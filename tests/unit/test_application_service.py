from __future__ import annotations

import asyncio
import json
import logging
import traceback
from pathlib import Path

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.core.contracts import (
    ApprovalMode,
    EngineEvent,
    EngineEventType,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    MessageTarget,
    PendingOperation,
)
from pair_harness.desktop_backend.application_service import (
    _failure_reason,
    build_configured_service,
    build_demo_service,
)
from tests.service_helpers import call, expect_service_error, wait_until

CUSTOMIZATION_PATH = "/api/v1/services/audio/tts/customization"


class _CrashingEngine(ScriptedCodingEngine):
    """run_turn 一开始就抛错的编程助手。"""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def run_turn(self, session_ref, request):
        raise self.error
        yield  # pragma: no cover - 保持 async generator 形态


def _turn_terminal(service, status: str) -> bool:
    return any(
        payload["turn"]["status"] == status
        for payload in service.event_log.payloads("turn.status_changed")
    )


async def test_bootstrap_contains_projects_conversation_and_voice_shape(service) -> None:
    snapshot = await call(service, "1", "app.bootstrap")
    assert snapshot["projects"][0]["path_available"] is True
    assert snapshot["current_conversation"]["pair_id"] == "phainon_ancient_machine"
    assert [pair["pair_id"] for pair in snapshot["pairs"]] == [
        "firefly_sam",
        "march7_fourth_mirror",
        "phainon_ancient_machine",
    ]
    assert [pair["binding_id"] for pair in snapshot["pairs"]] == [
        "builtin:firefly_sam",
        "builtin:march7_fourth_mirror",
        "builtin:phainon_ancient_machine",
    ]
    assert all(pair["source"] == "builtin" for pair in snapshot["pairs"])
    assert snapshot["catalog_version"] == 0
    # 快照 pair 仍是当前搭档的内置形状；目录项额外带绑定 id 与角色摘要。
    current = snapshot["pairs"][-1]
    assert current["pair_id"] == snapshot["pair"]["pair_id"]
    assert current["assistant"] == snapshot["pair"]["assistant"]
    assert current["theme"] == snapshot["pair"]["theme"]
    assert current["character"]["name"] == snapshot["pair"]["character"]["name"]
    assert snapshot["messages"] == []
    assert snapshot["voice"]["supported"] is False
    assert snapshot["voice"]["speech_queue_len"] == 0
    assert snapshot["busy"] is False
    assert snapshot["active_tasks"] == []
    assert snapshot["sequence"] == -1

    service.emitter.emit("test.event", {})
    assert service.bootstrap()["sequence"] == service.event_log.items[-1]["sequence"]


async def test_bootstrap_approvals_json_serializable_with_pending(service) -> None:
    """有挂起审批时快照里的审批是可编码的 JSON 对象。"""
    op = PendingOperation(tool_kind="shell", command="npm test", paths=(), summary="跑测试")
    request_task = asyncio.create_task(
        service.approval_broker.request(op, "a1", "风险规则", "conv-1", "task-1")
    )
    await wait_until(lambda: service.approval_broker.snapshot(), message="审批应挂起")

    snapshot = await call(service, "1", "app.bootstrap")
    json.dumps(snapshot)
    assert snapshot["approvals"] == [
        {
            "approval_id": "a1",
            "conversation_id": "conv-1",
            "task_id": "task-1",
            "operation": {
                "tool_kind": "shell",
                "command": "npm test",
                "paths": [],
                "patch_file_count": None,
                "summary": "跑测试",
            },
            "reason": "风险规则",
        }
    ]

    service.approval_broker.resolve("a1", "deny")
    await request_task


async def test_sidecar_restart_restores_pair_and_finishes_orphaned_delegation(
    tmp_path: Path,
) -> None:
    """重启以聊天记录里的搭档为准，并一次性恢复中断的工作：委派卡标为失败，处理中的队列项退回排队。"""
    database = tmp_path / "data" / "pair_harness.db"
    first = build_demo_service(
        database=database,
        project_root=tmp_path,
        pair_id="march7_fourth_mirror",
    )
    conversation_id = first.current_conversation_id
    delegation = Message(
        conversation_id=conversation_id,
        pair_id="march7_fourth_mirror",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="查看并介绍项目",
        target=MessageTarget.ASSISTANT,
        origin=MessageOrigin.CHARACTER_DELEGATION,
        delegation_id="orphan-task",
        status=MessageStatus.PROCESSING,
    )
    first.store.save_message(delegation)
    queued = first.store.enqueue_queue_item(
        conversation_id=conversation_id,
        target="assistant",
        text="队列中的任务",
        intent="followup",
        account_id=first.current_account_id,
    )
    first.store.set_queue_item_status(queued["queue_item_id"], "processing")
    await first.shutdown()

    # 重启调用方仍传入默认搭档，业务状态应以聊天记录为准。
    second = build_demo_service(database=database, project_root=tmp_path)
    try:
        assert second.pair_config.pair_id == "march7_fourth_mirror"
        snapshot = second.bootstrap()
        assert snapshot["pair"]["pair_id"] == "march7_fourth_mirror"
        assert snapshot["current_conversation"]["pair_id"] == "march7_fourth_mirror"
        restored = next(
            message
            for message in snapshot["messages"]
            if message["message_id"] == delegation.message_id
        )
        assert restored["status"] == "failed"
        assert "Sidecar 在委派完成前断开" in restored["payload"]["error"]
        assert second.store.list_queue_items(conversation_id)[0]["status"] == "queued"
    finally:
        await second.shutdown()


async def test_chat_submit_emits_messages_and_direct_task_tool_updates(service) -> None:
    events = service.event_log.items
    conversation_id = service.current_conversation_id
    # chat.submit 同步落库并立即返回真实 message_id，回合在后台推进。
    result = await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="character",
        text="今天有点累，陪我聊聊。",
    )
    assert result["message_id"]
    assert result["status"] == "received"
    assert result["target"] == "character"
    assert events[0]["event"] == "message.created"
    assert events[0]["payload"]["message"]["source"] == "user"
    await wait_until(
        lambda: [e["event"] for e in events].count("message.created") == 2,
        message="后台回合应补发角色消息",
    )

    await call(
        service,
        "settings-1",
        "project.update_settings",
        approval_mode=ApprovalMode.FULL_AUTO.value,
    )
    events.clear()
    result = await call(
        service,
        "task-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="assistant",
        mode="collaboration",
        text="请检查这个项目",
    )
    assert result["message_id"]
    assert result["status"] == "received"
    await wait_until(
        lambda: _turn_terminal(service, "completed"),
        message="后台助手回合应执行到完成",
    )
    event_names = [event["event"] for event in events]
    assert "task.busy_changed" in event_names
    assert "message.delta" in event_names
    assert "tool_run.upserted" in event_names
    # turn 终态是本回合最后一个事件，前端据此收尾。
    assert event_names[-1] == "turn.status_changed"


async def test_project_and_conversation_commands_return_restorable_snapshot(
    service,
) -> None:
    project_root = service.tmp_path / "another-project"
    project_root.mkdir()
    snapshot = await call(
        service, "p-1", "project.create", root_path=str(project_root), name="另一个项目"
    )
    assert snapshot["current_project"]["name"] == "另一个项目"
    conversation_id = snapshot["current_conversation_id"]
    await call(
        service, "r-1", "conversation.rename", conversation_id=conversation_id, title="已改名"
    )
    await service.shutdown()

    restored = build_demo_service(
        database=service.store.database, project_root=service.tmp_path
    )
    try:
        snapshot = await call(restored, "b-1", "app.bootstrap")
        assert snapshot["current_project"]["name"] == "另一个项目"
        assert snapshot["current_conversation_id"] == conversation_id
        assert snapshot["current_conversation"]["title"] == "已改名"
    finally:
        await restored.shutdown()


async def test_project_defaults_to_folder_name_and_manual_name_survives_path_repair(
    service,
) -> None:
    first_root = service.tmp_path / "folder-a"
    second_root = service.tmp_path / "folder-b"
    first_root.mkdir()
    second_root.mkdir()
    snapshot = await call(service, "p-1", "project.create", root_path=str(first_root))
    project_id = snapshot["current_project_id"]
    assert snapshot["current_project"]["name"] == "folder-a"

    result = await call(
        service, "rename-1", "project.update_settings", project_id=project_id, name="我的项目"
    )
    assert result["project"]["name"] == "我的项目"

    result = await call(
        service,
        "repair-1",
        "project.update_settings",
        project_id=project_id,
        root_path=str(second_root),
    )
    assert result["project"]["root_path"] == str(second_root.resolve())
    assert result["project"]["name"] == "我的项目"


async def test_project_archive_works_for_current_last_project(service) -> None:
    snapshot = await call(
        service, "archive-1", "project.archive", project_id=service.current_project_id
    )
    assert snapshot["projects"] == []
    assert snapshot["current_project_id"] == ""
    assert snapshot["current_conversation_id"] == ""
    assert snapshot["current_project"]["project_id"] == ""
    await service.shutdown()

    restored = build_demo_service(
        database=service.store.database, project_root=service.tmp_path
    )
    try:
        restored_snapshot = restored.bootstrap()
        assert restored_snapshot["projects"] == []
        assert restored_snapshot["current_project_id"] == ""
    finally:
        await restored.shutdown()


class _GatedTitleModel(ScriptedDialogueModel):
    """标题请求挂起，直到测试放行。"""

    def __init__(self) -> None:
        super().__init__()
        self.title_started = asyncio.Event()
        self.release_title = asyncio.Event()

    async def generate_title(self, *, pair_id, context):
        self.title_started.set()
        await self.release_title.wait()
        return await super().generate_title(pair_id=pair_id, context=context)


def _title_events(service, conversation_id: str) -> list[str]:
    return [
        payload["conversation"]["title"]
        for payload in service.event_log.payloads("conversation.changed")
        if payload["conversation"]["conversation_id"] == conversation_id
    ]


async def test_first_complete_reply_generates_title_from_dialogue(service) -> None:
    conversation_id = service.current_conversation_id
    assert service.store.get_conversation(conversation_id).title == "新聊天"
    await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="character",
        text="请陪我规划一下今天的工作。",
    )
    await wait_until(
        lambda: _title_events(service, conversation_id),
        message="首次完整回复后应生成并广播标题",
    )
    conversation = service.store.get_conversation(conversation_id)
    assert _title_events(service, conversation_id) == [conversation.title]
    assert "请陪我规划" in conversation.title
    assert conversation.title_source == "auto"
    # 命名上下文是首条用户消息与首轮完整角色回复。
    [(_, context)] = service.dialogue_model.title_requests
    assert [message.source for message in context] == [
        MessageSource.USER,
        MessageSource.CHARACTER,
    ]
    assert all(message.text.strip() for message in context)


@pytest.mark.parametrize("rename_at", ["before_reply", "during_generation"])
async def test_manual_rename_is_not_overwritten_by_auto_title(
    service, rename_at: str
) -> None:
    """回复完成前改名则不再命名；标题生成途中改名，生成结果也不写入。"""
    model = _GatedTitleModel()
    service.orchestrator.dialogue_model = model
    conversation_id = service.current_conversation_id
    try:
        await call(
            service,
            "chat-1",
            "chat.submit",
            conversation_id=conversation_id,
            target="character",
            text="这是一个会被手动命名的聊天。",
        )
        if rename_at == "during_generation":
            await asyncio.wait_for(model.title_started.wait(), timeout=5.0)
        await call(
            service,
            "rename-1",
            "conversation.rename",
            conversation_id=conversation_id,
            title="手动命名",
        )
        model.release_title.set()
        await wait_until(
            lambda: _turn_terminal(service, "completed"),
            message="回合应完成",
        )
        # 回合完成时已经决定是否命名；等标题任务全部结束再看最终结果。
        await wait_until(lambda: not service._title_tasks, message="标题任务应结束")
    finally:
        model.release_title.set()

    conversation = service.store.get_conversation(conversation_id)
    assert conversation.title == "手动命名"
    assert conversation.title_source == "user"
    assert _title_events(service, conversation_id) == ["手动命名"]
    assert model.title_started.is_set() is (rename_at == "during_generation")


async def test_streaming_assistant_events_reconcile_to_persisted_segments(service) -> None:
    """助手输出按工具边界分段，流式 delta 与落库消息按 id 对账。"""
    events = service.event_log.items
    await call(
        service,
        "settings-1",
        "project.update_settings",
        approval_mode=ApprovalMode.FULL_AUTO.value,
    )
    await call(
        service,
        "task-1",
        "chat.submit",
        conversation_id=service.current_conversation_id,
        target="assistant",
        mode="collaboration",
        text="请检查这个项目",
    )
    await wait_until(
        lambda: _turn_terminal(service, "completed"),
        message="后台回合应完成",
        timeout=20.0,
    )

    delta_ids = {
        event["payload"]["message_id"] for event in events if event["event"] == "message.delta"
    }
    finalized_ids = {
        event["payload"]["message_id"]
        for event in events
        if event["event"] == "message.finalized"
    }
    snapshot = service.bootstrap()
    assistant_messages = [
        message for message in snapshot["messages"] if message["source"] == "assistant"
    ]
    assert delta_ids
    # 演示脚本：工具前的说明段 + 工具后的最终正文段。
    assert len(assistant_messages) == 2
    assert assistant_messages[0]["message_id"] in delta_ids
    # 流式占位都由 final 收尾；没有流式的最终段直接以 message.created 落库。
    assert delta_ids <= finalized_ids
    # 消息与工具卡共享单调 timeline_order。
    for message in assistant_messages:
        assert message["task_id"]
        assert message["timeline_order"] is not None
    assert snapshot["tool_runs"]
    assert all(run["timeline_order"] is not None for run in snapshot["tool_runs"])


class _ReplayEngine(ScriptedCodingEngine):
    """按给定的事件类型与载荷回放一次引擎回合。"""

    def __init__(self, script: list[tuple[EngineEventType, dict, str | None]]) -> None:
        super().__init__()
        self.script = script

    async def run_turn(self, session_ref, request):
        for sequence, (event_type, payload, tool_call_id) in enumerate(self.script):
            yield EngineEvent(
                sequence=sequence,
                type=event_type,
                conversation_id=request.conversation_id,
                task_id=request.task_id,
                engine_turn_id="replay-turn",
                tool_call_id=tool_call_id,
                payload=payload,
            )


async def test_assistant_segment_needs_text_or_reasoning_to_be_persisted(service) -> None:
    """既无正文也无思考的段不落库；只有思考的段保留为正文为空的消息。"""
    tool = {"status": "succeeded", "title": "列目录", "summary": "完成"}
    service.orchestrator.coding_engine = _ReplayEngine(
        [
            (EngineEventType.TURN_STARTED, {}, None),
            (EngineEventType.ASSISTANT_DELTA, {"text": ""}, None),
            (EngineEventType.TOOL_STARTED, {"title": "列目录"}, "tool-1"),
            (EngineEventType.TOOL_FINISHED, tool, "tool-1"),
            (
                EngineEventType.ASSISTANT_REASONING_DELTA,
                {"text": "先列目录，再写文件", "channel": "content"},
                None,
            ),
            (EngineEventType.TOOL_STARTED, {"title": "写文件"}, "tool-2"),
            (EngineEventType.TOOL_FINISHED, {**tool, "title": "写文件"}, "tool-2"),
            (EngineEventType.ASSISTANT_FINAL, {"text": "完成。"}, None),
            (EngineEventType.TURN_COMPLETED, {"status": "completed"}, None),
        ]
    )
    conversation_id = service.current_conversation_id
    await call(
        service,
        "task-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="assistant",
        mode="collaboration",
        text="整理项目",
    )
    await wait_until(lambda: _turn_terminal(service, "completed"), message="回合应完成")

    segments = [
        message
        for message in service.store.load_conversation(conversation_id).messages
        if message.kind == MessageKind.ASSISTANT_NATURAL_LANGUAGE
    ]
    assert [message.message_id.rsplit(":", 1)[-1] for message in segments] == ["1", "2"]
    assert segments[0].text == ""
    assert segments[0].payload["reasoning"] == "先列目录，再写文件"
    assert segments[0].status == MessageStatus.DONE
    assert segments[1].text == "完成。"


@pytest.mark.parametrize("mode", [None, "collaboration"])
async def test_chat_submit_persists_mode_only_when_given(service, mode: str | None) -> None:
    """不带 mode 的提交不改写聊天模式；显式携带时按请求保存。"""
    conversation_id = service.current_conversation_id
    assert service.store.get_conversation(conversation_id).last_mode == "chat"
    params = {"mode": mode} if mode else {}
    await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="character",
        text="普通消息",
        **params,
    )
    assert service.store.get_conversation(conversation_id).last_mode == (mode or "chat")


async def test_chat_mode_rejects_assistant_target(service) -> None:
    conversation_id = service.current_conversation_id
    await expect_service_error(
        lambda: call(
            service,
            "chat-1",
            "chat.submit",
            conversation_id=conversation_id,
            target="assistant",
            text="执行任务",
        ),
        "assistant_not_allowed_in_chat_mode",
    )
    assert service.orchestrator.state.active_tasks() == []
    assert service.store.load_conversation(conversation_id).messages == ()


async def _publish_card(service, name: str) -> str:
    """建一张已发布（可用）的角色卡；发布时自动绑定默认搭档。"""
    created = await call(service, f"{name}-draft", "card.create_draft", name=name)
    card_id = created["card_id"]
    await call(
        service,
        f"{name}-update",
        "card.update",
        card_id=card_id,
        card={"name": name, "first_mes": "你好"},
    )
    await call(service, f"{name}-publish", "card.publish", card_id=card_id)
    return card_id


def _card_conversation(service, card_id: str, *, archived: bool = False) -> str:
    """在当前项目建一个绑定角色卡的聊天，带一条历史消息。"""
    binding = service.binding_repository.find_binding(
        card_id, service.pair_config.pair_id
    )
    conversation = service.store.create_conversation(
        pair_id=service.pair_config.pair_id,
        project_id=service.current_project_id,
        title=f"卡聊天-{card_id}",
        account_id=service.current_account_id,
        character_card_id=card_id,
        binding_id=binding.binding_id if binding is not None else None,
    )
    service.store.save_message(
        Message(
            conversation_id=conversation.conversation_id,
            pair_id=conversation.pair_id,
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text="既有历史",
        )
    )
    if archived:
        service.store.archive_conversation(conversation.conversation_id)
    return conversation.conversation_id


@pytest.mark.parametrize(
    ("existing_card", "archived", "params", "reused"),
    [
        pytest.param(
            "same", False, {"character_card_id": "same", "reuse_active": True}, True,
            id="same-card",
        ),
        pytest.param(
            "same", False, {"character_card_id": "other", "reuse_active": True}, False,
            id="other-card",
        ),
        pytest.param(
            "same", False, {"character_card_id": "same"}, False,
            id="reuse-not-requested",
        ),
        pytest.param(
            "same", True, {"character_card_id": "same", "reuse_active": True}, False,
            id="archived",
        ),
        pytest.param(None, False, {"reuse_active": True}, False, id="without-card"),
    ],
)
async def test_conversation_create_reuse_active(
    service, existing_card: str | None, archived: bool, params: dict, reused: bool
) -> None:
    """reuse_active 只复用同项目、同绑定的未归档聊天，其他情况照常新建。"""
    cards: dict[str, str] = {}
    if existing_card is None:
        # 无绑定的普通会话不参与复用。
        existing = service.current_conversation_id
    else:
        cards = {
            "same": await _publish_card(service, "复用角色甲"),
            "other": await _publish_card(service, "复用角色乙"),
        }
        existing = _card_conversation(service, cards["same"], archived=archived)
    resolved_params = {
        key: (cards[value] if key == "character_card_id" else value)
        for key, value in params.items()
    }
    before = {
        conversation.conversation_id
        for conversation in service.store.list_conversations(service.current_project_id)
    }

    result = await call(service, "create-1", "conversation.create", **resolved_params)

    assert result["reused"] is reused
    after = {
        conversation.conversation_id
        for conversation in service.store.list_conversations(service.current_project_id)
    }
    if reused:
        assert result["current_conversation_id"] == existing
        assert after == before
        assert [message["text"] for message in result["messages"]] == ["既有历史"]
    else:
        assert result["current_conversation_id"] not in before
        assert after == before | {result["current_conversation_id"]}


async def test_archiving_other_projects_last_chat_refills_that_project(service) -> None:
    """归档非当前项目的最后一个聊天，新聊天补建在它自己的项目里。"""
    other_project = service.store.create_project(
        name="其他项目",
        root_path=str(service.tmp_path / "other"),
        account_id=service.current_account_id,
    )
    other_conversation = service.store.create_conversation(
        pair_id=service.pair_config.pair_id,
        project_id=other_project.project_id,
        title="其他项目聊天",
        account_id=service.current_account_id,
    )
    current_before = service.store.list_conversations(service.current_project_id)

    await call(
        service,
        "archive-1",
        "conversation.archive",
        conversation_id=other_conversation.conversation_id,
    )

    assert service.store.list_conversations(service.current_project_id) == current_before
    [refilled] = service.store.list_conversations(other_project.project_id)
    assert refilled.conversation_id != other_conversation.conversation_id
    assert refilled.archived is False


class _RecordingVoiceRuntime:
    """VoiceRuntime 的端口替身：记录服务下发的语音指令。

    ``transcript`` 非空时，松开按键说话会像真实运行时一样把识别文本交给
    ``on_text_input``；``ptt_stop_error`` 表示识别收尾失败。
    """

    def __init__(
        self,
        *,
        on_text_input=None,
        transcript: str = "",
        ptt_stop_error: Exception | None = None,
    ) -> None:
        self.on_text_input = on_text_input
        self.transcript = transcript
        self.ptt_stop_error = ptt_stop_error
        self.listening = False
        self.vad_enabled = False
        self.ptt_target: str | None = None
        self.stopped = False
        self.skips = 0
        self.contexts: list[tuple[str, str, str]] = []
        self.received: list[Message] = []
        self.replayed: list[Message] = []
        self.previews: list[tuple[str, str | None]] = []

    @property
    def speech_queue_len(self) -> int:
        return len(self.previews)

    def on_message(self, message: Message) -> None:
        self.received.append(message)

    async def interrupt_async(self, reason: str) -> None:
        del reason

    async def set_context_async(self, conversation_id, pair_config) -> None:
        self.contexts.append(
            (conversation_id, pair_config.pair_id, pair_config.character.voice_id)
        )

    async def start_listening(self, *, vad_enabled: bool = True) -> None:
        self.listening = True
        self.vad_enabled = vad_enabled

    async def set_vad_enabled(self, enabled: bool) -> None:
        self.vad_enabled = enabled

    async def stop_listening(self) -> None:
        self.listening = False

    def start_playback(self) -> None:
        pass

    async def push_to_talk_start(self, *, target: str) -> None:
        self.ptt_target = target

    async def push_to_talk_stop(self) -> None:
        target, self.ptt_target = self.ptt_target, None
        if self.ptt_stop_error is not None:
            raise self.ptt_stop_error
        if self.transcript:
            await self.on_text_input(self.transcript, target)

    async def stop_speaking_async(self) -> None:
        self.stopped = True

    def replay_message(self, message: Message) -> None:
        self.replayed.append(message)

    async def skip_playing_async(self) -> None:
        self.skips += 1

    def enqueue_text(self, text: str, *, voice_id: str | None = None) -> None:
        self.previews.append((text, voice_id))

    async def shutdown(self) -> None:
        pass


def _save_voice_config(service, voice_ids: dict[str, str]) -> None:
    """当前账号已保存语音 Key 与各说话方的专属音色。"""
    account_id = service.current_account_id
    service.store.set_configs_and_secrets(
        account_id,
        {f"voice.profile.{speaker}.voice_id": voice for speaker, voice in voice_ids.items()},
        {"voice.api_key": "test-key"},
    )


async def test_voice_commands_only_exchange_state_with_attached_runtime(service) -> None:
    runtime = _RecordingVoiceRuntime()
    service.attach_voice_runtime(runtime)
    assert service.bootstrap()["voice"]["supported"] is True
    assert service.bootstrap()["voice"]["speech_queue_len"] == 0
    await service.start_voice()
    assert runtime.listening is True
    assert runtime.vad_enabled is False
    assert service.bootstrap()["voice"]["vad_enabled"] is False
    assert service.bootstrap()["voice"]["assistant_voice_enabled"] is False

    await call(
        service,
        "assistant-voice-on",
        "config.set",
        updates={"assistant_voice_enabled": "true"},
    )
    assert service.bootstrap()["voice"]["assistant_voice_enabled"] is True
    await call(service, "vad-on", "voice.vad_set", enabled=True)
    assert runtime.vad_enabled is True
    await call(service, "ptt-on", "voice.ptt_start", target="character")
    assert runtime.ptt_target == "character"
    await call(service, "ptt-off", "voice.ptt_stop")
    await call(service, "tts-off", "voice.tts_stop")
    assert runtime.listening is True
    assert runtime.ptt_target is None
    assert runtime.stopped is True
    assert runtime.contexts[-1][:2] == (
        service.current_conversation_id,
        "phainon_ancient_machine",
    )
    changed = service.event_log.payloads("voice.state_changed")
    assert changed
    assert all(payload["voice"]["speech_queue_len"] == 0 for payload in changed)


async def test_invalid_pair_id_is_rejected_before_creating_records(service) -> None:
    existing_conversations = service.store.list_conversations(service.current_project_id)
    await expect_service_error(
        lambda: call(
            service,
            "invalid-conversation",
            "conversation.create",
            project_id=service.current_project_id,
            pair_id="not-a-pair",
        ),
        "PAIR_NOT_FOUND",
        contains="not-a-pair",
    )
    assert service.store.list_conversations(service.current_project_id) == existing_conversations

    invalid_project = service.tmp_path / "should-not-be-created"
    await expect_service_error(
        lambda: call(
            service,
            "invalid-project",
            "project.create",
            root_path=str(invalid_project),
            pair_id="not-a-pair",
        ),
        "PAIR_NOT_FOUND",
        contains="not-a-pair",
    )
    assert service.store.find_project_by_root_path(str(invalid_project.resolve())) is None


async def test_ptt_stop_failure_clears_listening_state_and_surfaces_error(service) -> None:
    runtime = _RecordingVoiceRuntime(ptt_stop_error=ValueError("角色模型未返回可用 speech"))
    service.attach_voice_runtime(runtime)
    await call(service, "ptt-start", "voice.ptt_start", target="character")
    assert service.bootstrap()["voice"]["ptt"] is True

    with pytest.raises(ValueError, match="角色模型未返回可用 speech"):
        await call(service, "ptt-stop-fail", "voice.ptt_stop")
    voice = service.bootstrap()["voice"]
    assert voice["ptt"] is False
    assert voice["error"] == "语音提交失败：角色模型未返回可用 speech"
    assert service.event_log.payloads("voice.state_changed")[-1]["voice"]["ptt"] is False


async def test_ptt_transcript_goes_to_conversation_captured_at_start(service) -> None:
    """按键说话开始时记下聊天与对象，录音期间切换聊天也提交到原聊天。"""
    runtime = _RecordingVoiceRuntime(transcript="语音文本")
    runtime.on_text_input = service._submit_voice_input
    service.attach_voice_runtime(runtime)
    captured = service.current_conversation_id
    await call(service, "ptt-start", "voice.ptt_start", target="character")
    other = await call(
        service, "create-1", "conversation.create", project_id=service.current_project_id
    )
    assert service.current_conversation_id == other["current_conversation_id"]

    await call(service, "ptt-stop", "voice.ptt_stop")

    [submitted] = [
        message
        for message in service.store.load_conversation(captured).messages
        if message.source == MessageSource.USER
    ]
    assert submitted.text == "语音文本"
    assert submitted.target == MessageTarget.CHARACTER
    assert service.store.load_conversation(other["current_conversation_id"]).messages == ()


async def test_voice_error_clears_when_synthesis_recovers_or_voice_toggles(service) -> None:
    """合成恢复只清除合成错误；语音总开关变化清除全部旧错误。"""
    # 语音运行时经 on_tts_state 与 on_error 回调上报状态。
    service._on_tts_state("failed")
    service._on_voice_error("语音合成失败：Requests rate limit exceeded")
    assert service.bootstrap()["voice"]["error"].startswith("语音合成失败")

    service._on_tts_state("playing")
    assert service.bootstrap()["voice"]["error"] is None

    service._on_voice_error("语音识别失败：连接中断")
    service._on_tts_state("idle")
    assert service.bootstrap()["voice"]["error"] == "语音识别失败：连接中断"

    await call(service, "cfg-voice", "config.set", updates={"voice.enabled": "false"})
    voice = service.bootstrap()["voice"]
    assert voice["error"] is None
    assert voice["enabled"] is False


async def test_voice_tts_play_skip_and_preview_commands(service) -> None:
    """tts_play 按 message_id 重播，tts_skip 跳过当前句，preview 把试听文本入队。"""
    runtime = _RecordingVoiceRuntime()
    service.attach_voice_runtime(runtime)
    _save_voice_config(service, {"phainon": "voice-phainon"})
    conversation_id = service.current_conversation_id
    result = await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="character",
        text="你好，白厄。",
    )
    message_id = result["message_id"]

    await call(service, "play-1", "voice.tts_play", message_id=message_id)
    assert [message.message_id for message in runtime.replayed] == [message_id]
    assert runtime.contexts[-1] == (
        conversation_id,
        "phainon_ancient_machine",
        "voice-phainon",
    )

    await call(service, "skip-1", "voice.tts_skip")
    assert runtime.skips == 1

    await call(service, "preview-1", "voice.preview", text="试听一下")
    assert runtime.previews == [("试听一下", "voice-phainon")]
    snapshot = await call(service, "b-1", "app.bootstrap")
    assert snapshot["voice"]["speech_queue_len"] == 1

    await expect_service_error(
        lambda: call(service, "play-2", "voice.tts_play", message_id="no-such-message"),
        "message_not_found",
    )
    await expect_service_error(
        lambda: call(service, "preview-2", "voice.preview", text="……"),
        "invalid_text",
    )


async def test_chat_submit_registers_turn_with_lifecycle_events(service) -> None:
    """一次提交对应一个 Turn：started(running) 后到达终态，快照按会话水合。"""
    conversation_id = service.current_conversation_id
    result = await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="character",
        text="今天状态怎么样？",
    )
    assert result["turn_id"]
    await wait_until(lambda: _turn_terminal(service, "completed"), message="回合应完成")

    [started] = service.event_log.payloads("turn.started")
    assert started["turn"]["turn_id"] == result["turn_id"]
    assert started["turn"]["status"] == "running"
    assert started["turn"]["source_message_id"] == result["message_id"]
    assert started["turn"]["conversation_id"] == conversation_id
    assert started["turn"]["project_id"] == service.current_project_id

    turns = [
        turn
        for turn in service.bootstrap()["turns"]
        if turn["conversation_id"] == conversation_id
    ]
    assert [(turn["turn_id"], turn["status"]) for turn in turns] == [
        (result["turn_id"], "completed")
    ]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        pytest.param(RuntimeError("引擎爆炸"), "引擎爆炸", id="message"),
        # 异常自述为空时，用户看到的原因是异常类型名。
        pytest.param(RuntimeError(), "RuntimeError", id="empty-message"),
    ],
)
async def test_failed_turn_marks_turn_failed_and_message_failed(
    service, error: Exception, reason: str
) -> None:
    """回合失败：turn 落 failed，用户消息标记失败并保留文字，系统消息带真实原因。"""
    events = service.event_log.items
    service.orchestrator.coding_engine = _CrashingEngine(error)
    conversation_id = service.current_conversation_id
    result = await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="assistant",
        mode="collaboration",
        text="检查项目",
    )
    user_message_id = result["message_id"]
    await wait_until(lambda: _turn_terminal(service, "failed"), message="回合应落 failed")

    [user_message] = [
        message for message in service.bootstrap()["messages"] if message["source"] == "user"
    ]
    assert user_message["message_id"] == user_message_id
    assert user_message["status"] == "failed"
    assert user_message["text"] == "检查项目"
    assert user_message["payload"]["error"] == reason
    assert any(
        payload["message"]["message_id"] == user_message_id
        for payload in service.event_log.payloads("message.status_changed")
    )
    notices = [
        payload["message"]["text"]
        for payload in service.event_log.payloads("message.created")
        if payload["message"]["source"] == "system"
    ]
    assert notices == [f"本次回复失败：{reason}"]
    # 失败路径同样收尾流式占位。
    assert any(event["event"] == "message.finalized" for event in events)


def test_failure_reason_falls_back_to_type_and_code() -> None:
    """异常自述为空时回落到类型名，带结构化 code 时一并给出。"""

    class _Coded(RuntimeError):
        def __init__(self) -> None:
            super().__init__()
            self.code = "provider_error"

    assert _failure_reason(RuntimeError("古代机械未返回最终回复")) == "古代机械未返回最终回复"
    assert _failure_reason(RuntimeError()) == "RuntimeError"
    assert _failure_reason(_Coded()) == "_Coded | code=provider_error"


async def test_account_register_login_and_snapshot_fields(service) -> None:
    """注册即登录，快照携带当前账号与账号列表。"""
    snapshot = await call(service, "b-1", "app.bootstrap")
    assert snapshot["current_account_id"] == "default-local"
    assert snapshot["current_account"]["username"] == "default"

    result = await call(
        service,
        "reg-1",
        "account.register",
        username="alice",
        display_name="爱丽丝",
        password="s3cret-pass",
    )
    account_id = result["account"]["account_id"]
    assert result["account"]["username"] == "alice"
    assert "password" not in result["account"]

    snapshot = await call(service, "b-2", "app.bootstrap")
    assert snapshot["current_account_id"] == account_id
    assert snapshot["current_account"]["display_name"] == "爱丽丝"
    assert [a["account_id"] for a in snapshot["accounts"] if a["is_last_login"]] == [account_id]
    assert len(snapshot["accounts"]) == 2

    await expect_service_error(
        lambda: call(
            service, "login-bad", "account.login", account_id=account_id, password="wrong-pass"
        ),
        "wrong_password",
    )
    logged = await call(
        service, "login-1", "account.login", account_id=account_id, password="s3cret-pass"
    )
    assert logged["account"]["account_id"] == account_id


async def test_account_switch_isolates_projects(service) -> None:
    default_project_id = service.current_project_id
    result = await call(
        service,
        "reg-1",
        "account.register",
        username="bob",
        display_name="鲍勃",
        password="bob-pass-1",
    )
    snapshot = await call(service, "b-1", "app.bootstrap")
    assert snapshot["current_account_id"] == result["account"]["account_id"]
    assert snapshot["projects"] == []
    # 新账号没有项目，当前项目与聊天指针清空，不残留上一账号的。
    assert snapshot["current_project_id"] == ""
    assert snapshot["current_conversation_id"] == ""

    back = await call(
        service, "login-1", "account.login", account_id="default-local", password=""
    )
    assert back["account"]["username"] == "default"
    snapshot = await call(service, "b-2", "app.bootstrap")
    assert any(p["project_id"] == default_project_id for p in snapshot["projects"])


async def test_account_onboarding_complete_marks_flag_only_on_command(service) -> None:
    """注册与登录不完成引导；account.onboarding_complete 显式置位并广播。"""
    events = service.event_log.items
    result = await call(
        service,
        "reg-1",
        "account.register",
        username="alice",
        display_name="爱丽丝",
        password="s3cret-pass",
    )
    assert result["account"]["onboarding_complete"] is False
    switched_snapshots = [event for event in events if event["event"] == "state.snapshot"]
    assert switched_snapshots
    assert all(
        event["payload"]["sequence"] == event["sequence"] for event in switched_snapshots
    )
    snapshot = await call(service, "b-1", "app.bootstrap")
    assert snapshot["current_account"]["onboarding_complete"] is False

    marked = await call(service, "ob-1", "account.onboarding_complete")
    assert marked["account"]["onboarding_complete"] is True
    changed = [event for event in events if event["event"] == "account.changed"]
    assert changed[-1]["payload"]["account"]["onboarding_complete"] is True
    assert changed[-1]["sequence"] == switched_snapshots[-1]["sequence"] + 1
    snapshot = await call(service, "b-2", "app.bootstrap")
    assert snapshot["current_account"]["onboarding_complete"] is True
    # 默认账号的引导状态不受影响。
    assert any(a["onboarding_complete"] is False for a in snapshot["accounts"])


async def test_account_switch_failure_keeps_original_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """目标账号的候选运行时构建失败时，当前账号、项目与聊天保持不变。"""
    for name in (
        "PAIR_HARNESS_DIALOGUE_BASE_URL",
        "PAIR_HARNESS_DIALOGUE_API_KEY",
        "PAIR_HARNESS_DIALOGUE_MODEL",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    service = build_configured_service(
        database=tmp_path / "data" / "pair_harness.db", project_root=tmp_path, demo=False
    )
    try:
        original = (
            service.current_account_id,
            service.current_project_id,
            service.current_conversation_id,
        )
        broken = service.store.create_account(
            username="broken-user", display_name="损坏账号", password="broken-pass-1"
        )
        # 目标账号保存的供应商与端点互相矛盾，按它构建运行时会被拒绝。
        service.store.set_configs_and_secrets(
            broken["account_id"],
            {
                "dialogue.provider": "deepseek",
                "dialogue.base_url": "https://gateway.example.com/v1",
            },
            {},
        )

        await expect_service_error(
            lambda: call(
                service, "switch-1", "account.switch", account_id=broken["account_id"]
            ),
            "provider_endpoint_mismatch",
        )
        assert (
            service.current_account_id,
            service.current_project_id,
            service.current_conversation_id,
        ) == original
        assert service.store.get_app_state("current_account_id") in (None, original[0])
    finally:
        await service.shutdown()


async def test_config_get_set_masks_secrets(service) -> None:
    """对话与语音 Key 按账号保存，读取时只回显掩码。"""
    updated = await call(
        service,
        "set-1",
        "config.set",
        updates={
            "dialogue.base_url": "https://api.deepseek.com",
            "dialogue.model": "deepseek-chat",
            "dialogue.api_key": "sk-super-secret-123456",
            "dialogue.reasoning_effort": "high",
            "voice.api_key": "voice-super-secret-abcdef",
            "voice.base_url": "https://dashscope.example/api/v1",
            "voice.enabled": "false",
            "assistant_voice_enabled": "true",
            "vad_enabled": "true",
        },
    )
    # 客户端不发送 engine，由后端推导。
    assert updated["config"]["engine"] == "reasonix"
    assert updated["config"]["dialogue"]["provider"] == "deepseek"
    assert updated["config"]["dialogue"]["provider_supported"] is True
    assert updated["config"]["dialogue"]["provider_unavailable"] is None
    config = await call(service, "get-1", "config.get")
    assert config == updated["config"]
    assert config["dialogue"]["model"] == "deepseek-chat"
    assert config["dialogue"]["reasoning_effort"] == "high"
    assert config["dialogue"]["api_key_masked"] == "sk-s…3456"
    assert config["voice"]["api_key_masked"] == "voic…cdef"
    assert config["voice"]["credential_source"] == "account"
    assert "super-secret" not in str(config)
    assert config["voice"]["base_url"] == "https://dashscope.example/api/v1"
    assert config["voice"]["asr_model"] == "qwen-audio-3.0-asr-flash-streaming"
    assert config["voice"]["tts_model"] == "qwen-audio-3.0-tts-flash"
    assert config["voice"]["voices_source"] == "account"
    assert config["voice"]["character_voice"] == ""
    assert config["voice"]["assistant_voice"] == ""
    assert config["voice"]["enabled"] == "false"
    assert config["voice"]["assistant_voice_enabled"] == "true"
    assert config["voice"]["vad_enabled"] == "true"
    assert config["voice"]["character_voice_name"] == "白厄"
    assert config["voice"]["assistant_voice_name"] == "神秘的古代机械"


async def test_config_get_distinguishes_development_env_voice_key_from_account_byok(
    service, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "env-only-voice-key")
    monkeypatch.setenv(
        "PAIR_HARNESS_DASHSCOPE_HTTP_URL",
        "https://dashscope.aliyuncs.com/api/v1",
    )
    config = await call(service, "get-env-voice", "config.get")
    assert config["voice"]["credential_source"] == "development_env"
    assert config["voice"]["api_key_masked"] == ""
    assert config["voice"]["asr_available"] is True
    assert "env-only-voice-key" not in str(config)


async def test_voice_provision_saves_returned_voice_id_and_keeps_it_on_failed_regeneration(
    service, replay_http
) -> None:
    """专属音色按 DashScope 返回的 voice_id 保存；重新生成失败时保留旧 ID 并显示失败。"""
    await call(
        service,
        "cfg-voice",
        "config.set",
        updates={
            "voice.api_key": "sk-voice-account",
            "voice.base_url": f"{replay_http.base_url}/api/v1",
        },
    )
    replay_http.reply(
        CUSTOMIZATION_PATH,
        200,
        {"output": {"voice_id": "qwen-tts-vc-phainon-001"}, "request_id": "req-clone-1"},
    )
    result = await call(service, "provision-1", "voice.provision", speaker_ids=["phainon"])
    assert result["status"] == "completed"
    assert result["results"][0]["voice_id"] == "qwen-tts-vc-phainon-001"
    completed = [
        payload
        for payload in service.event_log.payloads("voice.provision_changed")
        if payload["state"] == "completed"
    ]
    assert completed[-1]["voice_id"] == "qwen-tts-vc-phainon-001"
    [request] = replay_http.requests
    assert request.headers["Authorization"] == "Bearer sk-voice-account"
    assert request.body["input"]["prefix"] == "phainon"
    assert request.body["input"]["url"].startswith("data:audio/")

    replay_http.reply(
        CUSTOMIZATION_PATH,
        400,
        {
            "request_id": "req-clone-2",
            "code": "InvalidParameter",
            "message": "Audio duration is too short.",
        },
    )
    regenerated = await call(
        service,
        "provision-2",
        "voice.provision",
        speaker_ids=["phainon"],
        replace_existing=True,
    )
    assert regenerated["status"] == "partial_failed"
    config = await call(service, "voice-config", "config.get")
    phainon = next(
        item for item in config["voice"]["speakers"] if item["speaker_id"] == "phainon"
    )
    assert phainon["voice_id"] == "qwen-tts-vc-phainon-001"
    assert phainon["state"] == "failed"
    assert phainon["error"].startswith("HTTP 400 ")
    assert "Audio duration is too short." in phainon["error"]

    # 助手不使用语音，助手侧说话方不能生成专属音色，也不会发出请求。
    await expect_service_error(
        lambda: call(service, "provision-3", "voice.provision", speaker_ids=["sam"]),
        "assistant_voice_disabled",
    )
    assert len(replay_http.requests) == 2


async def test_voice_preview_allows_character_but_rejects_assistant_speakers(
    service,
) -> None:
    """试听只放行角色侧音色，助手侧音色与不属于当前账号的 ID 都被拒绝。"""
    runtime = _RecordingVoiceRuntime()
    service.attach_voice_runtime(runtime)
    _save_voice_config(
        service,
        {
            "phainon": "voice-phainon",
            "firefly": "voice-firefly",
            "sam": "voice-sam",
            "march7": "voice-march7",
            "fourth_mirror": "voice-fourth-mirror",
            "ancient_machine": "voice-ancient-machine",
        },
    )
    character_voice_ids = ["voice-phainon", "voice-firefly", "voice-march7"]
    for voice_id in character_voice_ids:
        await call(
            service, f"preview-{voice_id}", "voice.preview", text="试听角色", voice_id=voice_id
        )

    for voice_id, code in (
        ("voice-sam", "assistant_tts_disabled"),
        ("voice-fourth-mirror", "assistant_tts_disabled"),
        ("voice-ancient-machine", "assistant_tts_disabled"),
        ("voice-not-owned-by-current-account", "voice_preview_not_allowed"),
    ):
        await expect_service_error(
            lambda voice_id=voice_id: call(
                service,
                f"preview-{voice_id}",
                "voice.preview",
                text="试听",
                voice_id=voice_id,
            ),
            code,
        )
    assert [voice_id for _, voice_id in runtime.previews] == character_voice_ids


async def test_voice_tts_play_rejects_assistant_message(service) -> None:
    runtime = _RecordingVoiceRuntime()
    service.attach_voice_runtime(runtime)
    _save_voice_config(service, {"phainon": "voice-phainon"})
    assistant = Message(
        conversation_id=service.current_conversation_id,
        pair_id="phainon_ancient_machine",
        source=MessageSource.ASSISTANT,
        kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
        text="好的，我马上检查项目目录。",
    )
    service.store.save_message(assistant)

    await expect_service_error(
        lambda: call(
            service, "play-assistant", "voice.tts_play", message_id=assistant.message_id
        ),
        "assistant_tts_disabled",
    )
    assert runtime.replayed == []


async def test_config_set_accepts_voice_credentials_but_locks_models(service) -> None:
    """语音 Key 与服务地址可保存；语音模型和音色由应用固定，写入被拒绝。"""
    accepted = await call(
        service,
        "set-voice",
        "config.set",
        updates={
            "voice.api_key": "sk-user-voice",
            "voice.base_url": "dashscope.example/api/v1",
        },
    )
    assert accepted["config"]["voice"]["base_url"] == "https://dashscope.example/api/v1"
    assert accepted["config"]["voice"]["api_key_masked"] == "sk-u…oice"

    for key in ("voice.asr_model", "voice.tts_model", "character_voice", "assistant_voice"):
        await expect_service_error(
            lambda key=key: call(
                service, "set-locked", "config.set", updates={key: "user-value"}
            ),
            "voice_config_locked",
        )
    mixed = await call(
        service,
        "set-mixed",
        "config.set",
        updates={"voice.api_key": "sk-new-voice", "vad_enabled": "true"},
    )
    assert mixed["config"]["voice"]["vad_enabled"] == "true"
    assert mixed["config"]["voice"]["api_key_masked"] == "sk-n…oice"


async def test_api_key_never_appears_in_logs(service, caplog) -> None:
    """失败回合打出异常堆栈、切换账号加载配置时，日志里都没有 API Key。"""
    secret = "sk-leak-check-123456789"
    await call(service, "set-1", "config.set", updates={"dialogue.api_key": secret})
    service.orchestrator.coding_engine = _CrashingEngine(RuntimeError("引擎爆炸"))

    with caplog.at_level(logging.WARNING, logger="pair_harness"):
        await call(
            service,
            "chat-1",
            "chat.submit",
            conversation_id=service.current_conversation_id,
            target="assistant",
            mode="collaboration",
            text="检查项目",
        )
        await wait_until(lambda: _turn_terminal(service, "failed"), message="回合应落 failed")
        await call(
            service,
            "reg-1",
            "account.register",
            username="carol",
            display_name="卡罗",
            password="carol-pass-1",
        )
        await call(service, "b-1", "app.bootstrap")

    assert caplog.records
    for record in caplog.records:
        rendered = record.getMessage()
        if record.exc_info:
            rendered += "".join(traceback.format_exception(*record.exc_info))
        assert secret not in rendered


async def test_voice_runtime_receives_created_messages_via_listener_wiring(service) -> None:
    """挂上语音运行时后，落库的用户消息与角色回复都进入朗读入口。"""
    runtime = _RecordingVoiceRuntime()
    service.attach_voice_runtime(runtime)
    await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=service.current_conversation_id,
        target="character",
        text="你好，白厄。",
    )
    assert any(
        message.source == MessageSource.USER and message.text == "你好，白厄。"
        for message in runtime.received
    )
    await wait_until(
        lambda: any(message.source == MessageSource.CHARACTER for message in runtime.received),
        message="角色回复应进入语音朗读入口",
    )


def _listed_conversation_ids(snapshot: dict) -> set[str]:
    return {
        conversation["conversation_id"]
        for project in snapshot["projects"]
        for conversation in project["conversations"]
    }


async def test_conversation_and_engine_data_isolated_per_account(service) -> None:
    """切换账号后看不到上一账号的聊天，按 id 选择被拒；切回后完整恢复。"""
    default_conv = service.current_conversation_id
    await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=default_conv,
        target="assistant",
        mode="collaboration",
        text="检查项目",
    )
    assert default_conv in _listed_conversation_ids(await call(service, "b-0", "app.bootstrap"))

    await call(
        service,
        "reg-1",
        "account.register",
        username="dave",
        display_name="戴夫",
        password="dave-pass-1",
    )
    snapshot = await call(service, "b-1", "app.bootstrap")
    assert snapshot["projects"] == []
    assert snapshot["messages"] == []
    await expect_service_error(
        lambda: call(service, "sel-1", "conversation.select", conversation_id=default_conv),
        "conversation_account_mismatch",
    )

    await call(service, "login-1", "account.login", account_id="default-local", password="")
    snapshot = await call(service, "b-2", "app.bootstrap")
    assert snapshot["current_conversation_id"] == default_conv
    assert default_conv in _listed_conversation_ids(snapshot)


async def test_service_restart_restores_projects_for_current_account_only(service) -> None:
    """重启后按上次登录的账号恢复项目，不回落到默认账号的项目。"""
    await call(
        service,
        "reg-1",
        "account.register",
        username="restart-user",
        display_name="重启用户",
        password="restart-pass-1",
    )
    await service.shutdown()

    restored = build_demo_service(
        database=service.store.database, project_root=service.tmp_path
    )
    try:
        assert restored.current_account_id != "default-local"
        snapshot = restored.bootstrap()
        assert snapshot["projects"] == []
        assert snapshot["current_project_id"] == ""
        assert snapshot["current_conversation_id"] == ""
    finally:
        await restored.shutdown()


async def test_project_commands_reject_foreign_account_ids(service) -> None:
    foreign_project_id = service.current_project_id
    await call(
        service,
        "reg-1",
        "account.register",
        username="project-user",
        display_name="项目用户",
        password="project-pass-1",
    )
    for request_id, method, params in (
        ("select", "project.select", {"project_id": foreign_project_id}),
        ("update", "project.update_settings", {"project_id": foreign_project_id, "name": "越权"}),
        ("archive", "project.archive", {"project_id": foreign_project_id}),
        ("conversation", "conversation.create", {"project_id": foreign_project_id}),
    ):
        await expect_service_error(
            lambda request_id=request_id, method=method, params=params: call(
                service, request_id, method, **params
            ),
            "project_account_mismatch",
        )


async def test_new_conversation_belongs_to_current_account(service) -> None:
    await call(
        service,
        "reg-1",
        "account.register",
        username="erin",
        display_name="艾琳",
        password="erin-pass-1",
    )
    created = await call(
        service,
        "p-1",
        "project.create",
        root_path=str(service.tmp_path / "erin-project"),
        name="艾琳的项目",
    )
    conversation = await call(
        service,
        "c-1",
        "conversation.create",
        project_id=created["current_project_id"],
        title="艾琳的聊天",
    )
    erin_conv = conversation["current_conversation_id"]

    await call(service, "login-1", "account.login", account_id="default-local", password="")
    snapshot = await call(service, "b-1", "app.bootstrap")
    assert erin_conv not in _listed_conversation_ids(snapshot)


async def test_pairing_failure_budget_persists_across_restart(service) -> None:
    """配对码的累计错误次数在失败当刻落盘，Sidecar 重启不重置尝试预算。"""
    issued = await call(service, "c1", "remote.issue_code")
    valid_code = issued["code"]
    wrong_code = "000000" if valid_code != "000000" else "111111"

    def pair(target, request_id: str, code: str):
        return lambda: call(
            target, request_id, "remote.pair", origin="remote", code=code, device_name="phone"
        )

    for attempt in range(1, 5):
        await expect_service_error(pair(service, f"pair-{attempt}", wrong_code), "pairing_invalid_code")
        persisted = json.loads(service.store.get_app_state("remote.pairing_state"))
        assert persisted["code"]["failures"] == attempt
    await service.shutdown()

    restarted = build_demo_service(
        database=service.store.database, project_root=service.tmp_path
    )
    try:
        await expect_service_error(pair(restarted, "pair-5", wrong_code), "pairing_code_exhausted")
        # 配对码已作废，正确码也不能再配对。
        await expect_service_error(pair(restarted, "pair-6", valid_code), "pairing_invalid_code")
    finally:
        await restarted.shutdown()
