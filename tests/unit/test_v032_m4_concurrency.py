"""V0.3.2 M4：后端多聊天并发的服务级验收。

并发单位是 conversation：不同聊天的提交立即运行、A/B 事件互不串线；
同一聊天第二次提交进入本聊天队列；task.cancel 定向校验；
conversation.open 只读装载，不改变全局导航。
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    TaskRequest,
)
from pair_harness.desktop_backend.application_service import (
    ServiceError,
    build_demo_service,
)
from tests.unit.test_application_service import command


class PausingEngine(ScriptedCodingEngine):
    """tool.started 后按任务挂起：制造确定性的“任务运行中”。

    每个任务有自己的放行门闩（engine_turn_id → Event）；cancel_turn 只
    放行目标任务，模拟真实引擎的 interrupt 语义。
    """

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.gates: dict[str, asyncio.Event] = {}

    def release_all(self) -> None:
        for gate in self.gates.values():
            gate.set()

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self.requests.append(request)
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
        self.started.set()
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
        # 模拟真实引擎收到 interrupt 后只放行目标任务
        gate = self.gates.get(turn_id)
        if gate is not None:
            gate.set()


async def _wait_condition(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("条件在超时前未满足")


def _turn_done(events, conversation_id: str) -> bool:
    return any(
        e["event"] == "turn.status_changed"
        and e["payload"]["turn"]["status"] in {"completed", "failed", "cancelled"}
        and e["payload"]["turn"]["conversation_id"] == conversation_id
        for e in events
    )


async def _make_service(tmp_path, events):
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    # 演示引擎无原生执行前审批；用完全自动模式避免本地审批门控挂起
    await service.handle_command(
        command(
            "settings",
            "project.update_settings",
            project_id=service.current_project_id,
            approval_mode="full_auto",
        )
    )
    return service


@pytest.mark.asyncio
async def test_two_conversations_run_concurrently_and_isolate(tmp_path) -> None:
    """同项目双聊天同时运行；A/B 的 busy 事件与 active_tasks 互不覆盖。"""
    events: list[dict] = []
    service = await _make_service(tmp_path, events)
    engine = PausingEngine()
    service.orchestrator.coding_engine = engine
    try:
        project_id = service.current_project_id
        conv_a = service.current_conversation_id
        conv_b_resp = await service.handle_command(
            command(
                "conv-create",
                "conversation.create",
                project_id=project_id,
                title="聊天 B",
            )
        )
        conv_b = conv_b_resp["current_conversation_id"]

        # A、B 先后提交，两条都应立即运行（不被全局闸门排队）
        await service.handle_command(
            command(
                "submit-a",
                "chat.submit",
                conversation_id=conv_a,
                target="assistant",
                mode="collaboration",
                text="检查 A",
            )
        )
        await _wait_condition(lambda: engine.started.is_set())
        await service.handle_command(
            command(
                "submit-b",
                "chat.submit",
                conversation_id=conv_b,
                target="assistant",
                mode="collaboration",
                text="检查 B",
            )
        )
        await _wait_condition(
            lambda: len(engine.requests) >= 2
        )
        # 两个聊天同时 active
        actives = {
            turn.conversation_id
            for turn in service.orchestrator.state.active_tasks()
        }
        assert actives == {conv_a, conv_b}

        engine.release_all()
        await _wait_condition(lambda: _turn_done(events, conv_a))
        await _wait_condition(lambda: _turn_done(events, conv_b))

        # busy_changed 事件携带完整集合；A 结束后集合中仍应出现过 B
        busy_events = [e for e in events if e["event"] == "task.busy_changed"]
        assert any(
            len(e["payload"].get("active_tasks") or []) == 2 for e in busy_events
        )
        # 各自的消息不串线
        messages_a = service.store.load_conversation(conv_a)["messages"]
        messages_b = service.store.load_conversation(conv_b)["messages"]
        assert {m.conversation_id for m in messages_a} == {conv_a}
        assert {m.conversation_id for m in messages_b} == {conv_b}
        assert any(m.text == "检查 A" for m in messages_a)
        assert any(m.text == "检查 B" for m in messages_b)
    finally:
        engine.release_all()
        await service.shutdown()


@pytest.mark.asyncio
async def test_same_conversation_second_submit_queues(tmp_path) -> None:
    """同一聊天忙碌时第二条提交进入本聊天队列。"""
    events: list[dict] = []
    service = await _make_service(tmp_path, events)
    engine = PausingEngine()
    service.orchestrator.coding_engine = engine
    try:
        conv = service.current_conversation_id
        await service.handle_command(
            command(
                "submit-1",
                "chat.submit",
                conversation_id=conv,
                target="assistant",
                mode="collaboration",
                text="第一条",
            )
        )
        await _wait_condition(lambda: engine.started.is_set())
        queued = await service.handle_command(
            command(
                "submit-2",
                "chat.submit",
                conversation_id=conv,
                target="assistant",
                text="第二条",
                intent="followup",
            )
        )
        assert queued.get("queued") is True
        engine.gates[list(engine.gates)[0]].set()
        # 队列项在首个回合完成后自动派发
        await _wait_condition(lambda: len(engine.requests) >= 2)
        assert engine.requests[1].instructions == "第二条"
    finally:
        engine.release_all()
        await service.shutdown()


@pytest.mark.asyncio
async def test_task_cancel_targets_precise_conversation_and_task(tmp_path) -> None:
    """取消 A 不影响 B；错误的 task id 不产生取消。"""
    events: list[dict] = []
    service = await _make_service(tmp_path, events)
    engine = PausingEngine()
    service.orchestrator.coding_engine = engine
    try:
        project_id = service.current_project_id
        conv_a = service.current_conversation_id
        conv_b = (
            await service.handle_command(
                command(
                    "conv-create",
                    "conversation.create",
                    project_id=project_id,
                    title="聊天 B",
                )
            )
        )["current_conversation_id"]

        for cid, text in ((conv_a, "A 任务"), (conv_b, "B 任务")):
            await service.handle_command(
                command(
                    f"submit-{cid[:6]}",
                    "chat.submit",
                    conversation_id=cid,
                    target="assistant",
                    mode="collaboration",
                    text=text,
                )
            )
        await _wait_condition(lambda: len(engine.requests) >= 2)

        # 错误的 task id：不取消
        wrong = await service.handle_command(
            command(
                "cancel-wrong",
                "task.cancel",
                conversation_id=conv_a,
                task_id="not-a-task",
            )
        )
        assert wrong["cancelled"] is False

        task_a = service.orchestrator.state.get_for_conversation(conv_a)
        result = await service.handle_command(
            command(
                "cancel-a",
                "task.cancel",
                conversation_id=conv_a,
                task_id=task_a.task_id,
            )
        )
        assert result["cancelled"] is True
        await _wait_condition(lambda: _turn_done(events, conv_a))
        # B 仍在运行，随后正常完成
        assert service.orchestrator.state.get_for_conversation(conv_b) is not None
        engine.release_all()
        await _wait_condition(lambda: _turn_done(events, conv_b))
        turn_statuses = {
            e["payload"]["turn"]["conversation_id"]: e["payload"]["turn"]["status"]
            for e in events
            if e["event"] == "turn.status_changed"
            and e["payload"]["turn"]["status"] in {"completed", "cancelled"}
        }
        assert turn_statuses.get(conv_a) == "cancelled"
        assert turn_statuses.get(conv_b) == "completed"
    finally:
        engine.release_all()
        await service.shutdown()


@pytest.mark.asyncio
async def test_conversation_open_loads_without_switching_current(tmp_path) -> None:
    """conversation.open 只读装载 B，不改变当前聊天，不清审批/会话。"""
    events: list[dict] = []
    service = await _make_service(tmp_path, events)
    try:
        project_id = service.current_project_id
        conv_a = service.current_conversation_id
        conv_b = (
            await service.handle_command(
                command(
                    "conv-create",
                    "conversation.create",
                    project_id=project_id,
                    title="聊天 B",
                )
            )
        )["current_conversation_id"]
        # current 切回 A
        await service.handle_command(
            command("select-a", "conversation.select", conversation_id=conv_a)
        )
        assert service.current_conversation_id == conv_a

        opened = await service.handle_command(
            command(
                "open-b",
                "conversation.open",
                conversation_id=conv_b,
                view_id="window-2",
            )
        )
        assert opened["conversation"]["conversation_id"] == conv_b
        assert opened["project"]["project_id"] == project_id
        assert opened["pair"]["pair_id"]
        assert "messages" in opened and "tool_runs" in opened
        assert "turns" in opened and "queue_items" in opened
        assert "active_task" in opened
        # 只读：全局当前聊天不变
        assert service.current_conversation_id == conv_a
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_background_chat_uses_its_own_pair_after_another_pair_is_selected(
    tmp_path,
) -> None:
    """显式提交旧聊天时，用户/角色消息与模型请求都绑定
    该聊天的 pair，不读取后来选中的全局 pair。
    """
    events: list[dict] = []
    service = await _make_service(tmp_path, events)
    try:
        project_id = service.current_project_id
        phainon_conversation = service.current_conversation_id
        await service.handle_command(
            command(
                "create-march7",
                "conversation.create",
                project_id=project_id,
                title="三月七聊天",
                pair_id="march7_fourth_mirror",
            )
        )
        assert service.orchestrator.pair_id == "march7_fourth_mirror"

        await service.handle_command(
            command(
                "submit-background-phainon",
                "chat.submit",
                conversation_id=phainon_conversation,
                target="character",
                mode="chat",
                text="你好",
            )
        )
        await _wait_condition(lambda: _turn_done(events, phainon_conversation))
        messages = service.store.load_conversation(phainon_conversation)["messages"]
        assert messages
        assert {message.pair_id for message in messages} == {
            "phainon_ancient_machine"
        }
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_bootstrap_contains_active_tasks_field(tmp_path) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        snapshot = service.bootstrap()
        assert "active_tasks" in snapshot
        assert snapshot["active_tasks"] == []
        assert snapshot["active_task"] is None
    finally:
        await service.shutdown()
