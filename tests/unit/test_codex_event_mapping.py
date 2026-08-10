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
    # O4.1：适配器不再自定序号，全部固定为 0；最终序号由
    # orchestrator 出口统一重排（见 test_event_sequence.py）
    assert [started.sequence, finished.sequence, assistant.sequence] == [0, 0, 0]


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


def test_maps_server_initiated_request_approval_payload() -> None:
    """O3.1：app-server 服务端发起的 requestApproval（带 JSON-RPC id）。

    approval_id 取请求 id（orchestrator 据此经 respond 回复）；字段归一为
    tool_kind/command/paths/summary，供沙箱与审批管理器直接使用。
    """
    event = CodexCodec().map_notification(
        {
            "id": 100,
            "method": "item/commandExecution/requestApproval",
            "params": {
                "itemId": "tool-1",
                "command": "pytest tests/",
                "cwd": "C:\\project",
                "reason": "需要用户审批",
            },
        },
        binding(),
    )
    assert event.type == "approval.requested"
    assert event.tool_call_id == "tool-1"
    assert event.payload["approval_id"] == "100"
    assert event.payload["request_id"] == 100
    assert event.payload["tool_kind"] == "shell"
    assert event.payload["command"] == "pytest tests/"
    assert event.payload["paths"] == []
    assert event.payload["reason"] == "需要用户审批"


def test_maps_file_change_request_approval_grant_root_to_paths() -> None:
    """O3.1：fileChange 审批把 grantRoot 归一进 paths 供沙箱检查。"""
    event = CodexCodec().map_notification(
        {
            "id": 7,
            "method": "item/fileChange/requestApproval",
            "params": {
                "itemId": "tool-2",
                "grantRoot": "C:\\project\\src",
                "reason": "写文件",
            },
        },
        binding(),
    )
    assert event.type == "approval.requested"
    assert event.payload["approval_id"] == "7"
    assert event.payload["tool_kind"] == "file_write"
    assert event.payload["paths"] == ["C:\\project\\src"]

