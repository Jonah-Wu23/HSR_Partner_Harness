from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePath

from .contracts import (
    ApprovalDecision,
    ApprovalMode,
    EngineEvent,
    EngineEventType,
    Message,
    PendingOperation,
    ReviewerVerdict,
)
from .risk_rules import RiskRules, match_high_risk


class ApprovalRequired(RuntimeError):
    """当前操作需要用户或审查智能体审批。"""

    def __init__(
        self, approval_id: str, op: PendingOperation, event: EngineEvent
    ):
        self.approval_id = approval_id
        self.op = op
        self.event = event
        super().__init__(f"operation requires approval: {approval_id}")


@dataclass
class GateOutcome:
    """审批门控结果。"""

    decision: ApprovalDecision
    events: tuple[EngineEvent, ...] = ()


class ApprovalManager:
    """项目级审批管理器，支持三种审批模式。"""

    def __init__(
        self,
        mode: ApprovalMode,
        rules: RiskRules,
        reviewer: "Reviewer | None" = None,
        on_review: "Callable[[str, dict], None] | None" = None,
    ) -> None:
        self.mode = mode
        self.rules = rules
        self.reviewer = reviewer
        self.on_review = on_review
        self._session_allow: set[str] = set()
        self._pending: dict[str, PendingOperation] = {}

    def _signature(self, op: PendingOperation) -> str:
        """操作签名，用于“本对话内允许”缓存。

        O1.5 收紧规则（依据见优化计划 §O1.5）：
        - shell 至少取命令与子命令两个词元：允许过 ``git status`` 后，
          ``git push --force`` 不得同对话内直接放行；
        - file 类签名纳入父目录维度：同目录下同类文件共享签名，
          不同目录不共享；
        - patch 统一为 ``patch``。
        命中敏感路径或高风险规则的操作不写入缓存（见 :meth:`resolve`）。
        """
        if op.tool_kind == "shell" and op.command:
            words = op.command.split()
            return " ".join(words[:2]) if len(words) >= 2 else words[0]
        if op.tool_kind == "patch":
            return "patch"
        parent = PurePath(op.paths[0]).parent.as_posix() if op.paths else ""
        return f"{op.tool_kind}:{parent}"

    async def gate(
        self,
        op: PendingOperation,
        *,
        conversation_id: str,
        task_id: str,
        engine_turn_id: str,
        sequence: int,
        tool_call_id: str | None = None,
        context: list[Message] | None = None,
    ) -> GateOutcome:
        """对单个操作进行门控。

        - ``FULL_AUTO``：直接放行，不产生审批事件。
        - ``REQUEST_APPROVAL``：未缓存时抛出 :class:`ApprovalRequired`。
        - ``REVIEW``：低风险直接放行；高风险连同近期上下文交审查智能体裁决，
          并返回审批事件。
        """
        if self.mode == ApprovalMode.FULL_AUTO:
            return GateOutcome(decision=ApprovalDecision.ALLOW)

        if self.mode == ApprovalMode.REQUEST_APPROVAL:
            sig = self._signature(op)
            if sig in self._session_allow:
                return GateOutcome(decision=ApprovalDecision.ALLOW_FOR_CONVERSATION)
            approval_id = self._new_approval_id()
            self._pending[approval_id] = op
            event = self._approval_requested_event(
                op=op,
                approval_id=approval_id,
                reason=op.summary or "需要用户审批",
                conversation_id=conversation_id,
                task_id=task_id,
                engine_turn_id=engine_turn_id,
                sequence=sequence,
                tool_call_id=tool_call_id,
            )
            raise ApprovalRequired(approval_id, op, event)

        # REVIEW 模式
        reason = match_high_risk(op, self.rules)
        if reason is None and self._has_enough_info(op):
            return GateOutcome(decision=ApprovalDecision.ALLOW)
        if reason is None:
            # B1 联调：app-server 0.147.0 的 fileChange 审批请求不带路径
            # （grantRoot/reason 均为 None），映射出的操作信息不足无法判定
            # 风险。不得按低风险放行（删除会绕过审查），转审查智能体结合
            # 近期上下文判断用户意图。
            reason = "信息不足：无法确认操作目标"

        event = self._approval_requested_event(
            op=op,
            approval_id=self._new_approval_id(),
            reason=reason,
            conversation_id=conversation_id,
            task_id=task_id,
            engine_turn_id=engine_turn_id,
            sequence=sequence,
            tool_call_id=tool_call_id,
            # 计划 A3：审查模式下的裁决由审查智能体做出，actor 记为 reviewer
            actor="reviewer",
        )
        if self.reviewer is None:
            resolved = self._approval_resolved_event(
                event=event,
                decision=ApprovalDecision.DENY,
                actor="reviewer",
                reason="未配置审查智能体",
            )
            return GateOutcome(
                decision=ApprovalDecision.DENY,
                events=(event, resolved),
            )
        # 计划 A3：把操作连同近期上下文交给审查智能体
        verdict = await self._review_op(op, context or [])
        if verdict.allow:
            resolved = self._approval_resolved_event(
                event=event,
                decision=ApprovalDecision.ALLOW,
                actor="reviewer",
                reason="审查通过",
            )
            return GateOutcome(decision=ApprovalDecision.ALLOW, events=(event, resolved))
        resolved = self._approval_resolved_event(
            event=event,
            decision=ApprovalDecision.DENY,
            actor="reviewer",
            reason=verdict.reason,
            suggestion=verdict.suggestion,
        )
        return GateOutcome(decision=ApprovalDecision.DENY, events=(event, resolved))

    async def _review_op(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict:
        """V0.2：调用审查智能体并发出 review.started/completed/failed。

        审查提示只在真正调用审查智能体时出现；低风险直接放行、空闲状态
        与普通回复不触发本方法（问题 14）。审查异常按安全默认（否决）
        处理并发出 review.failed。
        """
        if self.on_review is not None:
            self.on_review(
                "review.started",
                {
                    "summary": op.summary,
                    "tool_kind": op.tool_kind,
                    "command": op.command,
                    "paths": list(op.paths),
                },
            )
        try:
            verdict = await self.reviewer.review(op, context or [])
        except Exception as exc:  # noqa: BLE001 - 审查异常降级为安全否决
            if self.on_review is not None:
                self.on_review("review.failed", {"reason": str(exc)})
            return ReviewerVerdict(allow=False, reason="审查智能体异常", suggestion="请重试")
        if self.on_review is not None:
            self.on_review(
                "review.completed",
                {
                    "allow": verdict.allow,
                    "reason": verdict.reason,
                    "suggestion": verdict.suggestion,
                },
            )
        return verdict

    @staticmethod
    def _has_enough_info(op: PendingOperation) -> bool:
        """操作是否携带足够判定风险的信息。

        B1 联调：真实 app-server 的 fileChange 审批请求不携带路径
        （grantRoot/reason 均为 None），映射出的操作既无 command 也无
        paths——这类操作无法区分"创建文件"与"删除文件"，不得在
        REVIEW 模式下按低风险放行。
        """
        return bool(op.command or op.paths)

    async def adjudicate(
        self,
        op: PendingOperation,
        *,
        requested_event: EngineEvent,
        conversation_id: str,
        task_id: str,
        engine_turn_id: str,
        tool_call_id: str | None = None,
        context: list[Message] | None = None,
        request_decision: Callable[
            [PendingOperation, str, str], Awaitable[ApprovalDecision]
        ]
        | None = None,
    ) -> GateOutcome:
        """O3.1：裁决引擎侧挂起的原生审批请求。

        与 :meth:`gate` 的差异：
        - ``approval_id`` 来自 app-server（requestApproval 请求 id），
          由调用方从 ``requested_event.payload`` 读取，不再本地生成；
        - 裁决结果由调用方经 ``CodingEngine.resolve_approval`` 回复引擎，
          本方法不直接接触引擎；
        - 返回的 ``GateOutcome.events`` 只含 ``approval.resolved``
          （请求事件由 codec 映射产生，不重复合成）。
        ``request_decision`` 供“请求批准”模式询问用户（等价于编排器的
        approval_callback）；未提供时按否决处理（与 gate 路径一致）。
        """
        approval_id = str(requested_event.payload.get("approval_id") or "")
        reason = str(
            requested_event.payload.get("reason") or op.summary or "需要用户审批"
        )

        if self.mode == ApprovalMode.FULL_AUTO:
            return GateOutcome(decision=ApprovalDecision.ALLOW)

        if self.mode == ApprovalMode.REQUEST_APPROVAL:
            if self._signature(op) in self._session_allow:
                return GateOutcome(decision=ApprovalDecision.ALLOW_FOR_CONVERSATION)
            if request_decision is None:
                decision = ApprovalDecision.DENY
                resolved_reason = "未配置审批回调"
            else:
                decision = await request_decision(op, approval_id, reason)
                resolved_reason = reason
            if (
                decision == ApprovalDecision.ALLOW_FOR_CONVERSATION
                and match_high_risk(op, self.rules) is None
            ):
                # O1.5：命中敏感路径或高风险规则的操作永不写入会话缓存
                self._session_allow.add(self._signature(op))
            resolved = self._approval_resolved_event(
                requested_event,
                decision,
                actor="user",
                reason=resolved_reason,
            )
            return GateOutcome(decision=decision, events=(resolved,))

        # REVIEW 模式
        risk_reason = match_high_risk(op, self.rules)
        if risk_reason is None and self._has_enough_info(op):
            return GateOutcome(decision=ApprovalDecision.ALLOW)
        if risk_reason is None:
            # B1 联调：信息不足的操作（如 fileChange 审批请求无路径）不得
            # 按低风险放行，转审查智能体结合近期上下文判断（见 gate）。
            risk_reason = "信息不足：无法确认操作目标"
        if self.reviewer is None:
            resolved = self._approval_resolved_event(
                requested_event,
                ApprovalDecision.DENY,
                actor="reviewer",
                reason="未配置审查智能体",
            )
            return GateOutcome(decision=ApprovalDecision.DENY, events=(resolved,))
        verdict = await self._review_op(op, context or [])
        if verdict.allow:
            resolved = self._approval_resolved_event(
                requested_event,
                ApprovalDecision.ALLOW,
                actor="reviewer",
                reason="审查通过",
            )
            return GateOutcome(decision=ApprovalDecision.ALLOW, events=(resolved,))
        resolved = self._approval_resolved_event(
            requested_event,
            ApprovalDecision.DENY,
            actor="reviewer",
            reason=verdict.reason,
            suggestion=verdict.suggestion,
        )
        return GateOutcome(decision=ApprovalDecision.DENY, events=(resolved,))

    def resolve(self, approval_id: str, decision: ApprovalDecision) -> PendingOperation:
        """处理用户或审查智能体的裁决。

        若用户选择“本对话内允许”，则把操作签名写入当前聊天缓存。
        """
        op = self._pending.pop(approval_id, None)
        if op is None:
            raise KeyError(f"unknown approval_id: {approval_id}")
        if decision == ApprovalDecision.ALLOW_FOR_CONVERSATION:
            # O1.5：命中敏感路径或高风险规则的操作永不写入会话缓存，
            # 保证同对话内再次执行时仍要求审批。
            if match_high_risk(op, self.rules) is None:
                self._session_allow.add(self._signature(op))
        return op

    def clear_session_cache(self) -> None:
        """聊天结束/切换时清空“本对话内允许”缓存。

        O4.2：由编排器的 :meth:`close_conversation` 在聊天结束/切换
        钩子处调用（此前无人调用，缓存没有生命周期）。只清理
        ALLOW_FOR_CONVERSATION 缓存，不影响已挂起的审批请求
        （``_pending`` 由裁决流程自行消费）。
        """
        self._session_allow.clear()

    @staticmethod
    def _new_approval_id() -> str:
        from uuid import uuid4

        return str(uuid4())

    @staticmethod
    def _approval_requested_event(
        op: PendingOperation,
        approval_id: str,
        reason: str,
        *,
        conversation_id: str,
        task_id: str,
        engine_turn_id: str,
        sequence: int,
        tool_call_id: str | None,
        actor: str = "user",
    ) -> EngineEvent:
        return EngineEvent(
            conversation_id=conversation_id,
            task_id=task_id,
            engine_turn_id=engine_turn_id,
            sequence=sequence,
            type=EngineEventType.APPROVAL_REQUESTED,
            tool_call_id=tool_call_id,
            payload={
                "approval_id": approval_id,
                "summary": op.summary,
                "reason": reason,
                "actor": actor,
                "options": [
                    ApprovalDecision.ALLOW.value,
                    ApprovalDecision.ALLOW_FOR_CONVERSATION.value,
                    ApprovalDecision.DENY.value,
                ],
            },
        )

    @staticmethod
    def _approval_resolved_event(
        event: EngineEvent,
        decision: ApprovalDecision,
        *,
        actor: str,
        reason: str,
        suggestion: str = "",
    ) -> EngineEvent:
        return EngineEvent(
            conversation_id=event.conversation_id,
            task_id=event.task_id,
            engine_turn_id=event.engine_turn_id,
            sequence=event.sequence + 1,
            type=EngineEventType.APPROVAL_RESOLVED,
            tool_call_id=event.tool_call_id,
            payload={
                "approval_id": event.payload.get("approval_id"),
                "decision": decision.value,
                "actor": actor,
                "reason": reason,
                "suggestion": suggestion,
            },
        )
