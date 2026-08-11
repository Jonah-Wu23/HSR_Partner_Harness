from __future__ import annotations

from pathlib import Path

import pytest

from pair_harness.core.contracts import ApprovalMode
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
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        project_root = tmp_path / "another-project"
        project_root.mkdir()
        snapshot = await service.handle_command(
            command("p-1", "project.create", root_path=str(project_root), name="另一个项目")
        )
        assert snapshot["current_project"]["name"] == "另一个项目"
        conversation_id = snapshot["current_conversation_id"]
        await service.handle_command(
            command("r-1", "conversation.rename", conversation_id=conversation_id, title="已改名")
        )
        snapshot = await service.handle_command(command("b-1", "app.bootstrap"))
        assert snapshot["current_conversation"]["title"] == "已改名"
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
