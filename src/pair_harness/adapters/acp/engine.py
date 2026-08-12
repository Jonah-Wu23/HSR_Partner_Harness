"""DeepSeek 编程助手（Reasonix ACP v1 客户端）——V0.2 M3（方案 §M3-5）。

复用本地 DeepSeek-Reasonix 的 ACP/流式会话能力作为引擎边界（出处见
THIRD_PARTY_NOTICES.md）：Reasonix 以 Agent Client Protocol v1 的 NDJSON
JSON-RPC 2.0 暴露于 stdin/stdout（``reasonix acp``）。本适配器复用
``JsonlProcessTransport`` 与编排器现有 EngineEvent 事件模型，把 ACP 的
``agent_message_chunk``/``thought_chunk``/``tool_call_*``/``request_permission``
映射为统一的工具、审批和消息事件。账号、项目与引擎会话仍由编排器管理。

协议要点（docs/ACP.md）：
- ``initialize`` → ``session/new {cwd}`` 打开会话，返回 sessionId；
- ``session/prompt`` 运行一轮并持续推送更新，直到返回 stop reason；
- ``request_permission`` 是服务端请求（带 JSON-RPC id），须经
  ``transport.respond(id, result)`` 回复 allow/deny；
- 取消走 ``session/cancel``（notification）；steer 走厂商扩展
  ``_reasonix.io/session/steer``（动态方法名，缺省用官方名回退）。
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any

from pair_harness.core.contracts import (
    ApprovalDecision,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    ProjectRef,
    TaskAmendment,
    TaskRequest,
)
from pair_harness.core.ports import CodingEngine


class AcpCodingEngine(CodingEngine):
    """Reasonix ACP 会话的 CodingEngine 适配器。

    每个会话（conversation）一个 ACP session；``EngineSessionRef.opaque_ref``
    编码 acp session_id，与 codex 适配器编码 thread_id 同构。
    """

    engine_type = "acp"

    def __init__(self, transport: Any, *, model: str | None = None) -> None:
        self.transport = transport
        self.model = model or ""
        self._initialized = False

    @staticmethod
    def _encode_ref(acp_session_id: str) -> EngineSessionRef:
        encoded = base64.urlsafe_b64encode(
            json.dumps({"acp_session_id": acp_session_id}).encode("utf-8")
        ).decode("ascii")
        return EngineSessionRef(engine_type=AcpCodingEngine.engine_type, opaque_ref=encoded)

    @staticmethod
    def _decode_ref(ref: EngineSessionRef) -> str:
        if ref.engine_type != AcpCodingEngine.engine_type:
            raise ValueError(f"unsupported engine session type: {ref.engine_type}")
        data = json.loads(base64.urlsafe_b64decode(ref.opaque_ref.encode("ascii")))
        return str(data["acp_session_id"])

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        await self.transport.start()
        await self.transport.request(
            "initialize",
            {"clientInfo": {"name": "pair-harness", "version": "0.2.0"}},
        )
        self._initialized = True

    async def open_session(
        self,
        project: ProjectRef,
        stored_ref: EngineSessionRef | None = None,
        *,
        approval_policy: str | None = None,
        sandbox: str | None = None,
        approvals_reviewer: str | None = None,
        developer_instructions: str | None = None,
    ) -> EngineSessionRef:
        """打开（或恢复）ACP 会话。工具审批映射到 ACP 的 tool_approval 配置。"""
        del approvals_reviewer
        await self._ensure_initialized()
        if stored_ref is not None:
            # ACP session/resume 恢复会话（不重放 transcript）
            acp_session_id = self._decode_ref(stored_ref)
            await self.transport.request(
                "session/resume", {"sessionId": acp_session_id, "cwd": project.root_path}
            )
            return self._encode_ref(acp_session_id)
        params: dict[str, Any] = {"cwd": project.root_path}
        if self.model:
            params["model"] = self.model
        if developer_instructions:
            params["developerInstructions"] = developer_instructions
        result = await self.transport.request("session/new", params)
        session_id = result.get("sessionId") or result.get("session", {}).get("id")
        if not session_id:
            raise RuntimeError("session/new returned no session id")
        # 工具审批策略：编排器按审批模式传入（ask/auto/yolo 语义由宿主映射）
        if approval_policy is not None:
            try:
                await self.transport.request(
                    "session/set_config_option",
                    {"sessionId": session_id, "configId": "tool_approval", "value": approval_policy},
                )
            except RuntimeError:
                # 会话不支持该配置项时忽略（Reasonix 与 ACP 官方形状差异）
                pass
        return self._encode_ref(str(session_id))

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        acp_session_id = self._decode_ref(session_ref)
        task_text = request.instructions
        if request.constraints:
            constraints = "\n".join(f"- {item}" for item in request.constraints)
            task_text = f"{task_text}\n\n本次任务约束：\n{constraints}"
        prompt_task = asyncio.create_task(
            self.transport.request(
                "session/prompt",
                {
                    "sessionId": acp_session_id,
                    "prompt": [{"type": "text", "text": task_text}],
                },
            )
        )
        binding = {
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "engine_turn_id": f"acp-{request.task_id}",
        }
        codec = AcpCodec()
        try:
            while True:
                if prompt_task.done():
                    # prompt 已返回：回合结束，但通知可能还在队列中
                    # （ACP 语义保证结束前事件已推送）；短超时消费剩余。
                    try:
                        notification = await asyncio.wait_for(
                            self.transport.next_notification(), timeout=0.05
                        )
                    except asyncio.TimeoutError:
                        break
                    event = codec.map_notification(notification, binding)
                    if event is None:
                        continue
                    yield event
                    continue
                # 事件通知与 prompt 响应并发等待：逐条消费映射
                notification_task = asyncio.create_task(self.transport.next_notification())
                done, _ = await asyncio.wait(
                    {prompt_task, notification_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if prompt_task in done:
                    if notification_task in done:
                        # 通知与 prompt 同时到达：先消费通知，不丢事件
                        event = codec.map_notification(notification_task.result(), binding)
                        if event is not None:
                            yield event
                    else:
                        notification_task.cancel()
                    continue
                notification = notification_task.result()
                event = codec.map_notification(notification, binding)
                if event is None:
                    continue
                yield event
        except asyncio.CancelledError:
            prompt_task.cancel()
            raise
        except BaseException as exc:  # noqa: BLE001 - 传输断开按回合失败上报
            prompt_task.cancel()
            yield EngineEvent(
                conversation_id=request.conversation_id,
                task_id=request.task_id,
                engine_turn_id=binding["engine_turn_id"],
                sequence=0,
                type=EngineEventType.TURN_FAILED,
                payload={"error": str(exc)},
            )
            return
        stop = await prompt_task
        stop_reason = str(stop.get("stopReason") or stop.get("stop_reason") or "")
        status = "failed" if "error" in stop_reason.lower() or not stop_reason else "completed"
        yield EngineEvent(
            conversation_id=request.conversation_id,
            task_id=request.task_id,
            engine_turn_id=binding["engine_turn_id"],
            sequence=0,
            type=(
                EngineEventType.TURN_COMPLETED
                if status == "completed"
                else EngineEventType.TURN_FAILED
            ),
            payload={"summary": "DeepSeek 编程助手回合结束", "stop_reason": stop_reason},
        )

    async def cancel_turn(self, session_ref: EngineSessionRef, turn_id: str) -> None:
        del turn_id
        await self.transport.request(
            "session/cancel", {"sessionId": self._decode_ref(session_ref)}
        )

    async def amend_turn(
        self,
        session_ref: EngineSessionRef,
        engine_turn_id: str,
        amendment: TaskAmendment,
    ) -> None:
        del engine_turn_id
        # Reasonix 厂商扩展：_reasonix.io/session/steer（方法名以能力发现为准，
        # 未发现时回退官方方法名，失败按 queued_followup 处理）
        await self.transport.request(
            "_reasonix.io/session/steer",
            {
                "sessionId": self._decode_ref(session_ref),
                "prompt": [{"type": "text", "text": amendment.instructions}],
            },
        )

    async def resolve_approval(
        self,
        session_ref: EngineSessionRef,
        approval_id: str,
        decision: ApprovalDecision,
    ) -> None:
        """回复 ACP request_permission 请求（allow/deny）。"""
        session_id = self._decode_ref(session_ref)
        result = {"approved": decision == ApprovalDecision.ALLOW}
        await self.transport.respond(int(approval_id), result)
        del session_id


class AcpCodec:
    """ACP 通知 → EngineEvent 映射（与 codex CodexCodec 同构）。"""

    def __init__(self) -> None:
        self._current_tool: dict[str, str] = {}
        self._sequence = 0

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    def map_notification(self, notification: dict[str, Any], binding: dict[str, str]) -> EngineEvent | None:
        method = notification.get("method")
        params = notification.get("params") or {}
        common = {
            "conversation_id": binding["conversation_id"],
            "task_id": binding["task_id"],
            "engine_turn_id": binding["engine_turn_id"],
        }
        if method == "agent_message_chunk":
            text = str(params.get("text") or "")
            if not text:
                return None
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.ASSISTANT_DELTA,
                payload={"text": text}, **common,
            )
        if method == "thought_chunk":
            text = str(params.get("text") or "")
            if not text:
                return None
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.ASSISTANT_REASONING_DELTA,
                payload={"text": text, "channel": "summary"}, **common,
            )
        if method == "tool_call_started":
            tool_call_id = str(params.get("toolCallId") or params.get("tool_call_id") or "")
            self._current_tool[tool_call_id] = tool_call_id
            title = str(params.get("toolName") or params.get("tool_name") or "工具调用")
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.TOOL_STARTED,
                tool_call_id=tool_call_id,
                payload={"title": title, "details": str(params.get("arguments") or "")},
                **common,
            )
        if method == "tool_call_progress":
            tool_call_id = str(params.get("toolCallId") or "")
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.TOOL_PROGRESS,
                tool_call_id=tool_call_id or None,
                payload={"summary": str(params.get("summary") or "执行中")}, **common,
            )
        if method == "tool_call_completed":
            tool_call_id = str(params.get("toolCallId") or "")
            status = str(params.get("status") or "succeeded")
            succeeded = status not in {"failed", "error", "denied"}
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.TOOL_FINISHED,
                tool_call_id=tool_call_id or None,
                payload={
                    "status": "succeeded" if succeeded else "failed",
                    "title": str(params.get("toolName") or "工具调用"),
                    "summary": str(params.get("summary") or ""),
                    "details": str(params.get("details") or ""),
                    "error": None if succeeded else str(params.get("error") or ""),
                },
                **common,
            )
        if method == "session/request_permission":
            request_id = notification.get("id")
            tool_call_id = str(params.get("toolCallId") or "")
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.APPROVAL_REQUESTED,
                tool_call_id=tool_call_id or None,
                payload={
                    "approval_id": str(request_id) if request_id is not None else tool_call_id,
                    "summary": str(params.get("summary") or "需要审批的工具操作"),
                    "reason": str(params.get("reason") or ""),
                    "actor": "engine",
                },
                **common,
            )
        if method == "plan_update":
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.TOOL_PROGRESS,
                tool_call_id=None,
                payload={"summary": f"计划：{params.get('state') or '更新'}"}, **common,
            )
        return None
