from __future__ import annotations

import logging
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
from .ports import Reviewer
from .risk_rules import RiskRules, match_high_risk

logger = logging.getLogger(__name__)


@dataclass
class GateOutcome:
    """一次审批裁决的结果与随之产生的 ``approval.resolved`` 事件。"""

    decision: ApprovalDecision
    events: tuple[EngineEvent, ...] = ()


class ApprovalManager:
    """单个聊天的审批管理器，支持三种审批模式。"""

    def __init__(
        self,
        mode: ApprovalMode,
        rules: RiskRules,
        reviewer: Reviewer | None = None,
        on_review: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.mode = mode
        self.rules = rules
        self.reviewer = reviewer
        self.on_review = on_review
        self._session_allow: set[str] = set()

    def _signature(self, op: PendingOperation) -> str:
        """操作签名，用于“本对话内允许”缓存。

        - shell 至少取命令与子命令两个词元：允许过 ``git status`` 后，
          ``git push --force`` 不得同对话内直接放行；
        - file 类签名纳入父目录维度：同目录下同类文件共享签名，
          不同目录不共享；
        - patch 统一为 ``patch``。
        命中敏感路径或高风险规则的操作不写入缓存（见 :meth:`adjudicate`）。
        """
        if op.tool_kind == "shell" and op.command:
            words = op.command.split()
            return " ".join(words[:2]) if len(words) >= 2 else words[0]
        if op.tool_kind == "patch":
            return "patch"
        parent = PurePath(op.paths[0]).parent.as_posix() if op.paths else ""
        return f"{op.tool_kind}:{parent}"

    async def _review_op(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict:
        """调用审查智能体并发出 review.started/completed/failed。

        审查提示只在真正调用审查智能体时出现；低风险直接放行、空闲状态
        与普通回复不触发本方法。审查调用失败时记录原始异常并否决操作，
        否决理由携带原始错误文本。
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
            verdict = await self.reviewer.review(op, context)
        except Exception as exc:  # noqa: BLE001 - 审查失败按否决处理（fail-closed）
            logger.exception("审查智能体调用失败：%s", op.summary)
            reason = f"审查智能体调用失败：{str(exc) or type(exc).__name__}"
            if self.on_review is not None:
                self.on_review("review.failed", {"reason": reason})
            return ReviewerVerdict(allow=False, reason=reason)
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

        既无 command 也无 paths 的操作无法区分创建与删除，不得在 REVIEW
        模式下按低风险放行。
        """
        return bool(op.command or op.paths)

    async def adjudicate(
        self,
        op: PendingOperation,
        *,
        requested_event: EngineEvent,
        request_decision: Callable[
            [PendingOperation, str, str], Awaitable[ApprovalDecision]
        ],
        context: list[Message],
    ) -> GateOutcome:
        """裁决引擎在工具执行前挂起的审批请求。

        ``approval_id`` 取自 ``requested_event.payload``；裁决结果由调用方经
        ``CodingEngine.resolve_approval`` 回复引擎。返回的
        ``GateOutcome.events`` 只含 ``approval.resolved``，请求事件由引擎
        适配器产生。``request_decision`` 在“请求批准”模式下询问用户，
        对应编排器的 approval_callback。

        - ``FULL_AUTO``：直接放行，不产生事件；
        - ``REQUEST_APPROVAL``：命中“本对话内允许”缓存时放行，否则询问用户；
        - ``REVIEW``：低风险且信息充分时放行，其余连同近期用户消息交审查
          智能体裁决。
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
            decision = await request_decision(op, approval_id, reason)
            if (
                decision == ApprovalDecision.ALLOW_FOR_CONVERSATION
                and match_high_risk(op, self.rules) is None
            ):
                # 命中敏感路径或高风险规则的操作永不写入会话缓存，
                # 同对话内再次执行时仍要求审批。
                self._session_allow.add(self._signature(op))
            resolved = self._approval_resolved_event(
                requested_event,
                decision,
                actor="user",
                request_reason=reason,
                resolution_reason=None,
            )
            return GateOutcome(decision=decision, events=(resolved,))

        if match_high_risk(op, self.rules) is None and self._has_enough_info(op):
            return GateOutcome(decision=ApprovalDecision.ALLOW)
        suggestion = ""
        if self.reviewer is None:
            decision, resolution = ApprovalDecision.DENY, "未配置审查智能体"
        else:
            verdict = await self._review_op(op, context)
            if verdict.allow:
                decision, resolution = ApprovalDecision.ALLOW, "审查通过"
            else:
                decision, resolution = ApprovalDecision.DENY, verdict.reason
                suggestion = verdict.suggestion
        resolved = self._approval_resolved_event(
            requested_event,
            decision,
            actor="reviewer",
            request_reason=reason,
            resolution_reason=resolution,
            suggestion=suggestion,
        )
        return GateOutcome(decision=decision, events=(resolved,))

    def clear_session_cache(self) -> None:
        """聊天结束或切换时清空“本对话内允许”缓存。

        由编排器的 :meth:`close_conversation` 调用。
        """
        self._session_allow.clear()

    @staticmethod
    def _approval_resolved_event(
        event: EngineEvent,
        decision: ApprovalDecision,
        *,
        actor: str,
        request_reason: str,
        resolution_reason: str | None,
        suggestion: str = "",
    ) -> EngineEvent:
        """生成 approval.resolved 事件。

        ``request_reason`` 是触发审批的理由；``resolution_reason`` 是审查
        智能体给出的结论，用户裁决时为 None。
        """
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
                "request_reason": request_reason,
                "resolution_reason": resolution_reason,
                "suggestion": suggestion,
            },
        )
