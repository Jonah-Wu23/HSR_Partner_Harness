from pair_harness.adapters.codex.codec import CodexCodec, EventBinding


def binding() -> EventBinding:
    return EventBinding(conversation_id="c", task_id="task", engine_turn_id="turn")


def test_maps_assistant_and_tool_notifications() -> None:
    codec = CodexCodec()
    started = codec.map_notification(
        {
            "method": "item/started",
            "params": {
                "turnId": "turn",
                "item": {"id": "tool-1", "type": "command_execution", "command": "pytest"},
            },
        },
        binding(),
    )
    finished = codec.map_notification(
        {
            "method": "item/completed",
            "params": {
                "turnId": "turn",
                "item": {
                    "id": "tool-1",
                    "type": "command_execution",
                    "command": "pytest",
                    "status": "completed",
                    "aggregatedOutput": "2 passed",
                },
            },
        },
        binding(),
    )
    assistant = codec.map_notification(
        {
            "method": "item/completed",
            "params": {
                "turnId": "turn",
                "item": {"id": "msg", "type": "agent_message", "text": "完成"},
            },
        },
        binding(),
    )

    assert started.type == "tool.started"
    assert started.tool_call_id == "tool-1"
    assert finished.type == "tool.finished"
    assert finished.payload["status"] == "succeeded"
    assert assistant.type == "assistant.final"
    assert [started.sequence, finished.sequence, assistant.sequence] == [0, 1, 2]


def test_maps_failed_turn_and_ignores_other_turn() -> None:
    codec = CodexCodec()
    assert (
        codec.map_notification(
            {"method": "turn/started", "params": {"turn": {"id": "other"}}}, binding()
        )
        is None
    )
    failed = codec.map_notification(
        {
            "method": "turn/completed",
            "params": {"turn": {"id": "turn", "status": "failed", "error": "boom"}},
        },
        binding(),
    )
    assert failed.type == "turn.failed"
    assert failed.payload["error"] == "boom"


def test_maps_native_approval_cards() -> None:
    event = CodexCodec().map_notification(
        {
            "method": "item/approval/requested",
            "params": {
                "turnId": "turn",
                "itemId": "tool-1",
                "approvalId": "approval-1",
                "reason": "needs confirmation",
            },
        },
        binding(),
    )
    assert event.type == "approval.requested"
    assert event.payload["approval_id"] == "approval-1"

