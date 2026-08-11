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
    """Map native app-server notifications to stable Pair Harness events.

    O4.1：适配器不再自定事件序号——``_event`` 固定 ``sequence=0``，
    最终序号由 orchestrator 在出口处统一重排（含合成事件），
    避免“codec 自编号 + 编排器合成事件本地编号”双源头碰撞。
    """

    def _event(
        self,
        binding: EventBinding,
        event_type: EngineEventType,
        *,
        tool_call_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EngineEvent:
        return EngineEvent(
            conversation_id=binding.conversation_id,
            task_id=binding.task_id,
            engine_turn_id=binding.engine_turn_id,
            sequence=0,
            type=event_type,
            tool_call_id=tool_call_id,
            payload=payload or {},
        )

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
        if method in {
            "item/reasoning/summaryTextDelta",
            "item/reasoning/textDelta",
        }:
            return self._event(
                binding,
                EngineEventType.ASSISTANT_REASONING_DELTA,
                tool_call_id=item_id,
                payload={
                    "text": params.get("delta", ""),
                    "channel": (
                        "summary"
                        if method == "item/reasoning/summaryTextDelta"
                        else "content"
                    ),
                },
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
        if method in (
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
        ):
            # O3.1：app-server 在工具操作执行前挂起并发起审批请求
            # （服务端发起的 JSON-RPC 请求，带 id）。orchestrator 裁决后
            # 经 respond() 回复；approval_id 取请求 id，保证 resolve_approval
            # 能路由回挂起中的请求。字段名依据 codex app-server
            # generate-json-schema（0.147.0）确认；B1 联调以实际通知为准。
            request_id = notification.get("id")
            tool_kind = {
                "item/commandExecution/requestApproval": "shell",
                "item/fileChange/requestApproval": "file_write",
                "item/permissions/requestApproval": "shell",
            }[method]
            command = params.get("command")
            paths = params.get("paths")
            if not paths and params.get("grantRoot"):
                paths = [params["grantRoot"]]
            return self._event(
                binding,
                EngineEventType.APPROVAL_REQUESTED,
                tool_call_id=item_id,
                payload={
                    "approval_id": (
                        str(request_id)
                        if request_id is not None
                        else params.get("approvalId")
                    ),
                    "request_id": request_id,
                    "reason": params.get("reason", ""),
                    "summary": params.get("reason") or command or "工具操作",
                    "tool_kind": tool_kind,
                    "command": command,
                    "paths": paths or [],
                },
            )
        if method == "item/approval/requested":
            # 旧协议兼容映射（O3.1 后不再作为交互卡片直透，
            # 统一由 orchestrator 裁决后经 resolve_approval 转发）。
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
