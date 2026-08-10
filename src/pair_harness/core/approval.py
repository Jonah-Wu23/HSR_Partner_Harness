from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .contracts import (
    ApprovalDecision,
    ApprovalMode,
    EngineEvent,
    EngineEventType,
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
    ) -> None:
        self.mode = mode
        self.rules = rules
        self.reviewer = reviewer
        self._session_allow: set[str] = set()
        self._pending: dict[str, PendingOperation] = {}

    def _signature(self, op: PendingOperation) -> str:
        """操作签名，用于“本对话内允许”缓存。"""
        if op.tool_kind == "shell" and op.command:
            return op.command.split()[0]
        if op.tool_kind == "patch":
            return "patch"
        ext = Path(op.paths[0]).suffix if op.paths else ""
        return f"{op.tool_kind}{ext}"

    async def gate(
        self,
        op: PendingOperation,
        *,
        conversation_id: str,
        task_id: str,
        engine_turn_id: str,
        sequence: int,
        tool_call_id: str | None = None,
    ) -> GateOutcome:
        """对单个操作进行门控。

        - ``FULL_AUTO``：直接放行，不产生审批事件。
        - ``REQUEST_APPROVAL``：未缓存时抛出 :class:`ApprovalRequired`。
        - ``REVIEW``：低风险直接放行；高风险交审查智能体裁决，并返回审批事件。
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
        if reason is None:
            return GateOutcome(decision=ApprovalDecision.ALLOW)

        event = self._approval_requested_event(
            op=op,
            approval_id=self._new_approval_id(),
            reason=reason,
            conversation_id=conversation_id,
            task_id=task_id,
            engine_turn_id=engine_turn_id,
            sequence=sequence,
            tool_call_id=tool_call_id,
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
        verdict = await self.reviewer.review(op, [])
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

    def resolve(self, approval_id: str, decision: ApprovalDecision) -> PendingOperation:
        """处理用户或审查智能体的裁决。

        若用户选择“本对话内允许”，则把操作签名写入当前聊天缓存。
        """
        op = self._pending.pop(approval_id, None)
        if op is None:
            raise KeyError(f"unknown approval_id: {approval_id}")
        if decision == ApprovalDecision.ALLOW_FOR_CONVERSATION:
            self._session_allow.add(self._signature(op))
        return op

    def clear_session_cache(self) -> None:
        """当前聊天结束时清空“本对话内允许”缓存。"""
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
                "actor": "user",
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
