from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pair_harness.core.contracts import EngineEvent, EngineEventType


@dataclass(frozen=True)
class EventBinding:
    conversation_id: str
    task_id: str
    engine_turn_id: str


class CodexCodec:
    """Map native app-server notifications to stable Pair Harness events."""

    def __init__(self) -> None:
        self._sequence = 0

    def _event(
        self,
        binding: EventBinding,
        event_type: EngineEventType,
        *,
        tool_call_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EngineEvent:
        event = EngineEvent(
            conversation_id=binding.conversation_id,
            task_id=binding.task_id,
            engine_turn_id=binding.engine_turn_id,
            sequence=self._sequence,
            type=event_type,
            tool_call_id=tool_call_id,
            payload=payload or {},
        )
        self._sequence += 1
        return event

    def map_notification(
        self, notification: dict[str, Any], binding: EventBinding
    ) -> EngineEvent | None:
        method = notification.get("method")
        params = notification.get("params") or {}
        turn = params.get("turn") or {}
        native_turn_id = params.get("turnId") or turn.get("id")
        if native_turn_id and native_turn_id != binding.engine_turn_id:
            return None

        item = params.get("item") or {}
        item_id = str(item.get("id") or params.get("itemId") or "") or None
        item_type = item.get("type") or params.get("itemType")

        if method == "turn/started":
            return self._event(binding, EngineEventType.TURN_STARTED)
        if method == "item/agentMessage/delta":
            return self._event(
                binding,
                EngineEventType.ASSISTANT_DELTA,
                payload={"text": params.get("delta", "")},
            )
        if method == "item/commandExecution/outputDelta":
            return self._event(
                binding,
                EngineEventType.TOOL_PROGRESS,
                tool_call_id=item_id,
                payload={"summary": params.get("delta", "")},
            )
        if method == "item/started" and item_type in {"command_execution", "mcp_tool_call"}:
            return self._event(
                binding,
                EngineEventType.TOOL_STARTED,
                tool_call_id=item_id,
                payload={
                    "title": item.get("command") or item.get("tool") or "工具调用",
                    "details": item.get("command") or "",
                },
            )
        if method == "item/completed" and item_type == "agent_message":
            return self._event(
                binding,
                EngineEventType.ASSISTANT_FINAL,
                payload={"text": item.get("text", "")},
            )
        if method == "item/completed" and item_type in {"command_execution", "mcp_tool_call"}:
            # 原生状态 "completed" 映射为协议内的 "succeeded"，与 ToolRun.status 对齐
            status = "succeeded" if item.get("status") == "completed" else "failed"
            return self._event(
                binding,
                EngineEventType.TOOL_FINISHED,
                tool_call_id=item_id,
                payload={
                    "status": status,
                    "title": item.get("command") or item.get("tool") or "工具调用",
                    "summary": item.get("aggregatedOutput") or item.get("output") or "",
                    "details": item.get("aggregatedOutput") or item.get("output") or "",
                    "error": item.get("error"),
                },
            )
        if method == "item/completed" and item_type == "file_change":
            return self._event(
                binding,
                EngineEventType.FILE_PATCH,
                tool_call_id=item_id,
                payload={"path": item.get("path", ""), "patch": item.get("patch", "")},
            )
        if method == "item/approval/requested":
            return self._event(
                binding,
                EngineEventType.APPROVAL_REQUESTED,
                tool_call_id=item_id,
                payload={
                    "approval_id": params.get("approvalId"),
                    "reason": params.get("reason", ""),
                },
            )
        if method == "item/approval/resolved":
            return self._event(
                binding,
                EngineEventType.APPROVAL_RESOLVED,
                tool_call_id=item_id,
                payload={
                    "approval_id": params.get("approvalId"),
                    "decision": params.get("decision"),
                },
            )
        if method == "turn/completed":
            status = turn.get("status") or params.get("status") or "completed"
            if status == "completed":
                return self._event(binding, EngineEventType.TURN_COMPLETED)
            return self._event(
                binding,
                EngineEventType.TURN_FAILED,
                payload={"error": turn.get("error") or params.get("error") or status},
            )
        return None

