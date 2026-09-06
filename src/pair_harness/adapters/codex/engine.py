from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator, Callable
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

from .codec import CodexCodec, EventBinding
from .transport import JsonlProcessTransport

logger = logging.getLogger(__name__)

# V0.3.8 T4（契约 §14.6）：回合无进展告警的检测间隔。app-server 静默重试期
# （如模型供给误配打向不可达端点）客户端此前零感知，每满 60s 无任何 JSONL
# 消息即发一次 diagnostic.warning，直到有进展或回合终态。
NO_PROGRESS_ALERT_INTERVAL_S = 60.0


class CodexAppServerEngine(CodingEngine):
    engine_type = "codex-app-server"
    native_preexecution_approval = True

    def __init__(
        self,
        transport: JsonlProcessTransport,
        *,
        model: str = "gpt-5.6-sol",
        reasoning_effort: str = "medium",
        idle_timeout: float = 600.0,
        diagnostic_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.transport = transport
        self.model = model
        # auto 在 Codex 端没有对应档位，沿用 configure_reasoning 的语义
        # 归一化为 medium（F5 档位）。
        self.reasoning_effort = "medium" if reasoning_effort == "auto" else reasoning_effort
        # B1 联调：app-server 协议要求连接后先发 initialize 握手，
        # 否则 thread/start 返回 {"code": -32600, "message": "Not initialized"}。
        # 每个引擎实例（每次连接）只需一次。
        self._initialized = False
        self._transport_generation = transport.generation
        # M1.3：当前 turn 连续无事件的最大空闲时间；超时先 interrupt 再失败。
        self.idle_timeout = idle_timeout
        # V0.3.8 T4：引擎诊断告警出口（None 时告警仅落本地日志）。
        self.diagnostic_callback = diagnostic_callback

    def configure_reasoning(self, effort: str) -> None:
        """设置 GPT-5.6 Sol 的真实 reasoning effort。"""
        normalized = "medium" if effort == "auto" else effort
        if normalized not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError(f"unsupported Codex reasoning effort: {effort}")
        self.reasoning_effort = normalized

    @staticmethod
    def _encode_ref(thread_id: str) -> EngineSessionRef:
        raw = json.dumps({"thread_id": thread_id}, separators=(",", ":")).encode("utf-8")
        return EngineSessionRef(
            engine_type=CodexAppServerEngine.engine_type,
            opaque_ref=base64.urlsafe_b64encode(raw).decode("ascii"),
        )

    @staticmethod
    def _decode_ref(ref: EngineSessionRef) -> str:
        if ref.engine_type != CodexAppServerEngine.engine_type:
            raise ValueError(f"unsupported engine session type: {ref.engine_type}")
        data = json.loads(base64.urlsafe_b64decode(ref.opaque_ref.encode("ascii")))
        return str(data["thread_id"])

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
        """打开（或恢复）app-server 线程。

        O3.1：``approval_policy``/``sandbox``/``approvals_reviewer`` 映射到
        thread/start 的 approvalPolicy / sandbox / approvalsReviewer 字段
        （字段名经 codex app-server generate-json-schema 0.147.0 确认）。
        仅新开线程时发送；恢复线程（thread/resume）沿用线程既有设置。
        B1 联调时由编排器按审批模式（request_approval → "untrusted" 等）
        与沙箱配置传入真实参数。
        """
        was_running = self.transport.is_running
        await self.transport.start()
        # M1.3：transport 重连后连接代次变化，必须复位并重新 initialize。
        if self._transport_generation != self.transport.generation:
            self._initialized = False
            self._transport_generation = self.transport.generation
        if not self._initialized or not was_running:
            await self.transport.request(
                "initialize",
                {"clientInfo": {"name": "pair-harness", "version": "0.3.4"}},
            )
            self._initialized = True
        if stored_ref is not None:
            thread_id = self._decode_ref(stored_ref)
            resume_params: dict[str, object] = {"threadId": thread_id}
            if developer_instructions:
                resume_params["developerInstructions"] = developer_instructions
            result = await self.transport.request("thread/resume", resume_params)
            resumed = result.get("thread") or {}
            return self._encode_ref(str(resumed.get("id") or thread_id))
        params: dict[str, object] = {"cwd": project.root_path}
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        if sandbox is not None:
            params["sandbox"] = sandbox
        if approvals_reviewer is not None:
            params["approvalsReviewer"] = approvals_reviewer
        if developer_instructions:
            params["developerInstructions"] = developer_instructions
        result = await self.transport.request("thread/start", params)
        thread = result.get("thread") or {}
        thread_id = thread.get("id")
        if not thread_id:
            raise RuntimeError("thread/start returned no thread id")
        return self._encode_ref(str(thread_id))

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        thread_id = self._decode_ref(session_ref)
        # 古代机械的 developer instructions 只接受结构化 TaskRequest。
        # 保留内部任务包络，避免恢复线程后把普通自然语言误判为无效指令。
        task_text = json.dumps(
            {
                "type": "TaskRequest",
                "task_id": request.task_id,
                "instructions": request.instructions,
                "constraints": list(request.constraints),
            },
            ensure_ascii=False,
        )
        result = await self.transport.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": task_text}],
                "model": self.model,
                "effort": self.reasoning_effort,
            },
        )
        turn = result.get("turn") or {}
        turn_id = str(turn.get("id") or "")
        if not turn_id:
            raise RuntimeError("turn/start returned no turn id")
        binding = EventBinding(
            conversation_id=request.conversation_id,
            task_id=request.task_id,
            engine_turn_id=turn_id,
        )
        codec = CodexCodec()
        quiet_seconds = 0.0
        try:
            while True:
                # V0.3.8 T4：等待切成 ≤60s 分片——每满一段无任何 JSONL 消息
                # 发一次无进展告警（契约 §14.6），累计到 idle_timeout 仍无
                # 事件才走 M1.3 空闲超时。
                remaining = self.idle_timeout - quiet_seconds
                slice_timeout = min(NO_PROGRESS_ALERT_INTERVAL_S, remaining)
                try:
                    notification = await asyncio.wait_for(
                        self.transport.next_notification(),
                        timeout=max(slice_timeout, 0.05),
                    )
                except asyncio.TimeoutError:
                    quiet_seconds += max(slice_timeout, 0.05)
                    if quiet_seconds >= self.idle_timeout:
                        # M1.3：空闲超时——先请求 interrupt，再产生带原始原因的失败。
                        interrupt_error = None
                        try:
                            await self.transport.request(
                                "turn/interrupt",
                                {"threadId": thread_id, "turnId": turn_id},
                            )
                        except Exception as exc:  # noqa: BLE001 - interrupt 失败也记录
                            interrupt_error = f"{type(exc).__name__}: {exc}"
                            logger.error("Codex idle timeout interrupt failed: %s", exc)
                        stderr_tail = self.transport.stderr_tail()
                        error_text = (
                            f"Codex app-server idle timeout after "
                            f"{self.idle_timeout}s"
                        )
                        if stderr_tail:
                            error_text = f"{error_text}；app-server 最近输出：{stderr_tail}"
                        payload: dict[str, Any] = {
                            "error": error_text,
                            "original_error": "idle timeout",
                        }
                        if stderr_tail:
                            payload["stderr_tail"] = stderr_tail
                        if interrupt_error is not None:
                            payload["interrupt_error"] = interrupt_error
                        logger.error("Codex turn idle timeout: turn=%s", turn_id)
                        yield EngineEvent(
                            conversation_id=request.conversation_id,
                            task_id=request.task_id,
                            engine_turn_id=turn_id,
                            sequence=0,
                            type=EngineEventType.TURN_FAILED,
                            payload=payload,
                        )
                        return
                    self._emit_no_progress_warning(quiet_seconds, turn_id)
                    continue
                except Exception as exc:  # noqa: BLE001 - 传输失败转为回合终态
                    # TransportClosed、EOF、reader 异常都保留类型和原文。
                    logger.error("Codex transport notification failed: %s", exc)
                    yield EngineEvent(
                        conversation_id=request.conversation_id,
                        task_id=request.task_id,
                        engine_turn_id=turn_id,
                        sequence=0,
                        type=EngineEventType.TURN_FAILED,
                        payload={
                            "error": f"{type(exc).__name__}: {exc}",
                            "original_error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                    return
                quiet_seconds = 0.0
                try:
                    event = codec.map_notification(notification, binding)
                except Exception as exc:  # noqa: BLE001 - 协议错误转为失败终态
                    logger.error("Codex protocol error: %s", exc)
                    yield EngineEvent(
                        conversation_id=request.conversation_id,
                        task_id=request.task_id,
                        engine_turn_id=turn_id,
                        sequence=0,
                        type=EngineEventType.TURN_FAILED,
                        payload={
                            "error": f"Codex protocol error: {exc}",
                            "original_error": f"{type(exc).__name__}: {exc}",
                        },
                    )
                    return
                if event is None:
                    continue
                yield event
                if event.type in (EngineEventType.TURN_COMPLETED, EngineEventType.TURN_FAILED):
                    return
        except asyncio.CancelledError:
            # M6.1：对话流取消时也要让 app-server 侧回合结束；interrupt 失败
            # 保留原始取消语义，不能把真实失败改写成成功。
            try:
                await self.cancel_turn(session_ref, turn_id)
            except Exception as exc:  # noqa: BLE001 - 取消收尾失败仅记录
                logger.error("Codex turn cancel failed after cancellation: %s", exc)
            raise

    def _emit_no_progress_warning(self, quiet_seconds: float, turn_id: str) -> None:
        """V0.3.8 T4（契约 §14.6）：回合无进展结构化告警。

        app-server 静默重试（模型供给误配、网络停摆）期间客户端此前零感知；
        告警不终止回合，只把停滞暴露给客户端与服务端日志，最终仍由
        idle_timeout 携带底层原因收尾。
        """
        logger.warning(
            "Codex turn no progress: turn=%s quiet=%.1fs", turn_id, quiet_seconds
        )
        if self.diagnostic_callback is None:
            return
        self.diagnostic_callback(
            {
                "source": "codex-app-server",
                "code": "engine_no_progress",
                "message": (
                    f"Codex app-server 已 {int(quiet_seconds)}s 未产生任何事件，"
                    "回合可能停滞（模型/网络/等待裁决）；超过 "
                    f"{int(self.idle_timeout)}s 将按空闲超时中断并附底层诊断"
                ),
                "detail": {
                    "elapsed_s": round(quiet_seconds, 1),
                    "engine_turn_id": turn_id,
                },
            }
        )

    async def cancel_turn(self, session_ref: EngineSessionRef, turn_id: str) -> None:
        await self.transport.request(
            "turn/interrupt",
            {"threadId": self._decode_ref(session_ref), "turnId": turn_id},
        )

    async def amend_turn(
        self,
        session_ref: EngineSessionRef,
        engine_turn_id: str,
        amendment: TaskAmendment,
    ) -> None:
        amendment_text = json.dumps(
            {
                "type": "TaskAmendment",
                "amendment_id": amendment.amendment_id,
                "target_task_id": amendment.target_task_id,
                "revision": amendment.revision,
                "instructions": amendment.instructions,
                "origin": amendment.origin,
            },
            ensure_ascii=False,
        )
        await self.transport.request(
            "turn/steer",
            {
                "threadId": self._decode_ref(session_ref),
                "expectedTurnId": engine_turn_id,
                "input": [{"type": "text", "text": amendment_text}],
            },
        )

    async def resolve_approval(
        self,
        session_ref: EngineSessionRef,
        approval_id: str,
        decision: ApprovalDecision,
    ) -> None:
        """O3.1：回复 app-server 挂起的审批请求（requestApproval）。

        ``approval_id`` 是服务端请求的 JSON-RPC id（codec 映射时写入
        APPROVAL_REQUESTED 事件的 payload），此处按 id 直接回复 result。
        决策映射（B1 联调可调）：
        - ALLOW / ALLOW_FOR_CONVERSATION → "accept"
          （“本对话内允许”由应用层会话缓存实现，不依赖原生 acceptForSession，
          保证 O1.5 的敏感路径/高风险收紧规则始终生效）；
        - DENY → "decline"（引擎继续 turn，把拒绝反馈给模型）。
        """
        del session_ref
        native = {
            ApprovalDecision.ALLOW: "accept",
            ApprovalDecision.ALLOW_FOR_CONVERSATION: "accept",
            ApprovalDecision.DENY: "decline",
        }[decision]
        await self.transport.respond(int(approval_id), {"decision": native})
