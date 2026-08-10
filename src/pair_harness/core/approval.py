from __future__ import annotations

from dataclasses import dataclass, field
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
    ) -> None:
        self.mode = mode
        self.rules = rules
        self.reviewer = reviewer
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
        verdict = await self.reviewer.review(op, context or [])
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
            # O1.5：命中敏感路径或高风险规则的操作永不写入会话缓存，
            # 保证同对话内再次执行时仍要求审批。
            if match_high_risk(op, self.rules) is None:
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
