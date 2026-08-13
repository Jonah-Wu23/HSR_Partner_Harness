from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

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


class CodexAppServerEngine(CodingEngine):
    engine_type = "codex-app-server"
    native_preexecution_approval = True

    def __init__(
        self,
        transport: JsonlProcessTransport,
        *,
        model: str = "gpt-5.6-sol",
        reasoning_effort: str = "medium",
    ) -> None:
        self.transport = transport
        self.model = model
        self.reasoning_effort = reasoning_effort
        # B1 联调：app-server 协议要求连接后先发 initialize 握手，
        # 否则 thread/start 返回 {"code": -32600, "message": "Not initialized"}。
        # 每个引擎实例（每次连接）只需一次。
        self._initialized = False

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
        if not self._initialized or not was_running:
            await self.transport.request(
                "initialize",
                {"clientInfo": {"name": "pair-harness", "version": "0.2.0"}},
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
        while True:
            notification = await self.transport.next_notification()
            event = codec.map_notification(notification, binding)
            if event is None:
                continue
            yield event
            if event.type in (EngineEventType.TURN_COMPLETED, EngineEventType.TURN_FAILED):
                return

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
