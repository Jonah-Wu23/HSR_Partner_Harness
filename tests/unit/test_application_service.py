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
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="今天有点累，陪我聊聊。",
            )
        )
        assert result["task_id"] is None
        assert [event["event"] for event in events] == [
            "message.created",
            "message.created",
        ]

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
        assert result["status"] == "completed"
        event_names = [event["event"] for event in events]
        assert "task.busy_changed" in event_names
        assert "message.delta" in event_names
        assert "tool_run.upserted" in event_names
        assert event_names[-1] == "task.busy_changed"
        assert events[-1]["payload"]["busy"] is False
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

        snapshot = await service.handle_command(
            command("rename-1", "project.update_settings", project_id=project_id, name="我的项目")
        )
        assert snapshot["current_project"]["name"] == "我的项目"

        snapshot = await service.handle_command(
            command(
                "repair-1",
                "project.update_settings",
                project_id=project_id,
                root_path=str(second_root),
            )
        )
        assert snapshot["current_project"]["root_path"] == str(second_root.resolve())
        assert snapshot["current_project"]["name"] == "我的项目"
    finally:
        await service.shutdown()


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
