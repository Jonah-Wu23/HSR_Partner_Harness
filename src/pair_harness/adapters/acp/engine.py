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
from collections.abc import AsyncIterator, Callable
from typing import Any

from pair_harness.adapters.codex.transport import JsonRpcError
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

# None 表示 tool_call_update 省略了 status 字段。
_TOOL_CALL_STATUSES = (None, "pending", "in_progress", "completed", "failed")


class AcpProtocolError(RuntimeError):
    """Reasonix 发来的 ACP 消息不符合协议。"""


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

    def __init__(
        self,
        transport: Any,
        *,
        model: str | None = None,
        idle_timeout: float = 600.0,
        diagnostic_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.transport = transport
        self.model = model or ""
        self.idle_timeout = idle_timeout
        self.diagnostic_callback = diagnostic_callback
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._transport_generation = getattr(transport, "generation", 0)

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
            generation = getattr(self.transport, "generation", 0)
            if self._transport_generation != generation:
                # M1.4：断线/重连后 transport 代次变化，必须重新 initialize。
                self._initialized = False
                self._transport_generation = generation
            if self._initialized:
                return
            await self.transport.start()
            generation = getattr(self.transport, "generation", 0)
            if self._transport_generation != generation:
                self._transport_generation = generation
            await self.transport.request(
                "initialize",
                {"clientInfo": {"name": "pair-harness", "version": "0.3.4"}},
            )
            self._initialized = True
            self._transport_generation = generation

    async def open_session(
        self,
        project: ProjectRef,
        stored_ref: EngineSessionRef | None = None,
        *,
        approval_mode: ApprovalMode,
        developer_instructions: str | None = None,
    ) -> EngineSessionRef:
        """打开（或恢复）ACP 会话。

        所有审批模式都把 Reasonix 的 tool_approval 设为 ask：每个工具先经
        session/request_permission 交给编排器做沙箱检查和 ApprovalManager
        裁决，FULL_AUTO 由 ApprovalManager 在沙箱检查通过后自动放行。
        """
        del approval_mode
        await self._ensure_initialized()
        if stored_ref is not None:
            # session/resume 恢复会话。恢复期间的会话事件用临时订阅器隔离并
            # 排空：历史以 SQLite 为准，replay 不写入消息历史，也不流入通用
            # 通知队列。
            acp_session_id = self._decode_ref(stored_ref)
            resume_subscription = self.transport.subscribe_session(acp_session_id)
            try:
                await self.transport.request(
                    "session/resume",
                    {"sessionId": acp_session_id, "cwd": project.root_path},
                )
                loop = asyncio.get_running_loop()
                resume_deadline = loop.time() + 1.0
                while loop.time() < resume_deadline:
                    try:
                        await asyncio.wait_for(
                            resume_subscription.next(), timeout=0.1
                        )
                    except asyncio.TimeoutError:
                        break
            finally:
                resume_subscription.close()
            # 恢复的会话可能带着旧版本设置的 yolo，这里重新设为 ask。
            await self._require_tool_approval(acp_session_id)
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
        await self._require_tool_approval(str(session_id))
        return self._encode_ref(str(session_id))

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
        # V0.3.2 M3：先订阅本 session 的通知，再发送 session/prompt——
        # 订阅建立前到达的事件会进入诊断缓冲而不是本回合，顺序不可颠倒。
        # 共享 transport 上多个 session 并发运行时各自拿到自己的事件流。
        subscription = self.transport.subscribe_session(acp_session_id)
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
            "acp_session_id": acp_session_id,
        }
        codec = AcpCodec()
        assistant_chunks: list[str] = []
        quiet_seconds = 0.0

        def remember_event(event: EngineEvent) -> None:
            if event.type == EngineEventType.ASSISTANT_DELTA:
                assistant_chunks.append(str(event.payload.get("text") or ""))

        notification_task: asyncio.Task[Any] | None = None
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
                                subscription.next(), timeout=timeout
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
                notification_task = asyncio.create_task(subscription.next())
                try:
                    remaining = self.idle_timeout - quiet_seconds
                    slice_timeout = max(
                        min(NO_PROGRESS_ALERT_INTERVAL_S, remaining),
                        0.05,
                    )
                    done, _ = await asyncio.wait(
                        {prompt_task, notification_task},
                        timeout=slice_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        quiet_seconds += slice_timeout
                        if quiet_seconds >= self.idle_timeout:
                            cancel_error = None
                            try:
                                await self.transport.notify(
                                    "session/cancel",
                                    {"sessionId": acp_session_id},
                                )
                            except Exception as exc:  # noqa: BLE001
                                cancel_error = f"{type(exc).__name__}: {exc}"
                                logger.error(
                                    "Reasonix idle timeout cancel failed: %s", exc
                                )
                            if not prompt_task.done():
                                prompt_task.cancel()
                            await asyncio.gather(
                                prompt_task, return_exceptions=True
                            )
                            stderr_tail = self.transport.stderr_tail()
                            error_text = (
                                "Reasonix ACP idle timeout after "
                                f"{self.idle_timeout}s"
                            )
                            if stderr_tail:
                                error_text += (
                                    f"；Reasonix 最近输出：{stderr_tail}"
                                )
                            payload: dict[str, Any] = {
                                "error": error_text,
                                "original_error": "idle timeout",
                            }
                            if stderr_tail:
                                payload["stderr_tail"] = stderr_tail
                            if cancel_error is not None:
                                payload["cancel_error"] = cancel_error
                            yield EngineEvent(
                                conversation_id=request.conversation_id,
                                task_id=request.task_id,
                                engine_turn_id=binding["engine_turn_id"],
                                sequence=0,
                                type=EngineEventType.TURN_FAILED,
                                payload=payload,
                            )
                            return
                        self._emit_no_progress_warning(
                            quiet_seconds,
                            binding["engine_turn_id"],
                        )
                        continue
                    quiet_seconds = 0.0
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
                finally:
                    # M1.4：每轮创建的 notification_task 必须取消并 await，
                    # 不能留下 pending task 泄漏。
                    if notification_task is not None:
                        if not notification_task.done():
                            notification_task.cancel()
                        await asyncio.gather(notification_task, return_exceptions=True)
                        notification_task = None
            # session/prompt 的 JSON-RPC 错误在这里抛出，与传输断开、协议错误
            # 走同一个 TURN_FAILED 分支。
            stop = prompt_task.result()
        except GeneratorExit:
            # 消费方 aclose() 抛出的 GeneratorExit 必须直通，订阅器由 finally
            # 归还；这里 yield TURN_FAILED 会让 aclose() 抛 RuntimeError。
            raise
        except asyncio.CancelledError:
            if not prompt_task.done():
                prompt_task.cancel()
            await asyncio.gather(prompt_task, return_exceptions=True)
            raise
        except Exception as exc:  # noqa: BLE001 - 回合失败经 TURN_FAILED 上报原始错误
            failure_payload: dict[str, Any] = {"error": f"{type(exc).__name__}: {exc}"}
            if isinstance(exc, JsonRpcError):
                failure_payload["code"] = exc.code
                failure_payload["data"] = exc.data
            if not prompt_task.done():
                # 本地出错时 Reasonix 仍在执行这一轮，通知它取消。
                prompt_task.cancel()
                try:
                    await self.transport.notify(
                        "session/cancel", {"sessionId": acp_session_id}
                    )
                except Exception as cancel_exc:  # noqa: BLE001 - 取消失败随回执上报
                    failure_payload["cancel_error"] = (
                        f"{type(cancel_exc).__name__}: {cancel_exc}"
                    )
            await asyncio.gather(prompt_task, return_exceptions=True)
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
            # V0.3.2 M3：订阅器随回合结束归还，session 路由槽位释放。
            subscription.close()
            # 取消/异常路径也要结清 notification_task（外层防御）
            if notification_task is not None:
                if not notification_task.done():
                    notification_task.cancel()
                await asyncio.gather(notification_task, return_exceptions=True)
            if not prompt_task.done():
                prompt_task.cancel()
                await asyncio.gather(prompt_task, return_exceptions=True)
        stop_reason = str(stop.get("stopReason") or stop.get("stop_reason") or "")
        stop_error = (
            stop.get("error")
            or stop.get("errorMessage")
            or stop.get("error_message")
        )
        # 回合终态只以协议响应为准。ACP v1 的 PromptResponse.stopReason 是必填
        # 字段，供应商、工具和运行时失败走 JSON-RPC 错误；stopReason 缺失或为空
        # 即协议违规，按失败上报。工具执行成功不能反证回合成功。
        normalized_reason = stop_reason.strip().lower()
        failure_reason: str | None = None
        if stop_error is not None:
            status = "failed"
            failure_reason = str(stop_error)
        elif normalized_reason == "end_turn":
            status = "completed"
        elif normalized_reason == "cancelled":
            # 协议终态 cancelled 不是成功：与 codex 适配器同形，经
            # TURN_COMPLETED 携带 status=cancelled，编排器据 payload.status
            # 生成取消回执（不降级成 failed，也不伪装成 completed）。
            status = "cancelled"
        elif not normalized_reason:
            # 必填字段缺失/为空：不是成功，也不能让失败原因留空。
            status = "failed"
            failure_reason = "session/prompt 响应缺少 stopReason（ACP 要求必带终态）"
        else:
            # 其余取值（max_turn_requests 或未知取值）都不是协议定义的成功
            # 终态：如实上报失败并带上原始取值，不做语义猜测。
            status = "failed"
            failure_reason = stop_reason
        if status == "failed":
            # 真实失败必须留下可定位的原始终态，不静默改写、不只进日志不进回执。
            logger.warning(
                "Reasonix turn failed by protocol terminal state: stop_reason=%r error=%r",
                stop_reason,
                stop_error,
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
        # V0.3.3：tool_call → tool_call_update 之间记下该工具的命令摘要，
        # 失败回执把命令拼进 details/error——真实 Reasonix 失败常常只给
        # "command exited: exit status 1"，没有命令就无法定位是哪个工具。
        self._tool_commands: dict[str, str] = {}

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
    def _usage_number(content: Any, *keys: str) -> int | None:
        """从 usage 对象里取第一个存在的整数 token 值；无则返回 None（不估算）。"""
        for key in keys:
            value = content.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        return None

    @staticmethod
    def _tool_text(content: Any) -> str:
        """tool_call_update 的 content（结果文本）提取。

        兼容 dict / 文本数组两种形状；失败型工具可能携带 stderr/error/
        traceback 字段，一并并入结果文本供错误卡片定位失败原因。
        """
        result_keys = ("text", "output", "result", "stderr", "error", "traceback")
        if isinstance(content, dict):
            return str(next((content[k] for k in result_keys if content.get(k)), ""))
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            nested = item.get("content")
            if isinstance(nested, dict):
                value = next((nested[k] for k in result_keys if nested.get(k)), "")
            else:
                value = next((item[k] for k in result_keys if item.get(k)), "")
            if value:
                parts.append(str(value))
        return "\n".join(parts)

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
        meta = (tool_call.get("_meta") or {}).get("reasonix.io") or {}
        tool_name = meta.get("tool") or tool_call.get("title")
        raw_input = tool_call.get("rawInput")
        if not isinstance(raw_input, dict):
            raw_input = {}
        paths = [str(location["path"]) for location in tool_call.get("locations") or ()]
        paths.extend(str(directory) for directory in meta.get("directories") or ())
        for field in cls._RAW_INPUT_PATH_FIELDS.get(str(tool_name), ()):
            value = raw_input.get(field)
            if isinstance(value, str) and value.strip():
                paths.append(value)
        command = raw_input.get("command") if kind == "execute" else None
        if not isinstance(command, str):
            command = None
        return {
            "tool_kind": cls._TOOL_KINDS.get(str(kind), "shell"),
            "command": command,
            "paths": paths,
            "summary": str(tool_call.get("title") or "") or (command or ""),
        }

    def map_notification(self, notification: dict[str, Any], binding: dict[str, str]) -> EngineEvent | None:
        method = notification.get("method")
        params = notification.get("params") or {}
        common = {
            "conversation_id": binding["conversation_id"],
            "task_id": binding["task_id"],
            "engine_turn_id": binding["engine_turn_id"],
        }

        # M1.4：能提供 session/turn 标识时核对归属；不匹配的事件记录协议
        # 错误，不能投影到当前会话。
        session_id = params.get("sessionId") or params.get("session_id")
        expected_session = binding.get("acp_session_id")
        if session_id is not None and expected_session is not None:
            if str(session_id) != str(expected_session):
                logger.warning(
                    "ACP notification session mismatch: got %r expected %r",
                    session_id,
                    expected_session,
                )
                return None
        turn_id = params.get("turnId") or params.get("turn_id")
        if turn_id is not None and binding.get("engine_turn_id"):
            # ACP 当前协议没有稳定 turnId 时，不额外投影；若服务端给出
            # 明确不匹配的 turn 标识，同样按协议错误丢弃。
            expected_turn = binding.get("acp_turn_id")
            if expected_turn is not None and str(turn_id) != str(expected_turn):
                logger.warning(
                    "ACP notification turn mismatch: got %r expected %r",
                    turn_id,
                    expected_turn,
                )
                return None

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
                if tool_call_id:
                    self._tool_commands[tool_call_id] = op["command"] or str(
                        update.get("title") or "工具调用"
                    )
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
                # ACP ToolCallStatus：只有 completed/failed 结束工具；status
                # 缺省表示本次更新只带内容，与 pending/in_progress 一样是进度。
                status = update.get("status")
                if status not in _TOOL_CALL_STATUSES:
                    raise AcpProtocolError(
                        f"tool_call_update status {status!r} 不是 ACP ToolCallStatus: {update!r}"
                    )
                text = self._tool_text(
                    update.get("content")
                    or update.get("result")
                    or update.get("output")
                )
                if status not in ("completed", "failed"):
                    return EngineEvent(
                        sequence=self._next(), type=EngineEventType.TOOL_PROGRESS,
                        tool_call_id=tool_call_id or None,
                        payload={"summary": text} if text else {},
                        **common,
                    )
                succeeded = status == "completed"
                # 失败工具附上对应 tool_call 的命令摘要，工具结果里的
                # stderr/error 文本已由 _tool_text 并入。
                if succeeded:
                    details = text
                else:
                    command = self._tool_commands.get(tool_call_id, "")
                    details = text or status
                    if command:
                        details = f"命令：{command}" + (f"\n{details}" if details else "")
                return EngineEvent(
                    sequence=self._next(), type=EngineEventType.TOOL_FINISHED,
                    tool_call_id=tool_call_id or None,
                    payload={
                        "status": "succeeded" if succeeded else "failed",
                        "title": str(update.get("title") or "工具调用"),
                        "summary": text,
                        "details": details,
                        "error": None if succeeded else details,
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
            if kind == "usage_update":
                # V0.3.9 §5：真实 usage 只来自服务端上报，绝不估算。
                # 兼容 update.usage.tokenUsage / update.usage 扁平 / 顶层
                # tokenUsage 三种形状；字段缺失保持 null（键仍存在）。
                usage = update.get("usage")
                if not isinstance(usage, dict):
                    usage = update.get("tokenUsage")
                if not isinstance(usage, dict):
                    usage = {}
                nested = usage.get("tokenUsage")
                if isinstance(nested, dict):
                    usage = nested
                payload: dict[str, Any] = {
                    "input_tokens": AcpCodec._usage_number(
                        usage, "inputTokens", "input_tokens", "promptTokens",
                        "prompt_tokens", "input",
                    ),
                    "output_tokens": AcpCodec._usage_number(
                        usage, "outputTokens", "output_tokens",
                        "completionTokens", "completion_tokens", "output",
                    ),
                    "total_tokens": AcpCodec._usage_number(
                        usage, "totalTokens", "total_tokens", "total",
                    ),
                }
                return EngineEvent(
                    sequence=self._next(), type=EngineEventType.USAGE,
                    payload=payload, **common,
                )
            # available_commands_update / model_update 等界面辅助更新不映射为事件
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
