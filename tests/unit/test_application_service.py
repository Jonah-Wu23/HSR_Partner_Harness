from __future__ import annotations

import asyncio
import json
import logging
import traceback
from pathlib import Path
from typing import Any

import pytest

from pair_harness.adapters.acp.engine import AcpCodingEngine
from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.audio.qwen_voice_customization import CustomizationResult
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    DialogueEvent,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    MessageTarget,
    PendingOperation,
)
from pair_harness.desktop_backend.application_service import (
    ServiceError,
    build_demo_service,
)
from pair_harness.desktop_backend.commands import DesktopCommand


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


async def _wait_until(
    predicate, *, message: str, timeout: float = 5.0
) -> None:
    """轮询等待条件成立（同步谓词）；超时抛 AssertionError。

    与各测试内联的 wait_for 等价；供需要真实等待后台回合完成的测试复用。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


@pytest.mark.asyncio
async def test_bootstrap_contains_projects_conversation_and_voice_shape(tmp_path: Path) -> None:
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        snapshot = await service.handle_command(command("1", "app.bootstrap"))
        assert snapshot["projects"][0]["path_available"] is True
        assert snapshot["current_conversation"]["pair_id"] == "phainon_ancient_machine"
        assert [pair["pair_id"] for pair in snapshot["pairs"]] == [
            "firefly_sam",
            "march7_fourth_mirror",
            "phainon_ancient_machine",
        ]
        assert snapshot["pairs"][-1] == snapshot["pair"]
        assert snapshot["messages"] == []
        assert snapshot["voice"]["supported"] is False
        # V0.2 M4：voice 快照携带待播队列长度（VoiceMiniPlayer 的 queuedCount）
        assert snapshot["voice"]["speech_queue_len"] == 0
        assert snapshot["busy"] is False
        assert snapshot["sequence"] == -1

        service.emitter.emit("test.event", {})
        next_snapshot = service.bootstrap()
        assert next_snapshot["sequence"] == events[-1]["sequence"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_bootstrap_approvals_json_serializable_with_pending(tmp_path: Path) -> None:
    """V0.3.3 走查发现：broker.snapshot() 曾直接返回 PendingOperation 对象，
    有挂起审批时 app.bootstrap 响应编码失败，请求方永远等不到响应。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        op = PendingOperation(
            tool_kind="shell", command="npm test", paths=(), summary="跑测试"
        )
        request_task = asyncio.create_task(
            service.approval_broker.request(op, "a1", "风险规则", "conv-1", "task-1")
        )
        await asyncio.sleep(0)  # 让 request 注册进 _pending

        snapshot = await service.handle_command(command("1", "app.bootstrap"))
        json.dumps(snapshot)  # 响应必须可编码，不抛即通过
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
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_track_turn_task_rejects_overwriting_unfinished_task(tmp_path: Path) -> None:
    """M1.1：同一会话已有未完成任务时禁止覆盖任务引用。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        blocking = asyncio.Event()
        async def never() -> None:
            await blocking.wait()

        first = asyncio.create_task(never())
        service._track_turn_task("conversation-1", first)
        second = asyncio.create_task(never())
        with pytest.raises(RuntimeError, match="unfinished turn task"):
            service._track_turn_task("conversation-1", second)
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        blocking.set()
        await asyncio.gather(first, return_exceptions=True)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_sidecar_restart_restores_pair_and_finishes_orphaned_delegation(
    tmp_path: Path,
) -> None:
    """Sidecar 重启不得用默认搭档覆盖当前聊天，也不得留下 processing 委派。"""
    database = tmp_path / "data" / "pair_harness.db"
    first = build_demo_service(
        database=database,
        project_root=tmp_path,
        pair_id="march7_fourth_mirror",
    )
    conversation_id = first.current_conversation_id
    delegation = first.orchestrator._message(
        conversation_id=conversation_id,
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="查看并介绍项目",
        target=MessageTarget.ASSISTANT,
        origin=MessageOrigin.CHARACTER_DELEGATION,
        delegation_id="orphan-task",
        status=MessageStatus.PROCESSING,
    )
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
        assert second.orchestrator.pair_id == "march7_fourth_mirror"
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


@pytest.mark.asyncio
async def test_chat_submit_emits_messages_and_direct_task_tool_updates(tmp_path: Path) -> None:
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id

        async def wait_for(
            predicate, *, message: str, timeout: float = 5.0
        ) -> None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                if predicate():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError(message)

        # 快速接受：chat.submit 同步落库并立即返回真实 message_id
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="今天有点累，陪我聊聊。",
            )
        )
        assert result["message_id"]
        assert result["status"] == "received"
        assert result["target"] == "character"
        # 用户消息立即出现；后台回合随后补发角色消息
        await wait_for(
            lambda: events[0]["event"] == "message.created",
            message="首条用户消息应立即出现",
        )
        assert events[0]["payload"]["message"]["source"] == "user"
        await wait_for(
            lambda: [e["event"] for e in events].count("message.created") == 2,
            message="后台回合应补发角色消息",
        )

        await service.handle_command(
            command(
                "settings-1",
                "project.update_settings",
                approval_mode=ApprovalMode.FULL_AUTO.value,
            )
        )
        events.clear()
        result = await service.handle_command(
            command(
                "task-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="assistant",
                mode="collaboration",
                text="请检查这个项目",
            )
        )
        assert result["message_id"]
        assert result["status"] == "received"
        # 等待后台回合执行到完成（turn 终态是回合收尾信号，位于 busy 回落后）
        await wait_for(
            lambda: any(
                e["event"] == "turn.status_changed"
                and e["payload"]["turn"]["status"] == "completed"
                for e in events
            ),
            message="后台助手回合应执行到完成",
        )
        event_names = [event["event"] for event in events]
        assert "task.busy_changed" in event_names
        assert "message.delta" in event_names
        assert "tool_run.upserted" in event_names
        assert event_names[-1] == "turn.status_changed"
        assert events[-1]["payload"]["turn"]["status"] == "completed"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_project_and_conversation_commands_return_restorable_snapshot(
    tmp_path: Path,
) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    service = build_demo_service(
        database=database,
        project_root=tmp_path,
    )
    project_root = tmp_path / "another-project"
    project_root.mkdir()
    try:
        snapshot = await service.handle_command(
            command("p-1", "project.create", root_path=str(project_root), name="另一个项目")
        )
        assert snapshot["current_project"]["name"] == "另一个项目"
        conversation_id = snapshot["current_conversation_id"]
        await service.handle_command(
            command("r-1", "conversation.rename", conversation_id=conversation_id, title="已改名")
        )
    finally:
        await service.shutdown()

    restored = build_demo_service(database=database, project_root=tmp_path)
    try:
        snapshot = await restored.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_project"]["name"] == "另一个项目"
        assert snapshot["current_conversation_id"] == conversation_id
        assert snapshot["current_conversation"]["title"] == "已改名"
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_project_defaults_to_folder_name_and_manual_name_survives_path_repair(
    tmp_path: Path,
) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    first_root = tmp_path / "folder-a"
    second_root = tmp_path / "folder-b"
    first_root.mkdir()
    second_root.mkdir()
    try:
        snapshot = await service.handle_command(
            command("p-1", "project.create", root_path=str(first_root))
        )
        project_id = snapshot["current_project_id"]
        assert snapshot["current_project"]["name"] == "folder-a"

        result = await service.handle_command(
            command("rename-1", "project.update_settings", project_id=project_id, name="我的项目")
        )
        assert result["project"]["name"] == "我的项目"

        result = await service.handle_command(
            command(
                "repair-1",
                "project.update_settings",
                project_id=project_id,
                root_path=str(second_root),
            )
        )
        assert result["project"]["root_path"] == str(second_root.resolve())
        assert result["project"]["name"] == "我的项目"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_project_archive_works_for_current_last_project(tmp_path: Path) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        project_id = service.current_project_id
        snapshot = await service.handle_command(
            command("archive-1", "project.archive", project_id=project_id)
        )
        assert snapshot["projects"] == []
        assert snapshot["current_project_id"] == ""
        assert snapshot["current_conversation_id"] == ""
        assert snapshot["current_project"]["project_id"] == ""
    finally:
        await service.shutdown()

    restored = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        restored_snapshot = restored.bootstrap()
        assert restored_snapshot["projects"] == []
        assert restored_snapshot["current_project_id"] == ""
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_first_complete_reply_generates_title_from_dialogue_only_and_manual_name_wins(
    tmp_path: Path,
) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        conversation_id = service.current_conversation_id
        await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="请陪我规划一下今天的工作。",
            )
        )
        # 标题生成是后台异步任务，在首轮完整回复落库后启动，不打断对话。
        title_requests = getattr(service.dialogue_model, "title_requests")
        await _wait_until(
            lambda: len(title_requests) == 1,
            message="首轮完整回复后应异步生成一次标题请求",
        )
        _, context = title_requests[0]
        # 命名上下文必须同时包含首条用户消息和首轮完整角色回复。
        assert context
        assert any(
            message.source == MessageSource.USER
            and "请陪我规划一下今天的工作" in message.text
            for message in context
        )
        assert any(
            message.source == MessageSource.CHARACTER and message.text.strip()
            for message in context
        )
        conversation = service.store.get_conversation(conversation_id)
        assert conversation.title != "新聊天"
        assert "请陪我规划" in conversation.title
        assert conversation_id not in service._title_generation_started

        second = await service.handle_command(
            command("conversation-2", "conversation.create", project_id=service.current_project_id)
        )
        second_id = second["current_conversation_id"]
        await service.handle_command(
            command(
                "chat-2",
                "chat.submit",
                conversation_id=second_id,
                target="character",
                text="这是一个会被手动命名的聊天。",
            )
        )
        await service.handle_command(
            command(
                "rename-chat-2",
                "conversation.rename",
                conversation_id=second_id,
                title="手动命名",
            )
        )
        await asyncio.sleep(0)
        assert service.store.get_conversation(second_id).title == "手动命名"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_streaming_assistant_events_reconcile_to_persisted_segments(
    tmp_path: Path,
) -> None:
    """V0.3.2 M1：助手输出按工具边界拆段，delta 与持久化消息按 id 对账。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await service.handle_command(
            command(
                "settings-1",
                "project.update_settings",
                approval_mode=ApprovalMode.FULL_AUTO.value,
            )
        )
        conversation_id = service.current_conversation_id
        await service.handle_command(
            command(
                "task-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="assistant",
                mode="collaboration",
                text="请检查这个项目",
            )
        )
        # 快速接受后回合在后台运行：等待回合收尾（turn 终态 completed）
        async def _wait_turn_done() -> None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 5.0
            while loop.time() < deadline:
                if any(
                    e["event"] == "turn.status_changed"
                    and e["payload"]["turn"]["status"] == "completed"
                    for e in events
                ):
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("后台回合未在超时前结束")

        await _wait_turn_done()

        delta_ids = {
            event["payload"]["message_id"]
            for event in events
            if event["event"] == "message.delta"
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
        # 演示脚本：工具前的说明段 + 工具后的最终正文段
        assert len(assistant_messages) == 2
        message_ids = [message["message_id"] for message in assistant_messages]
        assert message_ids[0] in delta_ids
        # 流式占位必须被 final 收尾；未流式的最终段由 message.created 落库
        assert delta_ids <= finalized_ids
        # 分段 id 带 segment index；消息与工具卡共享单调 timeline_order
        for message in assistant_messages:
            assert message["task_id"]
            assert message["timeline_order"] is not None
        tool_runs = list(snapshot["tool_runs"])
        assert tool_runs
        assert all(run["timeline_order"] is not None for run in tool_runs)
        assert service.store.get_conversation(conversation_id).last_mode == "collaboration"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_commands_only_exchange_state_with_attached_runtime(tmp_path: Path) -> None:
    events: list[dict] = []

    class FakeVoiceRuntime:
        on_message = lambda self, _message: None
        # V0.2 M4：待播队列长度（VoiceMiniPlayer 的 queuedCount）
        speech_queue_len = 0

        def __init__(self) -> None:
            self.listening = False
            self.vad_enabled = False
            self.ptt = False
            self.stopped = False
            self.assistant_voice_enabled = False
            self.contexts: list[tuple[str, str, str]] = []

        async def set_context_async(self, conversation_id, pair_config) -> None:
            self.contexts.append(
                (
                    conversation_id,
                    pair_config.pair_id,
                    pair_config.character.voice_id,
                )
            )

        def set_assistant_voice_enabled(self, enabled: bool) -> None:
            self.assistant_voice_enabled = enabled

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
            del target
            self.ptt = True

        async def push_to_talk_stop(self) -> None:
            self.ptt = False

        def stop_speaking(self) -> None:
            self.stopped = True

        async def stop_speaking_async(self) -> None:
            self.stop_speaking()

        async def shutdown(self) -> None:
            pass

    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    runtime = FakeVoiceRuntime()
    service.attach_voice_runtime(runtime)  # type: ignore[arg-type]
    try:
        assert service.bootstrap()["voice"]["supported"] is True
        # V0.2 M4：voice 快照与事件都携带待播队列长度
        assert service.bootstrap()["voice"]["speech_queue_len"] == 0
        await service.start_voice()
        assert runtime.listening is True
        assert runtime.vad_enabled is False
        assert service.bootstrap()["voice"]["vad_enabled"] is False
        assert service.bootstrap()["voice"]["assistant_voice_enabled"] is False
        assert runtime.assistant_voice_enabled is False
        await service.handle_command(
            command(
                "assistant-voice-on",
                "config.set",
                updates={"assistant_voice_enabled": "true"},
            )
        )
        assert service.bootstrap()["voice"]["assistant_voice_enabled"] is True
        assert runtime.assistant_voice_enabled is True
        await service.handle_command(command("vad-on", "voice.vad_set", enabled=True))
        assert runtime.vad_enabled is True
        await service.handle_command(command("ptt-on", "voice.ptt_start", target="character"))
        await service.handle_command(command("ptt-off", "voice.ptt_stop"))
        await service.handle_command(command("tts-off", "voice.tts_stop"))
        assert runtime.listening is True
        assert runtime.ptt is False
        assert runtime.stopped is True
        assert runtime.contexts[-1][0] == service.current_conversation_id
        assert runtime.contexts[-1][1] == "phainon_ancient_machine"
        changed = [event for event in events if event["event"] == "voice.state_changed"]
        assert changed
        assert all(event["payload"]["voice"]["speech_queue_len"] == 0 for event in changed)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_invalid_pair_id_is_rejected_before_creating_records(tmp_path: Path) -> None:
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        existing_conversations = service.store.list_conversations(
            service.current_project_id,
            account_id=service.current_account_id,
        )
        with pytest.raises(ServiceError) as conversation_error:
            await service.handle_command(
                command(
                    "invalid-conversation",
                    "conversation.create",
                    project_id=service.current_project_id,
                    pair_id="not-a-pair",
                )
            )
        assert conversation_error.value.code == "PAIR_NOT_FOUND"
        assert "not-a-pair" in str(conversation_error.value)
        assert service.store.list_conversations(
            service.current_project_id,
            account_id=service.current_account_id,
        ) == existing_conversations

        invalid_project = tmp_path / "should-not-be-created"
        with pytest.raises(ServiceError) as project_error:
            await service.handle_command(
                command(
                    "invalid-project",
                    "project.create",
                    root_path=str(invalid_project),
                    pair_id="not-a-pair",
                )
            )
        assert project_error.value.code == "PAIR_NOT_FOUND"
        assert "not-a-pair" in str(project_error.value)
        assert service.store.find_project_by_root_path(str(invalid_project.resolve())) is None
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_ptt_stop_failure_clears_listening_state_and_surfaces_error(tmp_path: Path) -> None:
    events: list[dict] = []

    class FailingVoiceRuntime:
        on_message = lambda self, _message: None
        speech_queue_len = 0

        async def push_to_talk_stop(self) -> None:
            raise ValueError("角色模型未返回可用 speech")

        async def shutdown(self) -> None:
            pass

    service = build_demo_service(
        database=tmp_path / "data" / "ptt-failure.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    runtime = FailingVoiceRuntime()
    service.attach_voice_runtime(runtime)  # type: ignore[arg-type]
    service._voice_state["ptt"] = True
    try:
        with pytest.raises(ValueError, match="角色模型未返回可用 speech"):
            await service.handle_command(command("ptt-stop-fail", "voice.ptt_stop"))
        assert service.bootstrap()["voice"]["ptt"] is False
        assert service.bootstrap()["voice"]["error"] == "语音提交失败：角色模型未返回可用 speech"
        assert any(
            event["event"] == "voice.state_changed"
            and event["payload"]["voice"]["ptt"] is False
            for event in events
        )
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_tts_play_skip_and_preview_commands(tmp_path: Path) -> None:
    """V0.2 M2-4：voice.tts_play 按 message_id 重播、tts_skip 跳过、preview 试听入队。"""
    events: list[dict] = []

    class FakeVoiceRuntime:
        on_message = lambda self, _message: None

        def __init__(self) -> None:
            self.replayed: list[Any] = []
            self.skips = 0
            self.preview_texts: list[str] = []
            self.preview_voice_ids: list[str | None] = []
            self.contexts: list[tuple[str, str, str]] = []
            # V0.2 M4：待播队列长度（VoiceMiniPlayer 的 queuedCount）
            self.speech_queue_len = 0

        async def set_context_async(self, conversation_id, pair_config) -> None:
            self.contexts.append(
                (
                    conversation_id,
                    pair_config.pair_id,
                    pair_config.character.voice_id,
                )
            )

        def replay_message(self, message: Any) -> None:
            self.replayed.append(message)

        def skip_playing(self) -> None:
            self.skips += 1

        async def skip_playing_async(self) -> None:
            self.skip_playing()

        def enqueue_text(self, text: str, *, voice_id: str | None = None) -> None:
            self.preview_texts.append(text)
            self.preview_voice_ids.append(voice_id)
            self.speech_queue_len += 1

        async def shutdown(self) -> None:
            pass

    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    runtime = FakeVoiceRuntime()
    service.attach_voice_runtime(runtime)  # type: ignore[arg-type]
    service.store.set_secret(service.current_account_id, "voice.api_key", "test-key")
    service.store.set_config(
        service.current_account_id,
        "voice.profile.phainon.voice_id",
        "voice-phainon",
    )
    service._account_config = None
    try:
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="你好，白厄。",
            )
        )
        message_id = result["message_id"]

        # tts_play：从会话消息取文本重播（返回真实 message_id 的用户消息）
        await service.handle_command(
            command("play-1", "voice.tts_play", message_id=message_id)
        )
        assert [m.message_id for m in runtime.replayed] == [message_id]
        assert runtime.contexts[-1] == (
            conversation_id,
            "phainon_ancient_machine",
            "voice-phainon",
        )

        # tts_skip：调用 runtime.skip_playing
        await service.handle_command(command("skip-1", "voice.tts_skip"))
        assert runtime.skips == 1

        # preview：文本入队试听
        await service.handle_command(command("preview-1", "voice.preview", text="试听一下"))
        assert runtime.preview_texts == ["试听一下"]
        assert runtime.preview_voice_ids == ["voice-phainon"]

        # V0.2 M4：voice 快照的 speech_queue_len 反映待播队列长度
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["voice"]["speech_queue_len"] == 1

        # 错误路径：消息不存在 / 试听文本不可读
        with pytest.raises(ServiceError):
            await service.handle_command(
                command("play-2", "voice.tts_play", message_id="no-such-message")
            )
        with pytest.raises(ServiceError):
            await service.handle_command(command("preview-2", "voice.preview", text="……"))
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_chat_submit_registers_turn_with_lifecycle_events(tmp_path: Path) -> None:
    """V0.2 M2：一次提交 = 一个 Turn——提交返回 turn_id，后台推进
    turn.started(running) → turn.status_changed(completed)，快照可水合。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id

        async def wait_for(
            predicate, *, message: str, timeout: float = 5.0
        ) -> None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                if predicate():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError(message)

        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="今天状态怎么样？",
            )
        )
        assert result["turn_id"]

        def turn_events() -> list[dict]:
            return [
                e for e in events if e["event"] in ("turn.started", "turn.status_changed")
            ]

        await wait_for(
            lambda: len(turn_events()) >= 2,
            message="应发射 turn.started 与终态 turn.status_changed",
        )
        started = [e for e in turn_events() if e["event"] == "turn.started"]
        assert len(started) == 1
        assert started[0]["payload"]["turn"]["turn_id"] == result["turn_id"]
        assert started[0]["payload"]["turn"]["status"] == "running"
        assert started[0]["payload"]["turn"]["source_message_id"] == result["message_id"]
        assert started[0]["payload"]["turn"]["conversation_id"] == conversation_id
        assert started[0]["payload"]["turn"]["project_id"]  # 归属项目

        terminal = turn_events()[-1]
        assert terminal["payload"]["turn"]["status"] == "completed"

        # 快照水合：turns 按顺序包含该会话的 turn（终态 completed）
        snapshot = service.bootstrap()
        turns = [t for t in snapshot["turns"] if t["conversation_id"] == conversation_id]
        assert turns
        assert turns[-1]["turn_id"] == result["turn_id"]
        assert turns[-1]["status"] == "completed"
        assert turns[0]["turn_id"] == turns[-1]["turn_id"]  # 单次提交单条 turn
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_failed_turn_marks_turn_failed_and_message_failed(tmp_path: Path) -> None:
    """V0.2 M2：回合失败时 turn 进入 failed，用户消息标记 failed（文字保留）。

    用执行即抛异常的引擎真实触发失败路径：turn 终态 failed、
    用户消息标记 failed（文字保留）、系统状态消息可见、流式占位被收尾。
    """
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await service.handle_command(
            command(
                "settings-1",
                "project.update_settings",
                approval_mode=ApprovalMode.FULL_AUTO.value,
            )
        )

        class FailingEngine(ScriptedCodingEngine):
            """open_session 正常，run_turn 立即抛错——模拟引擎崩溃。"""

            async def run_turn(self, session_ref, request):
                raise RuntimeError("引擎爆炸")
                yield  # pragma: no cover - 保持 async generator 形态

        service.orchestrator.coding_engine = FailingEngine()
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="assistant",
                mode="collaboration",
                text="检查项目",
            )
        )
        user_message_id = result["message_id"]

        # 回合失败：turn 终态 failed
        await _wait_until(
            lambda: any(
                e["event"] == "turn.status_changed"
                and e["payload"]["turn"]["status"] == "failed"
                for e in events
            ),
            message="失败回合应落到 failed 终态",
        )
        # 用户消息标记 failed，文字保留可重试
        user_messages = [
            message
            for message in service.bootstrap()["messages"]
            if message["source"] == "user"
        ]
        assert len(user_messages) == 1
        assert user_messages[0]["message_id"] == user_message_id
        assert user_messages[0]["status"] == "failed"
        assert user_messages[0]["text"] == "检查项目"
        assert "引擎爆炸" in user_messages[0]["payload"]["error"]
        # 状态变更事件按 id 对账
        assert any(
            e["event"] == "message.status_changed"
            and e["payload"]["message"]["message_id"] == user_message_id
            for e in events
        )
        # 失败可见：系统状态消息（可恢复错误入通知队列）
        assert any(
            e["event"] == "message.created"
            and e["payload"]["message"]["source"] == "system"
            and "本次回复失败" in e["payload"]["message"]["text"]
            for e in events
        )
        # 三个点永不卡死：失败路径补发流式占位收尾
        assert any(e["event"] == "message.finalized" for e in events)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_busy_submit_enqueues_then_auto_dispatches_after_turn(tmp_path: Path) -> None:
    """V0.2 M2（问题 9）：忙碌时提交先入队返回 queue_item；回合完成后
    自动派发队列项（成为真实用户消息），队列消费后清空。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id

        async def wait_for(predicate, *, message: str, timeout: float = 5.0) -> None:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                if predicate():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError(message)

        # 制造忙碌：编排器有活动任务时提交会入队
        service.orchestrator.state.start(
            project_id="project-demo", conversation_id=conversation_id, task_id="task-busy"
        )
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="等你忙完再说这个。",
            )
        )
        assert result["queued"] is True
        assert result["queue_item"]["status"] == "queued"
        assert result["queue_item"]["conversation_id"] == conversation_id
        # 入队时不创建用户消息（派发时才落库）
        assert not any(
            e["event"] == "message.created" for e in events
        )
        queue_changed = [e for e in events if e["event"] == "queue.changed"]
        assert queue_changed, "入队应推送 queue.changed"
        assert len(queue_changed[-1]["payload"]["items"]) == 1

        # 清理忙碌：下一条提交的回合完成后应自动派发队列项
        service.orchestrator.state.finish("task-busy")
        events.clear()
        await service.handle_command(
            command(
                "chat-2",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="现在有空了吗？",
            )
        )

        # 注意：必须是同步谓词——wait_for 直接调用 predicate()，
        # 传 async 函数会得到从未 await 的 coroutine（恒真），主断言会失效。
        def queued_text_dispatched() -> bool:
            messages = [
                m for m in service.bootstrap()["messages"]
                if m["source"] == "user"
            ]
            return any("等你忙完再说这个" in m["text"] for m in messages)

        await wait_for(queued_text_dispatched, message="队列项应被自动派发为用户消息")
        # 队列消费后清空（processing → 完成删除）
        await wait_for(
            lambda: service.store.list_queue_items(conversation_id) == [],
            message="队列项派发完成后应从队列移除",
        )
        # 派发的队列项也走 Turn 生命周期
        turn_events = [
            e for e in events if e["event"] in ("turn.started", "turn.status_changed")
        ]
        assert len([e for e in turn_events if e["event"] == "turn.started"]) == 2
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_queue_edit_withdraw_and_prioritize(tmp_path: Path) -> None:
    """V0.2 M2：queue.edit 改文本、queue.withdraw 撤回、queue.prioritize 置队首。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        service.orchestrator.state.start(
            project_id="project-demo", conversation_id=conversation_id, task_id="task-busy"
        )
        first = await service.handle_command(
            command("chat-1", "chat.submit", conversation_id=conversation_id, text="第一条")
        )
        second = await service.handle_command(
            command("chat-2", "chat.submit", conversation_id=conversation_id, text="第二条")
        )
        first_item, second_item = first["queue_item"], second["queue_item"]
        assert first_item["position"] == 0
        assert second_item["position"] == 1

        # 编辑
        edited = await service.handle_command(
            command("edit-1", "queue.edit", queue_item_id=first_item["queue_item_id"], text="改过的第一条")
        )
        assert edited["queue_item"]["text"] == "改过的第一条"

        # 调序：第二条置队首
        await service.handle_command(
            command("pri-1", "queue.prioritize", queue_item_id=second_item["queue_item_id"])
        )
        items = service.store.list_queue_items(conversation_id)
        assert items[0]["queue_item_id"] == second_item["queue_item_id"]
        assert items[0]["position"] == 0
        assert items[1]["position"] == 1

        # 撤回第一条
        withdrawn = await service.handle_command(
            command("wd-1", "queue.withdraw", queue_item_id=first_item["queue_item_id"])
        )
        assert withdrawn["queue_item"]["status"] == "withdrawn"
        assert service.store.peek_queue_item(conversation_id)["queue_item_id"] == second_item["queue_item_id"]

        # 每个命令都推送 queue.changed 全量快照
        changed = [e for e in events if e["event"] == "queue.changed"]
        # 两次入队 + 编辑/调序/撤回 各一次 = 5 次全量推送
        assert len(changed) == 5
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_queue_persists_across_service_restart(tmp_path: Path) -> None:
    """V0.2 M2：conversation_inbox 持久化——重启后 bootstrap 快照仍含队列项。"""
    database = tmp_path / "data" / "pair_harness.db"
    service = build_demo_service(database=database, project_root=tmp_path)
    try:
        conversation_id = service.current_conversation_id
        service.orchestrator.state.start(
            project_id="project-demo", conversation_id=conversation_id, task_id="task-busy"
        )
        result = await service.handle_command(
            command("chat-1", "chat.submit", conversation_id=conversation_id, text="跨重启的队列项")
        )
        assert result["queued"] is True
    finally:
        await service.shutdown()

    restored = build_demo_service(database=database, project_root=tmp_path)
    try:
        snapshot = restored.bootstrap()
        items = [item for item in snapshot["queue_items"] if item["conversation_id"] == conversation_id]
        assert len(items) == 1
        assert items[0]["text"] == "跨重启的队列项"
        assert items[0]["status"] == "queued"
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_account_register_login_and_snapshot_fields(tmp_path: Path) -> None:
    """V0.2 M3：注册即登录；快照携带当前账号与账号列表。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_account_id"] == "default-local"
        assert snapshot["current_account"]["username"] == "default"

        result = await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="alice",
                display_name="爱丽丝",
                password="s3cret-pass",
            )
        )
        assert result["account"]["username"] == "alice"
        assert "password" not in result["account"]

        snapshot = await service.handle_command(command("b-2", "app.bootstrap"))
        assert snapshot["current_account_id"] == result["account"]["account_id"]
        assert snapshot["current_account"]["display_name"] == "爱丽丝"
        assert any(a["is_last_login"] for a in snapshot["accounts"])
        assert len(snapshot["accounts"]) == 2

        # 登录（密码错误拒绝）
        with pytest.raises(Exception):
            await service.handle_command(
                command(
                    "login-bad",
                    "account.login",
                    account_id=result["account"]["account_id"],
                    password="wrong-pass",
                )
            )
        logged = await service.handle_command(
            command(
                "login-1",
                "account.login",
                account_id=result["account"]["account_id"],
                password="s3cret-pass",
            )
        )
        assert logged["account"]["account_id"] == result["account"]["account_id"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_account_switch_isolates_projects(tmp_path: Path) -> None:
    """V0.2 M3：切换账号后项目/聊天按账号隔离。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        default_project_id = service.current_project_id
        # 注册新账号：默认账号项目不再可见
        result = await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="bob",
                display_name="鲍勃",
                password="bob-pass-1",
            )
        )
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_account_id"] == result["account"]["account_id"]
        assert snapshot["projects"] == []  # 新账号无项目
        # 切换账号后当前项目指针必须清空，不得残留上一账号的项目
        assert service.current_project_id == ""
        assert service.current_conversation_id == ""

        # 切回默认账号：项目恢复
        back = await service.handle_command(
            command("login-1", "account.login", account_id="default-local", password="")
        )
        assert back["account"]["username"] == "default"
        snapshot = await service.handle_command(command("b-2", "app.bootstrap"))
        assert any(p["project_id"] == default_project_id for p in snapshot["projects"])
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_account_onboarding_complete_marks_flag_only_on_command(
    tmp_path: Path,
) -> None:
    """V0.2 M4：注册/登录不自动完成引导；account.onboarding_complete 显式置位并广播。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        result = await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="alice",
                display_name="爱丽丝",
                password="s3cret-pass",
            )
        )
        # 注册后引导未完成（前端负责展示 Onboarding）
        assert result["account"]["onboarding_complete"] is False
        switched_snapshots = [event for event in events if event["event"] == "state.snapshot"]
        assert switched_snapshots
        assert all(
            event["payload"]["sequence"] == event["sequence"]
            for event in switched_snapshots
        )
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_account"]["onboarding_complete"] is False

        # 显式命令置位并广播 account.changed
        marked = await service.handle_command(
            command("ob-1", "account.onboarding_complete")
        )
        assert marked["account"]["onboarding_complete"] is True
        changed = [event for event in events if event["event"] == "account.changed"]
        assert changed
        assert changed[-1]["payload"]["account"]["onboarding_complete"] is True
        assert changed[-1]["sequence"] == switched_snapshots[-1]["sequence"] + 1
        snapshot = await service.handle_command(command("b-2", "app.bootstrap"))
        assert snapshot["current_account"]["onboarding_complete"] is True
        # 默认账号不受影响（登录页不展示引导）
        assert any(a["onboarding_complete"] is False for a in snapshot["accounts"])
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_config_get_set_masks_secrets(tmp_path: Path) -> None:
    """V0.3.2 M6：对话和语音 Key 都按账号保存且只回显掩码。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        updated = await service.handle_command(
            command(
                "set-1",
                "config.set",
                updates={
                    "engine": "deepseek",
                    "dialogue.base_url": "https://api.deepseek.com",
                    "dialogue.model": "deepseek-chat",
                    "dialogue.api_key": "sk-super-secret-123456",
                    "voice.api_key": "voice-super-secret-abcdef",
                    "voice.base_url": "https://dashscope.example/api/v1",
                    "voice.enabled": "false",
                    "assistant_voice_enabled": "true",
                    "vad_enabled": "true",
                },
            )
        )
        assert updated["config"]["engine"] == "deepseek"
        assert updated["config"]["dialogue"]["model"] == "deepseek-chat"
        config = await service.handle_command(command("get-1", "config.get"))
        assert config["engine"] == "deepseek"
        assert config["dialogue"]["model"] == "deepseek-chat"
        assert config["dialogue"]["api_key_masked"] == "sk-s…3456"
        assert "sk-super-secret" not in config["dialogue"]["api_key_masked"]
        assert config["voice"]["api_key_masked"].endswith("cdef")
        assert config["voice"]["credential_source"] == "account"
        assert "voice-super-secret" not in config["voice"]["api_key_masked"]
        assert config["voice"]["base_url"] == "https://dashscope.example/api/v1"
        assert config["voice"]["asr_model"] == "qwen-audio-3.0-asr-flash-streaming"
        assert config["voice"]["tts_model"] == "qwen-audio-3.0-tts-flash"
        assert config["voice"]["voices_source"] == "account"
        assert config["voice"]["character_voice"] == ""
        assert config["voice"]["assistant_voice"] == ""
        # 明文只存 secret_refs，config.get 不回传
        assert "sk-super-secret" not in str(config)
        assert "voice-super-secret" not in str(config)
        # 语音开关类偏好可读写；模型/音色由应用固定，不回显为可编辑配置
        assert config["voice"]["enabled"] == "false"
        assert config["voice"]["assistant_voice_enabled"] == "true"
        assert config["voice"]["vad_enabled"] == "true"
        assert config["voice"]["character_voice_name"] == "白厄"
        assert config["voice"]["assistant_voice_name"] == "神秘的古代机械"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_config_get_distinguishes_development_env_voice_key_from_account_byok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "env-only-voice-key")
    monkeypatch.setenv(
        "PAIR_HARNESS_DASHSCOPE_HTTP_URL",
        "https://dashscope.aliyuncs.com/api/v1",
    )
    service = build_demo_service(
        database=tmp_path / "data" / "env-voice.db",
        project_root=tmp_path,
    )
    try:
        config = await service.handle_command(command("get-env-voice", "config.get"))
        assert config["voice"]["credential_source"] == "development_env"
        assert config["voice"]["api_key_masked"] == ""
        assert config["voice"]["asr_available"] is True
        assert "env-only-voice-key" not in str(config)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_provision_completed_event_carries_voice_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pair_harness.adapters.audio.qwen_voice_customization import (
        QwenVoiceCustomizationClient,
    )

    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "voice-provision.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    service.store.set_secret(service.current_account_id, "voice.api_key", "account-key")
    service.store.set_config(
        service.current_account_id,
        "voice.base_url",
        "https://dashscope.aliyuncs.com/api/v1",
    )
    service._account_config = None

    def fake_clone(self, *, prefix: str, url: str) -> CustomizationResult:
        del self, url
        return CustomizationResult(
            voice_id=f"voice-{prefix}", payload={"output": {"voice_id": f"voice-{prefix}"}}
        )

    def fake_design(
        self, *, prefix: str, voice_prompt: str, preview_text: str
    ) -> CustomizationResult:
        del self, voice_prompt, preview_text
        return CustomizationResult(
            voice_id=f"voice-{prefix}", payload={"output": {"voice_id": f"voice-{prefix}"}}
        )

    monkeypatch.setattr(QwenVoiceCustomizationClient, "create_cloned_voice", fake_clone)
    monkeypatch.setattr(QwenVoiceCustomizationClient, "create_designed_voice", fake_design)
    try:
        result = await service.handle_command(
            command(
                "provision-one",
                "voice.provision",
                speaker_ids=["phainon"],
            )
        )
        assert result["results"][0]["voice_id"] == "voice-phainon"
        completed = [
            event
            for event in events
            if event["event"] == "voice.provision_changed"
            and event["payload"]["state"] == "completed"
        ]
        assert completed[-1]["payload"]["voice_id"] == "voice-phainon"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_preview_allows_character_but_rejects_assistant_speakers(
    tmp_path: Path,
) -> None:
    """V0.3.3：试听只放行角色侧声源；助手侧说话人声源一律拒绝 assistant_tts_disabled。"""

    class FakeVoiceRuntime:
        on_message = lambda self, _message: None
        speech_queue_len = 0

        def __init__(self) -> None:
            self.preview_voice_ids: list[str | None] = []

        def enqueue_text(self, text: str, *, voice_id: str | None = None) -> None:
            del text
            self.preview_voice_ids.append(voice_id)

        async def shutdown(self) -> None:
            pass

    service = build_demo_service(
        database=tmp_path / "data" / "voice-preview.db",
        project_root=tmp_path,
    )
    runtime = FakeVoiceRuntime()
    service.attach_voice_runtime(runtime)  # type: ignore[arg-type]
    all_voice_ids = {
        "phainon": "voice-phainon",
        "firefly": "voice-firefly",
        "sam": "voice-sam",
        "march7": "voice-march7",
        "fourth_mirror": "voice-fourth-mirror",
        "ancient_machine": "voice-ancient-machine",
    }
    service.store.set_secret(service.current_account_id, "voice.api_key", "test-key")
    for speaker_id, voice_id in all_voice_ids.items():
        service.store.set_config(
            service.current_account_id,
            f"voice.profile.{speaker_id}.voice_id",
            voice_id,
        )
    service._account_config = None

    character_voice_ids = ["voice-phainon", "voice-firefly", "voice-march7"]
    assistant_voice_ids = ["voice-sam", "voice-fourth-mirror", "voice-ancient-machine"]

    try:
        for voice_id in character_voice_ids:
            await service.handle_command(
                command(
                    f"preview-{voice_id}",
                    "voice.preview",
                    text="试听角色",
                    voice_id=voice_id,
                )
            )
        assert set(runtime.preview_voice_ids) == set(character_voice_ids)

        # V0.3.3：助手侧声源全部被拒
        for voice_id in assistant_voice_ids:
            with pytest.raises(ServiceError) as exc_info:
                await service.handle_command(
                    command(
                        f"preview-assistant-{voice_id}",
                        "voice.preview",
                        text="试听助手",
                        voice_id=voice_id,
                    )
                )
            assert exc_info.value.code == "assistant_tts_disabled"

        # 显式传入未知 ID 仍如实报错，不静默回退到角色音色
        with pytest.raises(ServiceError) as exc_info:
            await service.handle_command(
                command(
                    "preview-unknown",
                    "voice.preview",
                    text="试听陌生音色",
                    voice_id="voice-not-owned-by-current-account",
                )
            )
        assert exc_info.value.code == "voice_preview_not_allowed"

        assert set(runtime.preview_voice_ids) == set(character_voice_ids)
    finally:
        await service.shutdown()

@pytest.mark.asyncio
async def test_voice_tts_play_rejects_assistant_message(tmp_path: Path) -> None:
    """V0.3.3：手动重播助手消息在语音入口被拒，返回 assistant_tts_disabled。"""
    events: list[dict] = []

    class FakeVoiceRuntime:
        on_message = lambda self, _message: None
        speech_queue_len = 0

        def __init__(self) -> None:
            self.replayed: list[Any] = []

        def replay_message(self, message: Any) -> None:
            self.replayed.append(message)

        async def set_context_async(
            self, conversation_id: str, pair_config: Any
        ) -> None:
            del conversation_id, pair_config

        async def shutdown(self) -> None:
            pass

    service = build_demo_service(
        database=tmp_path / "data" / "voice-play-assistant.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    runtime = FakeVoiceRuntime()
    service.attach_voice_runtime(runtime)  # type: ignore[arg-type]
    service.store.set_secret(service.current_account_id, "voice.api_key", "test-key")
    service.store.set_config(
        service.current_account_id,
        "voice.profile.phainon.voice_id",
        "voice-phainon",
    )
    service._account_config = None
    try:
        conversation_id = service.current_conversation_id
        assistant = Message(
            conversation_id=conversation_id,
            pair_id="phainon_ancient_machine",
            source=MessageSource.ASSISTANT,
            kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
            text="好的，我马上检查项目目录。",
        )
        service.store.save_message(assistant)

        with pytest.raises(ServiceError) as exc_info:
            await service.handle_command(
                command(
                    "play-assistant",
                    "voice.tts_play",
                    message_id=assistant.message_id,
                )
            )
        assert exc_info.value.code == "assistant_tts_disabled"
        assert runtime.replayed == []
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_provision_rejects_assistant_speaker(tmp_path: Path) -> None:
    """V0.3.3：voice.provision 拒绝助手侧说话人，返回 assistant_voice_disabled。"""
    service = build_demo_service(
        database=tmp_path / "data" / "voice-provision-assistant.db",
        project_root=tmp_path,
    )
    service.store.set_secret(service.current_account_id, "voice.api_key", "account-key")
    service.store.set_config(
        service.current_account_id,
        "voice.base_url",
        "https://dashscope.aliyuncs.com/api/v1",
    )
    service._account_config = None
    try:
        with pytest.raises(ServiceError) as exc_info:
            await service.handle_command(
                command(
                    "provision-assistant",
                    "voice.provision",
                    speaker_ids=["sam"],
                )
            )
        assert exc_info.value.code == "assistant_voice_disabled"
    finally:
        await service.shutdown()
@pytest.mark.asyncio
async def test_config_get_returns_saved_dialogue_reasoning_effort(tmp_path: Path) -> None:
    """M5.2：config.get 必须回读保存的 dialogue.reasoning_effort，不能硬编码 auto。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        await service.handle_command(
            command(
                "set-1",
                "config.set",
                updates={"dialogue.reasoning_effort": "high"},
            )
        )
        config = await service.handle_command(command("get-1", "config.get"))
        assert config["dialogue"]["reasoning_effort"] == "high"
        assert service._load_account_config()["dialogue.reasoning_effort"] == "high"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_config_set_accepts_voice_credentials_but_locks_models(tmp_path: Path) -> None:
    """V0.3.2 M6：允许保存用户语音凭据，但模型和音色仍由应用固定。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        accepted = await service.handle_command(
            command(
                "set-voice",
                "config.set",
                updates={
                    "voice.api_key": "sk-user-voice",
                    "voice.base_url": "dashscope.example/api/v1",
                },
            )
        )
        assert accepted["config"]["voice"]["base_url"] == "https://dashscope.example/api/v1"
        assert accepted["config"]["voice"]["api_key_masked"].endswith("oice")

        for key in (
            "voice.asr_model",
            "voice.tts_model",
            "character_voice",
            "assistant_voice",
        ):
            with pytest.raises(ServiceError) as exc_info:
                await service.handle_command(
                    command("set-locked", "config.set", updates={key: "user-value"})
                )
            assert exc_info.value.code == "voice_config_locked"
        # 允许凭据和普通开关混合保存；锁定字段仍整体拒绝。
        mixed = await service.handle_command(
            command(
                "set-mixed",
                "config.set",
                updates={
                    "voice.api_key": "sk-new-voice",
                    "vad_enabled": "true",
                },
            )
        )
        assert mixed["config"]["voice"]["vad_enabled"] == "true"
        config = await service.handle_command(command("get-1", "config.get"))
        assert config["voice"]["vad_enabled"] == "true"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_snapshot_keeps_old_id_visible_when_regeneration_fails(
    tmp_path: Path,
) -> None:
    """M6：重新生成失败时保留旧音色 ID，但状态仍可显示失败并重试。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        service.store.set_config(
            service.current_account_id,
            "voice.profile.phainon.voice_id",
            "account-phainon-old",
        )
        service._voice_provision_states[service.current_account_id] = {
            "phainon": {"state": "failed", "error": "HTTP 500"}
        }
        config = await service.handle_command(command("voice-config", "config.get"))
        phainon = next(
            item for item in config["voice"]["speakers"] if item["speaker_id"] == "phainon"
        )
        assert phainon["voice_id"] == "account-phainon-old"
        assert phainon["state"] == "failed"
        assert phainon["error"] == "HTTP 500"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_config_test_connection_without_credentials_reports_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # live 测试基建会 load_dotenv(.env)；本测试要求“环境无凭据”前提，
    # 显式清空（与账号配置无关，纯环境兜底路径）。
    for name in (
        "PAIR_HARNESS_DIALOGUE_BASE_URL",
        "PAIR_HARNESS_DIALOGUE_API_KEY",
        "PAIR_HARNESS_DIALOGUE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        result = await service.handle_command(command("t-1", "config.test_connection"))
        assert result["ok"] is False
        assert "缺少对话服务配置" in result["message"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_codex_login_state_machine(tmp_path: Path) -> None:
    """V0.2 M3：codex.oauth_* 与 api_login 按当前账号隔离。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        status = await service.handle_command(command("s-1", "codex.oauth_status"))
        assert status["status"] in {"logged_out", "waiting", "logged_in"}

        await service.handle_command(command("s-2", "codex.oauth_start"))
        status = await service.handle_command(command("s-3", "codex.oauth_status"))
        assert status["status"] == "waiting"

        logged = await service.handle_command(
            command("s-4", "codex.api_login", api_key="sk-codex-123")
        )
        assert logged["status"] == "logged_in"
        status = await service.handle_command(command("s-5", "codex.oauth_status"))
        assert status["status"] == "logged_in"

        out = await service.handle_command(command("s-6", "codex.logout"))
        assert out["status"] == "logged_out"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_oauth_switch_from_deepseek_persists_before_starting_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DeepSeek → OAuth 必须先切统一供应商，再启动浏览器登录。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        await service.handle_command(
            command(
                "deepseek-config",
                "config.set",
                updates={
                    "engine": "deepseek",
                    "dialogue.provider": "deepseek",
                    "dialogue.base_url": "https://api.deepseek.com",
                    "dialogue.model": "deepseek-v4-flash",
                    "dialogue.api_key": "sk-deepseek-test",
                },
            )
        )
        seen_config: list[dict[str, str]] = []

        def fake_start_login() -> dict[str, object]:
            seen_config.append(service._load_account_config())
            return {"status": "waiting", "note": "test login"}

        monkeypatch.setattr(service.codex_auth, "start_login", fake_start_login)
        result = await service.handle_command(command("oauth-start", "codex.oauth_start"))

        assert seen_config == [
            {
                "engine": "codex",
                "dialogue.provider": "openai_oauth",
                "dialogue.base_url": "https://api.openai.com/v1",
                "dialogue.model": "gpt-5.6-sol",
                # 切换供应商时显式清空上一家已保存的 Key，防止环境变量补回。
                "dialogue.api_key": "",
            }
        ]
        assert service.store.get_secret(service.current_account_id, "dialogue.api_key") == ""
        assert result["config"]["engine"] == "codex"
        assert result["config"]["dialogue"]["provider"] == "openai_oauth"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_queue_item_failure_returns_to_queued_for_retry(tmp_path: Path) -> None:
    """F2/非功能-可靠：队列项回合失败退回 queued（可重试），不删除不吞掉。

    ``_dispatch_from_inbox`` 的失败分支（application_service 776-779）——
    队列项执行失败后不得被删除，也不得继续派发后续项。
    """
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await service.handle_command(
            command(
                "settings-1",
                "project.update_settings",
                approval_mode=ApprovalMode.FULL_AUTO.value,
            )
        )

        class FailOnSecondTurnEngine(ScriptedCodingEngine):
            """第一次回合正常，第二次回合（队列项）抛错。"""

            def __init__(self) -> None:
                super().__init__()
                self.turns_run = 0

            async def run_turn(self, session_ref, request):
                self.turns_run += 1
                if self.turns_run >= 2:
                    raise RuntimeError("队列项执行失败")
                    yield  # pragma: no cover - 保持 async generator 形态
                async for event in super().run_turn(session_ref, request):
                    yield event

        service.orchestrator.coding_engine = FailOnSecondTurnEngine()
        conversation_id = service.current_conversation_id

        # 忙碌时提交入队
        service.orchestrator.state.start(
            project_id="project-demo", conversation_id=conversation_id, task_id="task-busy"
        )
        queued = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="assistant",
                mode="collaboration",
                text="排队任务",
            )
        )
        assert queued["queued"] is True
        item_id = queued["queue_item"]["queue_item_id"]

        # 清理忙碌：下一条提交触发回合，完成后自动派发队列项
        service.orchestrator.state.finish("task-busy")
        await service.handle_command(
            command(
                "chat-2",
                "chat.submit",
                conversation_id=conversation_id,
                target="assistant",
                mode="collaboration",
                text="现在有空了",
            )
        )
        # 队列项的回合失败：退回 queued（可重试），不是删除
        await _wait_until(
            lambda: any(
                e["event"] == "turn.status_changed"
                and e["payload"]["turn"]["status"] == "failed"
                for e in events
            )
            and service.store.list_queue_items(conversation_id)[0]["status"] == "queued",
            message="队列项失败后应退回 queued 而非删除",
        )
        items = service.store.list_queue_items(conversation_id)
        assert len(items) == 1
        assert items[0]["queue_item_id"] == item_id
        assert items[0]["text"] == "排队任务"
        assert items[0]["status"] == "queued"
        # 失败的队列项也留下可见失败回合（不留悬空状态）
        failed_turns = [
            e["payload"]["turn"]
            for e in events
            if e["event"] == "turn.status_changed"
            and e["payload"]["turn"]["status"] == "failed"
        ]
        assert failed_turns
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_api_key_never_appears_in_logs(tmp_path: Path, caplog) -> None:
    """非功能-安全：API Key 不进日志——即使失败路径打出异常堆栈。"""
    secret = "sk-leak-check-123456789"
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await service.handle_command(
            command("set-1", "config.set", updates={"dialogue.api_key": secret})
        )
        await service.handle_command(
            command(
                "settings-1",
                "project.update_settings",
                approval_mode=ApprovalMode.FULL_AUTO.value,
            )
        )

        class FailingEngine(ScriptedCodingEngine):
            async def run_turn(self, session_ref, request):
                raise RuntimeError("引擎爆炸")
                yield  # pragma: no cover - 保持 async generator 形态

        service.orchestrator.coding_engine = FailingEngine()
        conversation_id = service.current_conversation_id

        with caplog.at_level(logging.WARNING, logger="pair_harness"):
            await service.handle_command(
                command(
                    "chat-1",
                    "chat.submit",
                    conversation_id=conversation_id,
                    target="assistant",
                    mode="collaboration",
                    text="检查项目",
                )
            )
            # 失败回合必然写日志（logger.exception）；再走账号切换的配置加载路径
            await _wait_until(
                lambda: any(
                    e["event"] == "turn.status_changed"
                    and e["payload"]["turn"]["status"] == "failed"
                    for e in events
                ),
                message="失败回合应产生日志",
            )
            await service.handle_command(
                command(
                    "reg-1",
                    "account.register",
                    username="carol",
                    display_name="卡罗",
                    password="carol-pass-1",
                )
            )
            await service.handle_command(command("b-1", "app.bootstrap"))

        assert caplog.records, "失败路径应产生日志记录"
        for record in caplog.records:
            rendered = record.getMessage()
            if record.exc_info:
                rendered += "".join(traceback.format_exception(*record.exc_info))
            assert secret not in rendered
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_runtime_receives_created_messages_via_listener_wiring(tmp_path: Path) -> None:
    """F7：attach_voice_runtime 后，落库消息经 add_message_listener 流入运行时。

    修复前 on_message 用空 lambda 替身，接线断掉测试仍绿；这里用记录型
    替身验证"消息持久化 → 运行时朗读入口"的真实链路。
    """

    class RecordingVoiceRuntime:
        speech_queue_len = 0

        def __init__(self) -> None:
            self.received: list[Any] = []

        def on_message(self, message) -> None:
            self.received.append(message)

        async def shutdown(self) -> None:
            pass

    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    runtime = RecordingVoiceRuntime()
    service.attach_voice_runtime(runtime)  # type: ignore[arg-type]
    try:
        conversation_id = service.current_conversation_id
        await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="你好，白厄。",
            )
        )
        # 用户消息立即落库 → 监听器同步收到
        await _wait_until(
            lambda: any(
                m.source == "user" and "你好，白厄" in m.text for m in runtime.received
            ),
            message="用户消息应进入语音朗读入口",
        )
        # 后台回合的角色回复也进入朗读入口
        await _wait_until(
            lambda: any(m.source == "character" for m in runtime.received),
            message="角色回复应进入语音朗读入口",
        )
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_rebuild_runtime_for_account_switches_engine_immediately(tmp_path: Path) -> None:
    """F3：切换引擎后下一个任务立即生效——重建路径真实替换引擎引用。

    demo 模式下 ``_rebuild_runtime_for_account`` 首行跳过（生产行为），
    这里按真实模式驱动重建：codex → CodexAppServerEngine，
    deepseek → AcpCodingEngine，且编排器与审查器依赖同步替换。
    """
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        assert isinstance(service.coding_engine, ScriptedCodingEngine)
        # 真实模式分支（demo 跳过是生产代码第一行 if self._demo: return）
        service._demo = False
        base_config = {
            "dialogue.provider": "openai_compatible",
            "dialogue.base_url": "https://api.example.com/v1",
            "dialogue.api_key": "sk-test",
            "dialogue.model": "gpt-5.6-sol",
        }

        await service._rebuild_runtime_for_account({**base_config, "engine": "codex"})
        assert isinstance(service.coding_engine, CodexAppServerEngine)
        assert isinstance(service.orchestrator.coding_engine, CodexAppServerEngine)
        assert isinstance(service.dialogue_model, OpenAICompatibleDialogueModel)
        assert isinstance(service.orchestrator.dialogue_model, OpenAICompatibleDialogueModel)

        deepseek_config = {
            "engine": "deepseek",
            "dialogue.provider": "deepseek",
            "dialogue.base_url": "https://api.deepseek.com",
            "dialogue.api_key": "sk-deepseek-test",
            "dialogue.model": "deepseek-v4-flash",
            "dialogue.reasoning_effort": "max",
        }
        await service._rebuild_runtime_for_account(deepseek_config)
        assert isinstance(service.coding_engine, AcpCodingEngine)
        assert isinstance(service.orchestrator.coding_engine, AcpCodingEngine)
        assert service.coding_engine.model == "deepseek-v4-flash"
        assert service.dialogue_model.model == "deepseek-v4-flash"
        assert service.dialogue_model.reasoning_effort == "max"
        # 审查智能体跟随新对话模型重建
        assert service.orchestrator.reviewer is not None
        assert service.orchestrator.reviewer._model is service.dialogue_model
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_conversation_and_engine_data_isolated_per_account(tmp_path: Path) -> None:
    """F6：切换账号后聊天/消息不可见，跨账号按 id 选择被拒。

    账号是完整隔离边界：即使前端持有其他账号的 conversation_id，
    选择上下文也必须被拒绝；切回后数据完整恢复。
    """
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        # 默认账号：产生一条消息与引擎数据（工具记录随回合落库）
        default_conv = service.current_conversation_id
        await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=default_conv,
                target="assistant",
                mode="collaboration",
                text="检查项目",
            )
        )
        snapshot = await service.handle_command(command("b-0", "app.bootstrap"))
        assert any(
            conv["conversation_id"] == default_conv
            for project in snapshot["projects"]
            for conv in project["conversations"]
        )

        # 注册新账号：项目/聊天全部不可见
        await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="dave",
                display_name="戴夫",
                password="dave-pass-1",
            )
        )
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["projects"] == []
        assert snapshot["messages"] == []

        # 跨账号按 id 选择被拒（隔离守卫，而不是静默串号）
        with pytest.raises(ServiceError) as exc_info:
            await service.handle_command(
                command("sel-1", "conversation.select", conversation_id=default_conv)
            )
        assert exc_info.value.code == "conversation_account_mismatch"

        # 切回默认账号：聊天与消息完整恢复
        await service.handle_command(
            command("login-1", "account.login", account_id="default-local", password="")
        )
        snapshot = await service.handle_command(command("b-2", "app.bootstrap"))
        assert snapshot["current_conversation_id"] == default_conv
        assert any(
            conv["conversation_id"] == default_conv
            for project in snapshot["projects"]
            for conv in project["conversations"]
        )
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_role_turn_same_conversation_is_queued_while_streaming(tmp_path: Path) -> None:
    """角色流不走 coding busy，也必须阻止同一聊天并发生成两轮。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )

    class BlockingDialogueModel:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def generate_title(self, *, pair_id: str, context: tuple) -> str | None:
            del pair_id, context
            return None

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

    model = BlockingDialogueModel()
    service.dialogue_model = model
    service.orchestrator.dialogue_model = model
    try:
        conversation_id = service.current_conversation_id
        first = await service.handle_command(
            command(
                "first",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="第一条",
            )
        )
        await asyncio.wait_for(model.started.wait(), timeout=1.0)

        second = await service.handle_command(
            command(
                "second",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="第二条",
            )
        )
        assert second["queued"] is True
        assert second["queue_item"]["status"] == "queued"
        assert model.calls == 1
        assert first["message_id"] != second["queue_item"]["queue_item_id"]

        model.release.set()
        deadline = asyncio.get_running_loop().time() + 2.0
        while asyncio.get_running_loop().time() < deadline:
            if not service.store.list_queue_items(conversation_id) and model.calls == 2:
                break
            await asyncio.sleep(0.01)
        assert not service.store.list_queue_items(conversation_id)
        assert model.calls == 2
    finally:
        model.release.set()
        await service.shutdown()


@pytest.mark.asyncio
async def test_service_restart_restores_projects_for_current_account_only(tmp_path: Path) -> None:
    """F6：重启读取 app_state 后，项目恢复仍绑定当前账号。"""
    database = tmp_path / "data" / "pair_harness.db"
    service = build_demo_service(database=database, project_root=tmp_path)
    await service.handle_command(
        command(
            "reg-1",
            "account.register",
            username="restart-user",
            display_name="重启用户",
            password="restart-pass-1",
        )
    )
    assert service.current_project_id == ""
    await service.shutdown()

    restored = build_demo_service(database=database, project_root=tmp_path)
    try:
        assert restored.current_account_id != "default-local"
        assert restored.current_project_id == ""
        assert restored.current_conversation_id == ""
        assert restored.bootstrap()["projects"] == []
    finally:
        await restored.shutdown()


@pytest.mark.asyncio
async def test_project_commands_reject_foreign_account_ids(tmp_path: Path) -> None:
    """F6：项目入口统一拦截其他账号的项目 ID。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db", project_root=tmp_path
    )
    try:
        foreign_project_id = service.current_project_id
        await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="project-user",
                display_name="项目用户",
                password="project-pass-1",
            )
        )
        for request_id, method, params in (
            ("select", "project.select", {"project_id": foreign_project_id}),
            ("update", "project.update_settings", {"project_id": foreign_project_id, "name": "越权"}),
            ("archive", "project.archive", {"project_id": foreign_project_id}),
            ("conversation", "conversation.create", {"project_id": foreign_project_id}),
        ):
            with pytest.raises(ServiceError) as exc_info:
                await service.handle_command(command(request_id, method, **params))
            assert exc_info.value.code == "project_account_mismatch"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_new_conversation_belongs_to_current_account(tmp_path: Path) -> None:
    """F6：新会话创建归属当前账号——切回默认账号后不可见。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        await service.handle_command(
            command(
                "reg-1",
                "account.register",
                username="erin",
                display_name="艾琳",
                password="erin-pass-1",
            )
        )
        # 新账号创建项目与聊天
        created = await service.handle_command(
            command(
                "p-1",
                "project.create",
                root_path=str(tmp_path / "erin-project"),
                name="艾琳的项目",
            )
        )
        erin_project = created["current_project_id"]
        conversation = await service.handle_command(
            command(
                "c-1",
                "conversation.create",
                project_id=erin_project,
                title="艾琳的聊天",
            )
        )
        erin_conv = conversation["current_conversation_id"]

        # 切回默认账号：艾琳的聊天不可见
        await service.handle_command(
            command("login-1", "account.login", account_id="default-local", password="")
        )
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert not any(
            conv["conversation_id"] == erin_conv
            for project in snapshot["projects"]
            for conv in project["conversations"]
        )
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_account_switch_failure_keeps_original_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3.1：目标账号候选运行时构建失败时，当前账号/上下文保持不变。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        original_account_id = service.current_account_id
        original_project_id = service.current_project_id
        original_conversation_id = service.current_conversation_id
        service._demo = False

        def broken_candidate(*args, **kwargs):
            raise ServiceError("目标账号配置损坏", code="config_corrupt")

        monkeypatch.setattr(service, "_build_runtime_candidate", broken_candidate)
        with pytest.raises(ServiceError, match="配置损坏"):
            await service.handle_command(
                command(
                    "reg-bad",
                    "account.register",
                    username="broken-user",
                    display_name="损坏账号",
                    password="broken-pass-1",
                )
            )

        assert service.current_account_id == original_account_id
        assert service.store.get_app_state("current_account_id") in (
            None,
            original_account_id,
        )
        assert service.current_project_id == original_project_id
        assert service.current_conversation_id == original_conversation_id
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_config_set_failure_keeps_database_old_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3.3：候选运行时构建失败时配置不落库，旧配置继续可用。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        service._demo = False

        def broken_candidate(*args, **kwargs):
            raise ServiceError("候选运行时不可用", code="runtime_build_failed")

        monkeypatch.setattr(service, "_build_runtime_candidate", broken_candidate)
        with pytest.raises(ServiceError, match="候选运行时不可用"):
            await service.handle_command(
                command(
                    "set-bad",
                    "config.set",
                    updates={
                        "engine": "deepseek",
                        "dialogue.provider": "deepseek",
                        "dialogue.base_url": "https://api.deepseek.com",
                        "dialogue.model": "deepseek-v4-flash",
                        "dialogue.api_key": "sk-new",
                    },
                )
            )

        assert service.store.get_config(service.current_account_id, "engine") is None
        assert service.store.get_secret(service.current_account_id, "dialogue.api_key") is None
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_explicit_cleared_api_key_blocks_environment_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3.3：显式清空已保存 API Key 后，环境变量不能把旧值悄悄补回。"""
    monkeypatch.setenv("PAIR_HARNESS_DIALOGUE_API_KEY", "sk-env-default")
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        # 从未保存时环境变量可作为默认来源。
        never_saved = service._load_account_config()
        assert "dialogue.api_key" not in never_saved
        _, _, env_key, _ = service._dialogue_runtime_settings(never_saved)
        assert env_key == "sk-env-default"

        # 用户显式清空保存的 Key。
        await service.handle_command(
            command("clear-key", "config.set", updates={"dialogue.api_key": ""})
        )
        saved = service._load_account_config()
        assert saved["dialogue.api_key"] == ""
        _, _, runtime_key, _ = service._dialogue_runtime_settings(saved)
        assert runtime_key == ""
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_runtime_rebuild_invalidates_engine_session_refs(tmp_path: Path) -> None:
    """M3.2：供应商/引擎切换后旧 EngineSessionRef 失效，下一次任务新开 session。"""
    from pair_harness.core.contracts import EngineSessionRef

    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        conversation_id = service.current_conversation_id
        service.store.save_engine_session(
            conversation_id,
            EngineSessionRef(engine_type="scripted", opaque_ref="old-session"),
        )
        service._demo = False
        deepseek_config = {
            "engine": "deepseek",
            "dialogue.provider": "deepseek",
            "dialogue.base_url": "https://api.deepseek.com",
            "dialogue.api_key": "sk-deepseek-test",
            "dialogue.model": "deepseek-v4-flash",
        }
        await service._rebuild_runtime_for_account(deepseek_config)

        assert service.store.load_conversation(conversation_id)["engine_session"] is None
        assert conversation_id not in service.orchestrator._sessions
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_app_reconnect_command_reports_clear_error_not_silent(tmp_path: Path) -> None:
    """F8：app.reconnect 命令返回明确错误——重连由桌面进程负责。

    进程管理（退避重启 1s→2s→…→15s）在 Tauri 侧 sidecar_reconnect 实现；
    Sidecar 进程自身不重建。此命令必须明确报错而非静默成功，
    前端不会误以为 Sidecar 侧已重连。
    """
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        with pytest.raises(ServiceError) as exc_info:
            await service.handle_command(command("r-1", "app.reconnect"))
        assert exc_info.value.code == "not_implemented"
        assert "桌面进程" in str(exc_info.value)
    finally:
        await service.shutdown()
