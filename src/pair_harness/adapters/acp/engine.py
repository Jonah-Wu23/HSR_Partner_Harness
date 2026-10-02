# DeepSeek-Reasonix（reasonix acp）的 Agent Client Protocol v1 客户端，出处见
# THIRD_PARTY_NOTICES.md。只映射 ACP v1 字段与 Reasonix 的 _reasonix.io 扩展。

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from pair_harness.adapters.codex.transport import JsonRpcError, TransportClosed
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    ProjectRef,
    TaskAmendment,
    TaskRequest,
)
from pair_harness.core.ports import CodingEngine

logger = logging.getLogger(__name__)

NO_PROGRESS_ALERT_INTERVAL_S = 60.0
ACP_PROTOCOL_VERSION = 1

# None 表示 tool_call_update 省略了 status 字段。
_TOOL_CALL_STATUSES = (None, "pending", "in_progress", "completed", "failed")

# 编排器裁决到 ACP PermissionOptionKind 的映射。本对话内允许由 ApprovalManager
# 自己缓存，回复 Reasonix 时也只放行这一次，后续工具仍逐个经 request_permission
# 做沙箱检查与审批。
_DECISION_OPTION_KINDS = {
    ApprovalDecision.ALLOW: "allow_once",
    ApprovalDecision.ALLOW_FOR_CONVERSATION: "allow_once",
    ApprovalDecision.DENY: "reject_once",
}


class AcpProtocolError(RuntimeError):
    """Reasonix 发来的 ACP 消息不符合协议。"""


class AcpCodingEngine(CodingEngine):
    """每个聊天对应一个 ACP session，EngineSessionRef.opaque_ref 编码 sessionId。"""

    engine_type = "acp"

    def __init__(
        self,
        transport: Any,
        *,
        idle_timeout: float = 600.0,
        diagnostic_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.transport = transport
        self.idle_timeout = idle_timeout
        self.diagnostic_callback = diagnostic_callback
        self._init_lock = asyncio.Lock()
        # 已完成 initialize 的连接代次；代次变化说明 Reasonix 子进程重启过。
        self._initialized_generation: int | None = None
        # sessionId → 该会话在哪个连接代次里已经由 session/new 或 session/resume 加载。
        self._loaded_sessions: dict[str, int] = {}
        # sessionId → 助手指令，随每轮 session/prompt 发送。
        self._session_instructions: dict[str, str] = {}
        # request_permission 的 JSON-RPC id → {PermissionOptionKind: optionId}。
        self._permission_options: dict[str, dict[str, str]] = {}

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
        async with self._init_lock:
            await self.transport.start()
            if self._initialized_generation == self.transport.generation:
                return
            await self.transport.request(
                "initialize", {"protocolVersion": ACP_PROTOCOL_VERSION}
            )
            self._initialized_generation = self.transport.generation

    async def open_session(
        self,
        project: ProjectRef,
        stored_ref: EngineSessionRef | None = None,
        *,
        approval_mode: ApprovalMode,
        developer_instructions: str | None = None,
    ) -> EngineSessionRef:
        """新建会话，或在 Reasonix 子进程重启后用 session/resume 恢复会话。

        所有审批模式都把 Reasonix 的 tool_approval 设为 ask：每个工具先经
        session/request_permission 交给编排器做沙箱检查和 ApprovalManager
        裁决，FULL_AUTO 由 ApprovalManager 在沙箱检查通过后自动放行。
        ACP 的 session/new 没有系统指令字段，助手指令随每轮 prompt 发送。
        """
        del approval_mode
        await self._ensure_initialized()
        generation = self.transport.generation
        if stored_ref is None:
            result = await self.transport.request(
                "session/new", {"cwd": project.root_path, "mcpServers": []}
            )
            acp_session_id = str(result["sessionId"])
            await self._require_tool_approval(acp_session_id)
        else:
            acp_session_id = self._decode_ref(stored_ref)
            if self._loaded_sessions.get(acp_session_id) != generation:
                # session/resume 不重放历史，聊天历史以 SQLite 为准。
                await self.transport.request(
                    "session/resume",
                    {
                        "sessionId": acp_session_id,
                        "cwd": project.root_path,
                        "mcpServers": [],
                    },
                )
                await self._require_tool_approval(acp_session_id)
        self._loaded_sessions[acp_session_id] = generation
        if developer_instructions:
            self._session_instructions[acp_session_id] = developer_instructions
        else:
            self._session_instructions.pop(acp_session_id, None)
        return self._encode_ref(acp_session_id)

    async def _require_tool_approval(self, acp_session_id: str) -> None:
        await self.transport.request(
            "session/set_config_option",
            {
                "sessionId": acp_session_id,
                "configId": "tool_approval",
                "value": "ask",
            },
        )

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        acp_session_id = self._decode_ref(session_ref)
        task_text = request.instructions
        if request.constraints:
            constraints = "\n".join(f"- {item}" for item in request.constraints)
            task_text = f"{task_text}\n\n本次任务约束：\n{constraints}"
        prompt = [{"type": "text", "text": task_text}]
        instructions = self._session_instructions.get(acp_session_id)
        if instructions:
            prompt.insert(0, {"type": "text", "text": instructions})
        # 先订阅再发 session/prompt：没有订阅器时到达的会话消息会被丢弃。
        subscription = self.transport.subscribe_session(acp_session_id)
        prompt_task = asyncio.create_task(
            self.transport.request(
                "session/prompt", {"sessionId": acp_session_id, "prompt": prompt}
            )
        )
        binding = {
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "engine_turn_id": f"acp-{request.task_id}",
        }
        codec = AcpCodec()
        assistant_chunks: list[str] = []

        def accept(notification: dict[str, Any]) -> EngineEvent | None:
            event = codec.map_notification(notification, binding)
            if event is None:
                return None
            if event.type == EngineEventType.ASSISTANT_DELTA:
                assistant_chunks.append(event.payload["text"])
            elif event.type == EngineEventType.APPROVAL_REQUESTED:
                self._permission_options[event.payload["approval_id"]] = {
                    option["kind"]: option["optionId"]
                    for option in notification["params"]["options"]
                }
            return event

        quiet_seconds = 0.0
        try:
            while not prompt_task.done():
                remaining = self.idle_timeout - quiet_seconds
                slice_timeout = max(min(NO_PROGRESS_ALERT_INTERVAL_S, remaining), 0.05)
                notification_task = asyncio.create_task(subscription.next())
                try:
                    done, _ = await asyncio.wait(
                        {prompt_task, notification_task},
                        timeout=slice_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    # 被取消的 next() 不会取走队列里的消息。
                    if not notification_task.done():
                        notification_task.cancel()
                        await asyncio.gather(notification_task, return_exceptions=True)
                if notification_task in done:
                    quiet_seconds = 0.0
                    event = accept(notification_task.result())
                    if event is not None:
                        yield event
                    continue
                if done:
                    continue
                quiet_seconds += slice_timeout
                if quiet_seconds < self.idle_timeout:
                    self._emit_no_progress_warning(quiet_seconds, binding["engine_turn_id"])
                    continue
                yield await self._idle_timeout_failure(acp_session_id, prompt_task, binding)
                return
            # Reasonix 先写出本回合的通知再写 prompt 响应，读循环按行序投递，
            # 响应解析之前这些通知已进入订阅队列，这里非阻塞取完。
            while True:
                try:
                    notification = subscription.next_nowait()
                except asyncio.QueueEmpty:
                    break
                event = accept(notification)
                if event is not None:
                    yield event
            # session/prompt 的 JSON-RPC 错误在这里抛出，与传输断开、协议错误
            # 走同一个 TURN_FAILED 分支。
            stop = prompt_task.result()
        except Exception as exc:  # noqa: BLE001 - 回合失败经 TURN_FAILED 上报原始错误
            failure_payload: dict[str, Any] = {"error": f"{type(exc).__name__}: {exc}"}
            if isinstance(exc, JsonRpcError):
                failure_payload["code"] = exc.code
                failure_payload["data"] = exc.data
            if not prompt_task.done():
                # 本地出错时 Reasonix 仍在执行这一轮，通知它取消。
                try:
                    await self.transport.notify(
                        "session/cancel", {"sessionId": acp_session_id}
                    )
                except TransportClosed as cancel_exc:
                    failure_payload["cancel_error"] = (
                        f"{type(cancel_exc).__name__}: {cancel_exc}"
                    )
            logger.warning("Reasonix turn failed: %s", failure_payload)
            yield EngineEvent(
                conversation_id=request.conversation_id,
                task_id=request.task_id,
                engine_turn_id=binding["engine_turn_id"],
                sequence=0,
                type=EngineEventType.TURN_FAILED,
                payload=failure_payload,
            )
            return
        finally:
            subscription.close()
            if not prompt_task.done():
                prompt_task.cancel()
                await asyncio.gather(prompt_task, return_exceptions=True)
        # ACP v1 的 stopReason 是必填字段。end_turn 之外的取值（Reasonix 的
        # error，以及 max_tokens、max_turn_requests、refusal）都按失败上报原始
        # 取值；cancelled 经 TURN_COMPLETED 携带 status=cancelled。
        stop_reason = stop.get("stopReason", "")
        failure_reason: str | None = None
        if stop_reason == "end_turn":
            status = "completed"
        elif stop_reason == "cancelled":
            status = "cancelled"
        else:
            status = "failed"
            failure_reason = stop_reason or "session/prompt 响应缺少 stopReason"
            logger.warning("Reasonix turn failed: stopReason=%r", stop_reason)
        if assistant_chunks:
            yield EngineEvent(
                conversation_id=request.conversation_id,
                task_id=request.task_id,
                engine_turn_id=binding["engine_turn_id"],
                sequence=0,
                type=EngineEventType.ASSISTANT_FINAL,
                payload={"text": "".join(assistant_chunks)},
            )
        terminal_payload: dict[str, Any] = {
            "summary": "DeepSeek 编程助手回合结束",
            "stop_reason": stop_reason,
        }
        if status == "cancelled":
            terminal_payload["status"] = "cancelled"
        if failure_reason is not None:
            terminal_payload["error"] = failure_reason
        yield EngineEvent(
            conversation_id=request.conversation_id,
            task_id=request.task_id,
            engine_turn_id=binding["engine_turn_id"],
            sequence=0,
            type=(
                EngineEventType.TURN_FAILED
                if status == "failed"
                else EngineEventType.TURN_COMPLETED
            ),
            payload=terminal_payload,
        )

    async def _idle_timeout_failure(
        self,
        acp_session_id: str,
        prompt_task: asyncio.Task[dict[str, Any]],
        binding: dict[str, str],
    ) -> EngineEvent:
        """回合连续 idle_timeout 秒没有事件：通知 Reasonix 取消并生成失败回执。"""
        payload: dict[str, Any] = {"original_error": "idle timeout"}
        try:
            await self.transport.notify("session/cancel", {"sessionId": acp_session_id})
        except TransportClosed as exc:
            payload["cancel_error"] = f"{type(exc).__name__}: {exc}"
            logger.error("Reasonix idle timeout cancel failed: %s", exc)
        prompt_task.cancel()
        await asyncio.gather(prompt_task, return_exceptions=True)
        error_text = f"Reasonix ACP idle timeout after {self.idle_timeout}s"
        stderr_tail = self.transport.stderr_tail()
        if stderr_tail:
            error_text += f"；Reasonix 最近输出：{stderr_tail}"
            payload["stderr_tail"] = stderr_tail
        payload["error"] = error_text
        return EngineEvent(
            conversation_id=binding["conversation_id"],
            task_id=binding["task_id"],
            engine_turn_id=binding["engine_turn_id"],
            sequence=0,
            type=EngineEventType.TURN_FAILED,
            payload=payload,
        )

    def _emit_no_progress_warning(
        self, quiet_seconds: float, engine_turn_id: str
    ) -> None:
        logger.warning(
            "Reasonix turn no progress: turn=%s quiet=%.1fs",
            engine_turn_id,
            quiet_seconds,
        )
        if self.diagnostic_callback is None:
            return
        self.diagnostic_callback(
            {
                "source": "reasonix-acp",
                "code": "engine_no_progress",
                "message": (
                    f"DeepSeek Reasonix 已 {int(quiet_seconds)}s 未产生任何事件，"
                    f"超过 {int(self.idle_timeout)}s 将按空闲超时取消"
                ),
                "detail": {
                    "elapsed_s": round(quiet_seconds, 1),
                    "engine_turn_id": engine_turn_id,
                },
            }
        )

    async def cancel_turn(self, session_ref: EngineSessionRef, turn_id: str) -> None:
        del turn_id
        await self.transport.notify(
            "session/cancel", {"sessionId": self._decode_ref(session_ref)}
        )

    async def amend_turn(
        self,
        session_ref: EngineSessionRef,
        engine_turn_id: str,
        amendment: TaskAmendment,
    ) -> None:
        del engine_turn_id
        # Reasonix 扩展方法，把修改作为 user 消息插入正在执行的回合。
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
        """回复 session/request_permission，optionId 取自该请求给出的 options。"""
        del session_ref
        options = self._permission_options.pop(approval_id)
        kind = _DECISION_OPTION_KINDS[decision]
        if kind not in options:
            raise AcpProtocolError(
                f"request_permission {approval_id} 没有 {kind} 选项: {options!r}"
            )
        result = {"outcome": {"outcome": "selected", "optionId": options[kind]}}
        await self.transport.respond(int(approval_id), result)

    async def aclose(self) -> None:
        await self.transport.close()


class AcpCodec:
    """把 session/update 通知与 session/request_permission 请求映射为 EngineEvent。"""

    def __init__(self) -> None:
        self._sequence = 0
        # toolCallId → (标题, 命令摘要)。工具结束回执沿用 tool_call 的标题；
        # 失败回执附上命令，Reasonix 的失败输出常常只有退出码。
        self._tools: dict[str, tuple[str, str]] = {}

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    @staticmethod
    def _chunk_text(content: dict[str, Any]) -> str:
        """消息与思考 chunk 的 ContentBlock 文本；非文本块没有可展示的文字。"""
        return content["text"] if content["type"] == "text" else ""

    @staticmethod
    def _tool_text(content: list[dict[str, Any]]) -> str:
        """ToolCallContent 列表里文本内容块的拼接。"""
        return "\n".join(
            item["content"]["text"]
            for item in content
            if item["type"] == "content" and item["content"]["type"] == "text"
        )

    # ACP ToolKind → PendingOperation.tool_kind。读取与搜索同样按路径做沙箱
    # 校验；think、fetch、other 等没有文件目标的工具按 shell 交给审批裁决。
    _TOOL_KINDS = {
        "execute": "shell",
        "edit": "file_write",
        "move": "file_write",
        "delete": "file_delete",
        "read": "file_write",
        "search": "file_write",
    }
    # Reasonix 内置工具里不产生 locations、参数却指向文件系统的字段，
    # 取自各工具的参数 JSON schema。
    _RAW_INPUT_PATH_FIELDS = {
        "ls": ("path",),
        "grep": ("path",),
        "move_file": ("source_path", "destination_path"),
    }

    @classmethod
    def _op_fields(cls, tool_call: dict[str, Any]) -> dict[str, Any]:
        """从 ACP ToolCall 提取沙箱与审批字段。

        路径取协议字段 ``locations[].path``；Reasonix 写权限审批申请的目录在
        ``_meta["reasonix.io"].directories``。工具名取 ``_meta`` 里的 tool，
        tool_call 通知没有 ``_meta``，标题就是工具名。rawInput 只按上表的
        工具参数补充路径，execute 类工具的命令取 shell 工具参数 ``command``。
        """
        kind = tool_call.get("kind")
        meta = tool_call.get("_meta", {}).get("reasonix.io", {})
        tool_name = meta.get("tool") or tool_call.get("title")
        raw_input = tool_call.get("rawInput") or {}
        paths = [location["path"] for location in tool_call.get("locations") or ()]
        paths.extend(meta.get("directories") or ())
        for field in cls._RAW_INPUT_PATH_FIELDS.get(tool_name, ()):
            if raw_input.get(field):
                paths.append(raw_input[field])
        command = raw_input.get("command") if kind == "execute" else None
        return {
            "tool_kind": cls._TOOL_KINDS.get(kind, "shell"),
            "command": command,
            "paths": paths,
            "summary": tool_call.get("title") or command or "",
        }

    def map_notification(
        self, notification: dict[str, Any], binding: dict[str, str]
    ) -> EngineEvent | None:
        """binding 提供 conversation_id、task_id、engine_turn_id；界面辅助更新返回 None。"""
        method = notification["method"]
        params = notification["params"]
        if method == "session/request_permission":
            return self._permission_event(notification["id"], params["toolCall"], binding)
        if method != "session/update":
            return None
        update = params["update"]
        kind = update["sessionUpdate"]
        if kind in ("agent_message_chunk", "agent_thought_chunk"):
            text = self._chunk_text(update["content"])
            if not text:
                return None
            if kind == "agent_message_chunk":
                return EngineEvent(
                    sequence=self._next(), type=EngineEventType.ASSISTANT_DELTA,
                    payload={"text": text}, **binding,
                )
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.ASSISTANT_REASONING_DELTA,
                payload={"text": text, "channel": "summary"}, **binding,
            )
        if kind == "tool_call":
            tool_call_id = update["toolCallId"]
            title = update["title"]
            op = self._op_fields(update)
            self._tools[tool_call_id] = (title, op["command"] or title)
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.TOOL_STARTED,
                tool_call_id=tool_call_id,
                payload={"title": title, "details": str(update.get("rawInput") or ""), **op},
                **binding,
            )
        if kind == "tool_call_update":
            return self._tool_update_event(update, binding)
        if kind == "plan":
            summary = "计划：" + "；".join(entry["content"] for entry in update["entries"])[:200]
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.TOOL_PROGRESS,
                payload={"summary": summary}, **binding,
            )
        if kind == "usage_update":
            # ACP v1 UsageUpdate 只报告上下文窗口占用，没有分项 token 计数。
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.USAGE,
                payload={"context_used": update["used"], "context_size": update["size"]},
                **binding,
            )
        return None

    def _tool_update_event(
        self, update: dict[str, Any], binding: dict[str, str]
    ) -> EngineEvent:
        tool_call_id = update["toolCallId"]
        # ACP ToolCallStatus：只有 completed/failed 结束工具；status 缺省表示本次
        # 更新只带内容，与 pending/in_progress 一样是进度。
        status = update.get("status")
        if status not in _TOOL_CALL_STATUSES:
            raise AcpProtocolError(
                f"tool_call_update status {status!r} 不是 ACP ToolCallStatus: {update!r}"
            )
        text = self._tool_text(update.get("content") or [])
        if status not in ("completed", "failed"):
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.TOOL_PROGRESS,
                tool_call_id=tool_call_id,
                payload={"summary": text} if text else {},
                **binding,
            )
        if tool_call_id not in self._tools:
            raise AcpProtocolError(
                f"tool_call_update 结束了本回合未出现过的工具调用: {update!r}"
            )
        title, command = self._tools[tool_call_id]
        succeeded = status == "completed"
        details = text if succeeded else f"命令：{command}\n{text or status}"
        return EngineEvent(
            sequence=self._next(), type=EngineEventType.TOOL_FINISHED,
            tool_call_id=tool_call_id,
            payload={
                "status": "succeeded" if succeeded else "failed",
                "title": update.get("title") or title,
                "summary": text,
                "details": details,
                "error": None if succeeded else details,
            },
            **binding,
        )

    def _permission_event(
        self, request_id: int, tool_call: dict[str, Any], binding: dict[str, str]
    ) -> EngineEvent:
        meta = tool_call.get("_meta", {}).get("reasonix.io", {})
        return EngineEvent(
            sequence=self._next(), type=EngineEventType.APPROVAL_REQUESTED,
            tool_call_id=tool_call["toolCallId"],
            payload={
                "approval_id": str(request_id),
                "reason": meta.get("reason", ""),
                "actor": "engine",
                **self._op_fields(tool_call),
            },
            **binding,
        )
