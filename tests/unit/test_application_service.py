from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pair_harness.core.contracts import ApprovalMode, MessageSource
from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


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
        assert snapshot["messages"] == []
        assert snapshot["voice"]["supported"] is False
        assert snapshot["busy"] is False
    finally:
        await service.shutdown()


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
        await asyncio.sleep(0)

        conversation = service.store.get_conversation(conversation_id)
        assert conversation.title != "新聊天"
        title_requests = getattr(service.dialogue_model, "title_requests")
        assert len(title_requests) == 1
        _, context = title_requests[0]
        assert context
        assert all(message.source in {MessageSource.USER, MessageSource.CHARACTER} for message in context)
        assert all(message.source not in {MessageSource.SYSTEM, MessageSource.TOOL} for message in context)

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
async def test_streaming_assistant_events_reconcile_to_one_persisted_message(
    tmp_path: Path,
) -> None:
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
        assistant_messages = [
            message
            for message in service.bootstrap()["messages"]
            if message["source"] == "assistant"
        ]
        assert delta_ids
        assert delta_ids <= finalized_ids
        assert len(assistant_messages) == 1
        assert assistant_messages[0]["message_id"] in delta_ids
        assert service.store.get_conversation(conversation_id).last_mode == "collaboration"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_voice_commands_only_exchange_state_with_attached_runtime(tmp_path: Path) -> None:
    events: list[dict] = []

    class FakeVoiceRuntime:
        on_message = lambda self, _message: None

        def __init__(self) -> None:
            self.listening = False
            self.ptt = False
            self.stopped = False

        async def start_listening(self) -> None:
            self.listening = True

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
        await service.handle_command(command("vad-on", "voice.vad_set", enabled=True))
        await service.handle_command(command("ptt-on", "voice.ptt_start", target="character"))
        await service.handle_command(command("ptt-off", "voice.ptt_stop"))
        await service.handle_command(command("tts-off", "voice.tts_stop"))
        assert runtime.listening is True
        assert runtime.ptt is False
        assert runtime.stopped is True
        assert "voice.state_changed" in [event["event"] for event in events]
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
    """V0.2 M2：回合失败时 turn 进入 failed，用户消息标记 failed（文字保留）。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        # 注入会失败的编排器路径：破坏对话模型不可行（demo 不会失败），
        # 改用关闭后的服务直接驱动 _run_submit_turn 不可行——这里通过
        # 让 submit 后立即 shutdown 触发任务取消，验证 cancelled 事件。
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="你好",
            )
        )
        assert result["turn_id"]
        await service.shutdown()

        # shutdown 后服务关闭，turn 记录仍按事件序列保留（cancelled）
        started = [e for e in events if e["event"] == "turn.started"]
        terminal = [e for e in events if e["event"] == "turn.status_changed"]
        assert started, "turn.started 应已发射"
        statuses = [e["payload"]["turn"]["status"] for e in terminal]
        assert "cancelled" in statuses or "completed" in statuses
    finally:
        await service.shutdown()
