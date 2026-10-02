from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.core.contracts import (
    CharacterTurn,
    DialogueEvent,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    MessageOrigin,
    MessageStatus,
    TaskRequest,
)
from pair_harness.desktop_backend.application_service import build_demo_service
from tests.service_helpers import call, wait_until


class PausingEngine(ScriptedCodingEngine):
    """tool.started 后按任务挂起，制造确定的“任务运行中”。

    每个任务有自己的放行门闩（engine_turn_id → Event），cancel_turn 只放行
    目标任务，与真实引擎的 interrupt 语义一致。指令在 ``fail_instructions``
    里的任务一开始就抛错。
    """

    def __init__(self) -> None:
        super().__init__()
        self.gates: dict[str, asyncio.Event] = {}
        self.fail_instructions: set[str] = set()

    def release_all(self) -> None:
        for gate in self.gates.values():
            gate.set()

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self.requests.append(request)
        if request.instructions in self.fail_instructions:
            raise RuntimeError(f"执行失败：{request.instructions}")
        engine_turn_id = f"pause-{request.task_id}"
        gate = self.gates.setdefault(engine_turn_id, asyncio.Event())
        common = {
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "engine_turn_id": engine_turn_id,
        }
        yield EngineEvent(sequence=0, type=EngineEventType.TURN_STARTED, **common)
        yield EngineEvent(
            sequence=1,
            type=EngineEventType.TOOL_STARTED,
            tool_call_id=f"tool-{request.task_id[:8]}",
            payload={"title": "探测", "details": request.instructions},
            **common,
        )
        await gate.wait()
        yield EngineEvent(
            sequence=2,
            type=EngineEventType.TOOL_FINISHED,
            tool_call_id=f"tool-{request.task_id[:8]}",
            payload={"status": "succeeded", "title": "探测", "summary": "完成"},
            **common,
        )
        yield EngineEvent(
            sequence=3,
            type=EngineEventType.ASSISTANT_FINAL,
            payload={"text": "探测完成。"},
            **common,
        )
        yield EngineEvent(
            sequence=4,
            type=EngineEventType.TURN_COMPLETED,
            payload={"status": "completed"},
            **common,
        )

    async def cancel_turn(self, session_ref, turn_id: str) -> None:
        await super().cancel_turn(session_ref, turn_id)
        gate = self.gates.get(turn_id)
        if gate is not None:
            gate.set()


class BlockingDialogueModel(ScriptedDialogueModel):
    """第一轮角色回复流出一段 delta 后挂起，直到测试放行。"""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def stream_reply(self, request):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            yield DialogueEvent(type="speech.delta", delta="第一轮正在回复")
            await self.release.wait()
        yield DialogueEvent(
            type="character.final",
            turn=CharacterTurn(speech=f"第{self.calls}轮完成。"),
        )


@pytest.fixture
async def engine(service):
    engine = PausingEngine()
    service.orchestrator.coding_engine = engine
    yield engine
    engine.release_all()


def _turn_statuses(service, conversation_id: str) -> list[str]:
    """该聊天按发生顺序的回合终态。"""
    return [
        payload["turn"]["status"]
        for payload in service.event_log.payloads("turn.status_changed")
        if payload["turn"]["conversation_id"] == conversation_id
    ]


async def _submit_to_assistant(service, conversation_id: str, text: str) -> dict:
    return await call(
        service,
        f"submit-{text}",
        "chat.submit",
        conversation_id=conversation_id,
        target="assistant",
        mode="collaboration",
        text=text,
    )


async def _create_conversation(service, title: str) -> str:
    created = await call(
        service,
        f"create-{title}",
        "conversation.create",
        project_id=service.current_project_id,
        title=title,
    )
    return created["current_conversation_id"]


async def test_two_conversations_run_concurrently_and_isolate(service, engine) -> None:
    """同项目两个聊天的任务同时运行，忙碌集合与消息互不串线。"""
    conv_a = service.current_conversation_id
    conv_b = await _create_conversation(service, "聊天 B")
    await _submit_to_assistant(service, conv_a, "检查 A")
    await _submit_to_assistant(service, conv_b, "检查 B")
    await wait_until(lambda: len(engine.gates) == 2, message="两个聊天的任务应同时运行")
    assert {task["conversation_id"] for task in service.bootstrap()["active_tasks"]} == {
        conv_a,
        conv_b,
    }

    engine.release_all()
    await wait_until(
        lambda: _turn_statuses(service, conv_a) == ["completed"]
        and _turn_statuses(service, conv_b) == ["completed"],
        message="两个任务都应完成",
    )
    assert any(
        len(payload["active_tasks"]) == 2
        for payload in service.event_log.payloads("task.busy_changed")
    )
    for conversation_id, text in ((conv_a, "检查 A"), (conv_b, "检查 B")):
        messages = service.store.load_conversation(conversation_id).messages
        assert {message.conversation_id for message in messages} == {conversation_id}
        assert any(message.text == text for message in messages)


@pytest.mark.parametrize("ending", ["completed", "cancelled"])
async def test_queued_submit_runs_after_current_turn_ends(
    service, engine, ending: str
) -> None:
    """忙碌时的提交先入队且不落消息；当前回合完成或被取消后自动派发并出队。"""
    conversation_id = service.current_conversation_id
    await _submit_to_assistant(service, conversation_id, "第一条")
    await wait_until(lambda: len(engine.gates) == 1, message="第一条应开始运行")

    queued = await call(
        service,
        "submit-2",
        "chat.submit",
        conversation_id=conversation_id,
        target="assistant",
        text="第二条",
        intent="followup",
    )
    assert queued["queued"] is True
    assert queued["queue_item"]["status"] == "queued"
    changed = service.event_log.payloads("queue.changed")
    assert [item["text"] for item in changed[-1]["items"]] == ["第二条"]
    messages = service.store.load_conversation(conversation_id).messages
    assert all(message.text != "第二条" for message in messages)

    if ending == "completed":
        engine.release_all()
    else:
        task = service.orchestrator.state.get_for_conversation(conversation_id)
        cancelled = await call(
            service,
            "cancel-1",
            "task.cancel",
            conversation_id=conversation_id,
            task_id=task.task_id,
        )
        assert cancelled["cancelled"] is True
    await wait_until(lambda: len(engine.requests) == 2, message="队列项应被派发")
    assert engine.requests[1].instructions == "第二条"
    engine.release_all()
    await wait_until(
        lambda: len(_turn_statuses(service, conversation_id)) == 2,
        message="派发的队列项应走完自己的回合",
    )
    assert _turn_statuses(service, conversation_id) == [ending, "completed"]
    assert service.store.list_queue_items(conversation_id) == []


async def test_failed_queue_item_is_dequeued_and_queue_advances(service, engine) -> None:
    """排队项的回合失败时落 failed 终态并出队，下一条照常派发。"""
    engine.fail_instructions.add("会失败的排队项")
    conversation_id = service.current_conversation_id
    await _submit_to_assistant(service, conversation_id, "第一条")
    await wait_until(lambda: len(engine.gates) == 1, message="第一条应开始运行")
    for text in ("会失败的排队项", "之后的排队项"):
        queued = await _submit_to_assistant(service, conversation_id, text)
        assert queued["queued"] is True

    engine.release_all()
    await wait_until(lambda: len(engine.requests) == 3, message="失败后应继续派发下一条")
    engine.release_all()
    await wait_until(
        lambda: len(_turn_statuses(service, conversation_id)) == 3,
        message="三个回合都应进入终态",
    )
    assert _turn_statuses(service, conversation_id) == ["completed", "failed", "completed"]
    assert service.store.list_queue_items(conversation_id) == []
    failed = next(
        message
        for message in service.store.load_conversation(conversation_id).messages
        if message.text == "会失败的排队项"
    )
    assert failed.status == MessageStatus.FAILED
    assert failed.payload["error"] == "执行失败：会失败的排队项"


async def test_queue_edit_withdraw_and_prioritize(service, engine) -> None:
    conversation_id = service.current_conversation_id
    await _submit_to_assistant(service, conversation_id, "运行中的任务")
    await wait_until(lambda: len(engine.gates) == 1, message="任务应开始运行")
    first = await call(
        service, "chat-1", "chat.submit", conversation_id=conversation_id, text="第一条"
    )
    second = await call(
        service, "chat-2", "chat.submit", conversation_id=conversation_id, text="第二条"
    )
    first_item, second_item = first["queue_item"], second["queue_item"]
    assert (first_item["position"], second_item["position"]) == (0, 1)

    edited = await call(
        service,
        "edit-1",
        "queue.edit",
        queue_item_id=first_item["queue_item_id"],
        text="改过的第一条",
    )
    assert edited["queue_item"]["text"] == "改过的第一条"

    await call(
        service, "pri-1", "queue.prioritize", queue_item_id=second_item["queue_item_id"]
    )
    items = service.store.list_queue_items(conversation_id)
    assert [item["queue_item_id"] for item in items] == [
        second_item["queue_item_id"],
        first_item["queue_item_id"],
    ]
    assert [item["position"] for item in items] == [0, 1]

    withdrawn = await call(
        service, "wd-1", "queue.withdraw", queue_item_id=first_item["queue_item_id"]
    )
    assert withdrawn["queue_item"]["status"] == "withdrawn"
    assert (
        service.store.peek_queue_item(conversation_id)["queue_item_id"]
        == second_item["queue_item_id"]
    )
    # 两次入队与编辑、调序、撤回各推送一次全量队列。
    assert len(service.event_log.payloads("queue.changed")) == 5


async def test_queue_persists_across_service_restart(service, engine) -> None:
    conversation_id = service.current_conversation_id
    await _submit_to_assistant(service, conversation_id, "运行中的任务")
    await wait_until(lambda: len(engine.gates) == 1, message="任务应开始运行")
    queued = await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        text="跨重启的队列项",
    )
    assert queued["queued"] is True
    await service.shutdown()

    restored = build_demo_service(
        database=service.store.database, project_root=service.tmp_path
    )
    try:
        items = [
            item
            for item in restored.bootstrap()["queue_items"]
            if item["conversation_id"] == conversation_id
        ]
        assert [(item["text"], item["status"]) for item in items] == [
            ("跨重启的队列项", "queued")
        ]
    finally:
        await restored.shutdown()


async def test_role_turn_same_conversation_is_queued_while_streaming(service) -> None:
    """角色回复不占用编程助手的忙碌状态，同一聊天的第二条提交仍要排队。"""
    model = BlockingDialogueModel()
    service.orchestrator.dialogue_model = model
    try:
        conversation_id = service.current_conversation_id
        first = await call(
            service,
            "first",
            "chat.submit",
            conversation_id=conversation_id,
            target="character",
            text="第一条",
        )
        await asyncio.wait_for(model.started.wait(), timeout=5.0)

        second = await call(
            service,
            "second",
            "chat.submit",
            conversation_id=conversation_id,
            target="character",
            text="第二条",
        )
        assert second["queued"] is True
        assert second["queue_item"]["status"] == "queued"
        assert model.calls == 1
        assert first["message_id"] != second["queue_item"]["queue_item_id"]

        model.release.set()
        await wait_until(
            lambda: model.calls == 2
            and not service.store.list_queue_items(conversation_id),
            message="第一轮结束后应派发排队的第二条",
        )
    finally:
        model.release.set()


async def test_task_cancel_targets_precise_conversation_and_task(service, engine) -> None:
    """取消 A 不影响 B；错误的 task id 不产生取消。"""
    conv_a = service.current_conversation_id
    conv_b = await _create_conversation(service, "聊天 B")
    await _submit_to_assistant(service, conv_a, "A 任务")
    await _submit_to_assistant(service, conv_b, "B 任务")
    await wait_until(lambda: len(engine.gates) == 2, message="两个任务都应开始运行")

    wrong = await call(
        service, "cancel-wrong", "task.cancel", conversation_id=conv_a, task_id="not-a-task"
    )
    assert wrong["cancelled"] is False

    task_a = service.orchestrator.state.get_for_conversation(conv_a)
    result = await call(
        service, "cancel-a", "task.cancel", conversation_id=conv_a, task_id=task_a.task_id
    )
    assert result["cancelled"] is True
    await wait_until(
        lambda: _turn_statuses(service, conv_a) == ["cancelled"],
        message="A 应进入取消终态",
    )
    assert service.orchestrator.state.get_for_conversation(conv_b) is not None
    engine.release_all()
    await wait_until(
        lambda: _turn_statuses(service, conv_b) == ["completed"],
        message="B 应正常完成",
    )


async def test_conversation_open_loads_without_switching_current(service) -> None:
    """conversation.open 只读装载目标聊天，不改变全局当前聊天。"""
    project_id = service.current_project_id
    conv_a = service.current_conversation_id
    conv_b = await _create_conversation(service, "聊天 B")
    await call(service, "select-a", "conversation.select", conversation_id=conv_a)

    opened = await call(
        service, "open-b", "conversation.open", conversation_id=conv_b, view_id="window-2"
    )
    assert opened["conversation"]["conversation_id"] == conv_b
    assert opened["project"]["project_id"] == project_id
    assert opened["pair"]["pair_id"]
    assert {"messages", "tool_runs", "turns", "queue_items", "active_task"} <= set(opened)
    assert opened["stream_id"] == service.emitter.stream_id
    assert opened["sequence"] == service.emitter.next_sequence - 1
    assert service.current_conversation_id == conv_a


async def test_selecting_chat_keeps_running_delegation_processing(service, engine) -> None:
    """委派运行中选中或打开它所在的聊天，委派卡保持处理中，直到真实终态。"""
    conversation_id = service.current_conversation_id
    await _create_conversation(service, "聊天 B")
    await call(
        service,
        "delegate",
        "chat.submit",
        conversation_id=conversation_id,
        target="character",
        mode="collaboration",
        text="请交给古代机械检查项目",
    )
    await wait_until(lambda: len(engine.gates) == 1, message="委派应开始执行")

    def delegation_status() -> MessageStatus:
        messages = service.store.load_conversation(conversation_id).messages
        return next(
            message.status
            for message in messages
            if message.origin == MessageOrigin.CHARACTER_DELEGATION
        )

    assert delegation_status() == MessageStatus.PROCESSING
    await call(service, "select", "conversation.select", conversation_id=conversation_id)
    await call(
        service, "open", "conversation.open", conversation_id=conversation_id, view_id="w2"
    )
    assert delegation_status() == MessageStatus.PROCESSING

    engine.release_all()
    await wait_until(
        lambda: delegation_status() == MessageStatus.DONE,
        message="委派应按执行结果完成",
    )


async def test_background_chat_uses_its_own_pair_after_another_pair_is_selected(
    service,
) -> None:
    """提交给后台聊天的消息与模型请求使用该聊天自己的搭档。"""
    phainon_conversation = service.current_conversation_id
    await call(
        service,
        "create-march7",
        "conversation.create",
        project_id=service.current_project_id,
        title="三月七聊天",
        pair_id="march7_fourth_mirror",
    )
    assert service.pair_config.pair_id == "march7_fourth_mirror"

    await call(
        service,
        "submit-background-phainon",
        "chat.submit",
        conversation_id=phainon_conversation,
        target="character",
        mode="chat",
        text="你好",
    )
    await wait_until(
        lambda: _turn_statuses(service, phainon_conversation) == ["completed"],
        message="后台聊天的回合应完成",
    )
    messages = service.store.load_conversation(phainon_conversation).messages
    assert messages
    assert {message.pair_id for message in messages} == {"phainon_ancient_machine"}
