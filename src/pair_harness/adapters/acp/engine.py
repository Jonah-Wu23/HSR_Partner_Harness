"""DeepSeek 编程助手（Reasonix ACP v1 客户端）——V0.2 M3（方案 §M3-5）。

复用本地 DeepSeek-Reasonix 的 ACP/流式会话能力作为引擎边界（出处见
THIRD_PARTY_NOTICES.md）：Reasonix 以 Agent Client Protocol v1 的 NDJSON
JSON-RPC 2.0 暴露于 stdin/stdout（``reasonix acp``）。本适配器复用
``JsonlProcessTransport`` 与编排器现有 EngineEvent 事件模型，把 ACP 的
``agent_message_chunk``/``thought_chunk``/``tool_call_*``/``request_permission``
映射为统一的工具、审批和消息事件。账号、项目与引擎会话仍由编排器管理。

协议要点（DeepSeek-Reasonix/docs/ACP.zh-CN.md，v1.24 实测）：
- ``initialize`` → ``session/new {cwd}`` 打开会话，返回 sessionId；
- ``session/prompt`` 运行一轮并持续推送更新，直到返回 stop reason；
- 回合内事件统一经 ``session/update`` 通知（``params.update.sessionUpdate``
  区分 ``agent_message_chunk`` / ``agent_thought_chunk`` / ``tool_call`` /
  ``tool_call_update`` / ``plan``）；
- ``session/request_permission`` 是服务端请求（带 JSON-RPC id），须经
  ``transport.respond(id, {"outcome": {"outcome": "selected", "optionId": ...}})``
  回复（allow_once / allow_always / reject_once）；
- 取消走 ``session/cancel``（notification，无 id）；steer 走厂商扩展
  ``_reasonix.io/session/steer``。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
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

logger = logging.getLogger(__name__)


class AcpCodingEngine(CodingEngine):
    """Reasonix ACP 会话的 CodingEngine 适配器。

    每个会话（conversation）一个 ACP session；``EngineSessionRef.opaque_ref``
    编码 acp session_id，与 codex 适配器编码 thread_id 同构。
    """

    engine_type = "acp"
    # reasonix 在工具执行前经 session/request_permission 挂起请求（原生
    # 执行前审批），编排器裁决后 resolve_approval 回复；TOOL_STARTED 事件
    # 不需要再走本地兜底门控（否则双重审批）。
    native_preexecution_approval = True
    # Reasonix 的 prompt 响应与最后一批 session/update 偶尔不在同一
    # 事件循环 tick 到达。给通知队列留一个短暂静默窗口，收齐工具回执。
    _POST_PROMPT_DRAIN_IDLE_SECONDS = 0.25
    _POST_PROMPT_DRAIN_MAX_SECONDS = 2.0

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
            {"clientInfo": {"name": "pair-harness", "version": "0.3.0"}},
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
        # 工具审批策略：编排器按审批模式传入（untrusted/never）→ reasonix
        # 的 ask/yolo（reasonix 不接受未知值，unknown 会按 ask 归一）
        if approval_policy is not None:
            await self.transport.request(
                "session/set_config_option",
                {
                    "sessionId": session_id,
                    "configId": "tool_approval",
                    "value": "yolo" if approval_policy == "never" else "ask",
                },
            )
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
        assistant_chunks: list[str] = []
        tool_succeeded = False
        tool_failed = False

        def remember_event(event: EngineEvent) -> None:
            nonlocal tool_succeeded, tool_failed
            if event.type == EngineEventType.ASSISTANT_DELTA:
                assistant_chunks.append(str(event.payload.get("text") or ""))
            elif event.type == EngineEventType.TOOL_FINISHED:
                if str(event.payload.get("status") or "") == "succeeded":
                    tool_succeeded = True
                else:
                    tool_failed = True

        try:
            while True:
                if prompt_task.done():
                    # prompt 已返回：回合结束，但通知可能在稍后的事件循环
                    # tick 到达。消费一个有上限的静默窗口，保留最后的工具回执。
                    loop = asyncio.get_running_loop()
                    max_deadline = loop.time() + self._POST_PROMPT_DRAIN_MAX_SECONDS
                    deadline = max_deadline
                    while loop.time() < deadline:
                        timeout = min(
                            self._POST_PROMPT_DRAIN_IDLE_SECONDS,
                            max(0.0, deadline - loop.time()),
                        )
                        try:
                            notification = await asyncio.wait_for(
                                self.transport.next_notification(), timeout=timeout
                            )
                        except asyncio.TimeoutError:
                            break
                        event = codec.map_notification(notification, binding)
                        if event is None:
                            continue
                        remember_event(event)
                        yield event
                        # 收到事件后再留一个短窗口，覆盖同一回合的后续更新。
                        deadline = min(
                            loop.time() + self._POST_PROMPT_DRAIN_IDLE_SECONDS,
                            max_deadline,
                        )
                    break
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
                            remember_event(event)
                            yield event
                    else:
                        notification_task.cancel()
                    continue
                notification = notification_task.result()
                event = codec.map_notification(notification, binding)
                if event is None:
                    continue
                remember_event(event)
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
        stop_error = (
            stop.get("error")
            or stop.get("errorMessage")
            or stop.get("error_message")
        )
        # Reasonix 的真实 session/prompt 成功响应可能只包含 sessionId，
        # 不带 stopReason。v1.24.2 还会在助手最终回复与工具均成功后返回
        # stopReason=error；此时保留 warning，但不能把已完成的任务改写成失败。
        failure_text = f"{stop_reason} {stop_error or ''}".lower()
        terminal_error = bool(
            stop_error or "error" in failure_text or "fail" in failure_text
        )
        recoverable_terminal_error = terminal_error and bool(
            assistant_chunks and tool_succeeded and not tool_failed
        )
        status = "completed" if not terminal_error or recoverable_terminal_error else "failed"
        warning = None
        if recoverable_terminal_error:
            warning = stop_error or stop_reason
            logger.warning(
                "Reasonix returned terminal error after successful tool execution: %s",
                warning,
            )
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
        if warning:
            terminal_payload["warning"] = str(warning)
        if status == "failed" and stop_error:
            terminal_payload["error"] = str(stop_error)
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
            payload=terminal_payload,
        )

    async def cancel_turn(self, session_ref: EngineSessionRef, turn_id: str) -> None:
        del turn_id
        # ACP 的 session/cancel 是 notification（无 id，服务端不回复）；
        # 按 request 发送会挂在 pending 直到超时。
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
        """回复 ACP request_permission 请求（outcome.selected + optionId）。

        reasonix 按 PermissionRequestResult 解析：``selected`` + optionId
        才会生效（allow_once / allow_always / reject_once）；旧形状
        ``{"approved": bool}`` 一律视为未选择（等于否决）。
        """
        # 解码只做类型校验：engine_type 不符会抛 ValueError
        self._decode_ref(session_ref)
        option_id = {
            ApprovalDecision.ALLOW: "allow_once",
            ApprovalDecision.ALLOW_FOR_CONVERSATION: "allow_always",
            ApprovalDecision.DENY: "reject_once",
        }[decision]
        result = {"outcome": {"outcome": "selected", "optionId": option_id}}
        await self.transport.respond(int(approval_id), result)


class AcpCodec:
    """ACP 通知 → EngineEvent 映射（reasonix v1.24 实测形状）。

    reasonix 把消息/思考/工具/计划统一封装为 ``session/update`` 通知，
    类型在 ``params.update.sessionUpdate``；``session/request_permission``
    是服务端发起的 JSON-RPC 请求（带 id），经 ``transport.respond`` 回复
    ``outcome``。仍保留直接 method 形状的兼容分支（旧版/其他 ACP 服务器）。
    """

    def __init__(self) -> None:
        self._sequence = 0

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    @staticmethod
    def _text_of(content: Any) -> str:
        """message/thought chunk 的纯文本。"""
        if isinstance(content, dict):
            return str(content.get("text") or "")
        return ""

    @staticmethod
    def _tool_text(content: Any) -> str:
        """tool_call_update 的 content 数组（结果文本）提取。"""
        if isinstance(content, dict):
            return str(content.get("text") or content.get("output") or content.get("result") or "")
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            nested = item.get("content")
            if isinstance(nested, dict) and nested.get("text"):
                parts.append(str(nested["text"]))
            elif item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)

    @staticmethod
    def _op_fields(update: dict[str, Any]) -> dict[str, Any]:
        """从 tool_call / request_permission 的 rawInput 提取门控字段。

        映射到编排器 PendingOperation 的有限枚举：execute→shell（命令），
        edit→file_write，read/search→file_write（只读路径按写路径做沙箱
        校验，越界读取照常拦截）。kind 缺省按 rawInput 字段启发。
        """
        kind = str(update.get("kind") or "").lower()
        raw = update.get("rawInput")
        args: dict[str, Any] = {}
        if isinstance(raw, dict):
            args = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    args = parsed
            except (ValueError, TypeError):
                pass
        if kind == "execute":
            tool_kind = "shell"
        elif kind == "edit":
            tool_kind = "file_write"
        elif kind in ("read", "search"):
            tool_kind = "file_write"
        elif "command" in args or "cmd" in args or "script" in args:
            tool_kind = "shell"
        elif "file_path" in args or "filePath" in args or "path" in args or "paths" in args:
            tool_kind = "file_write"
        else:
            tool_kind = "shell"
        command = args.get("command") or args.get("cmd") or args.get("script")
        path = args.get("file_path") or args.get("filePath") or args.get("path")
        paths = args.get("paths")
        if not paths and path:
            paths = [path]
        return {
            "tool_kind": tool_kind,
            "command": str(command) if isinstance(command, str) else None,
            "paths": [str(p) for p in paths] if isinstance(paths, (list, tuple)) else [],
            "summary": str(update.get("title") or "") or (str(command) if command else ""),
        }

    def map_notification(self, notification: dict[str, Any], binding: dict[str, str]) -> EngineEvent | None:
        method = notification.get("method")
        params = notification.get("params") or {}
        common = {
            "conversation_id": binding["conversation_id"],
            "task_id": binding["task_id"],
            "engine_turn_id": binding["engine_turn_id"],
        }

        if method == "session/update":
            update = params.get("update")
            if not isinstance(update, dict):
                return None
            kind = str(update.get("sessionUpdate") or "")
            if kind == "agent_message_chunk":
                text = self._text_of(update.get("content"))
                if not text:
                    return None
                return EngineEvent(
                    sequence=self._next(), type=EngineEventType.ASSISTANT_DELTA,
                    payload={"text": text}, **common,
                )
            if kind == "agent_thought_chunk":
                text = self._text_of(update.get("content"))
                if not text:
                    return None
                return EngineEvent(
                    sequence=self._next(), type=EngineEventType.ASSISTANT_REASONING_DELTA,
                    payload={"text": text, "channel": "summary"}, **common,
                )
            if kind == "tool_call":
                tool_call_id = str(
                    update.get("toolCallId")
                    or update.get("tool_call_id")
                    or update.get("id")
                    or ""
                )
                op = self._op_fields(update)
                return EngineEvent(
                    sequence=self._next(), type=EngineEventType.TOOL_STARTED,
                    tool_call_id=tool_call_id or None,
                    payload={
                        "title": str(update.get("title") or "工具调用"),
                        "details": str(update.get("rawInput") or ""),
                        **op,
                    },
                    **common,
                )
            if kind == "tool_call_update":
                tool_call_id = str(
                    update.get("toolCallId")
                    or update.get("tool_call_id")
                    or update.get("id")
                    or ""
                )
                status = str(update.get("status") or update.get("state") or "completed").lower()
                succeeded = status not in {"failed", "error", "denied", "rejected"}
                text = self._tool_text(
                    update.get("content")
                    or update.get("result")
                    or update.get("output")
                )
                return EngineEvent(
                    sequence=self._next(), type=EngineEventType.TOOL_FINISHED,
                    tool_call_id=tool_call_id or None,
                    payload={
                        "status": "succeeded" if succeeded else "failed",
                        "title": str(update.get("title") or "工具调用"),
                        "summary": text,
                        "details": text,
                        "error": None if succeeded else text or status,
                    },
                    **common,
                )
            if kind == "plan":
                entries = update.get("entries")
                summary = "计划："
                if isinstance(entries, list):
                    titles = [
                        str(entry.get("content") or entry.get("title") or "")
                        for entry in entries
                        if isinstance(entry, dict)
                    ]
                    summary += "；".join(t for t in titles if t)[:200]
                return EngineEvent(
                    sequence=self._next(), type=EngineEventType.TOOL_PROGRESS,
                    tool_call_id=None,
                    payload={"summary": summary}, **common,
                )
            # available_commands_update / usage_update / model_update 等
            # 界面辅助更新不映射为事件
            return None

        if method == "session/request_permission":
            request_id = notification.get("id")
            tool = params.get("toolCall")
            tool_update = tool if isinstance(tool, dict) else {}
            tool_call_id = str(tool_update.get("toolCallId") or "")
            meta = tool_update.get("_meta")
            reason = ""
            if isinstance(meta, dict):
                reasonix_meta = meta.get("reasonix.io")
                if isinstance(reasonix_meta, dict):
                    reason = str(reasonix_meta.get("reason") or "")
            op = self._op_fields(tool_update)
            return EngineEvent(
                sequence=self._next(), type=EngineEventType.APPROVAL_REQUESTED,
                tool_call_id=tool_call_id or None,
                payload={
                    "approval_id": str(request_id) if request_id is not None else tool_call_id,
                    "summary": op["summary"] or "需要审批的工具操作",
                    "reason": reason,
                    "actor": "engine",
                    **op,
                },
                **common,
            )

        # ---- 直接 method 形状的兼容分支（旧版 ACP 服务器） ----
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
        if method == "tool_call_completed":
            tool_call_id = str(
                params.get("toolCallId")
                or params.get("tool_call_id")
                or params.get("id")
                or ""
            )
            status = str(params.get("status") or "succeeded").lower()
            succeeded = status not in {"failed", "error", "denied", "rejected"}
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
        return None
