from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.context import ExecutionContext
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    DialogueEvent,
    DialogueRequest,
    Message,
    PendingOperation,
    ProjectRef,
    ReviewerVerdict,
)
from pair_harness.core.orchestrator import ConversationOrchestrator, ConversationOutcome
from pair_harness.core.ports import DialogueModel


def make_context(
    project: ProjectRef,
    *,
    conversation_id: str,
    pair_id: str = "phainon_ancient_machine",
    conversation_mode: Literal["chat", "collaboration"] = "collaboration",
    approval_mode: ApprovalMode = ApprovalMode.REQUEST_APPROVAL,
    assistant_instructions: str = "",
    account_id: str = "default-local",
) -> ExecutionContext:
    """测试用执行上下文；生产路径由 application_service 在提交时解析。"""
    return ExecutionContext(
        account_id=account_id,
        project=project,
        conversation_id=conversation_id,
        pair_id=pair_id,
        conversation_mode=conversation_mode,
        approval_mode=approval_mode,
        assistant_instructions=assistant_instructions,
    )


async def direct_input(
    orchestrator: ConversationOrchestrator,
    *,
    conversation_id: str,
    text: str,
    context: ExecutionContext,
) -> ConversationOutcome:
    """落库一条发给助手的用户消息并处理，等价于桌面提交链路的直发助手回合。"""
    user = await orchestrator.submit_user_message(
        conversation_id=conversation_id,
        text=text,
        target="assistant",
        pair_id=context.pair_id,
    )
    return await orchestrator.process_direct_input(
        conversation_id=conversation_id, user_message=user, context=context
    )


class UnusedJsonModelMixin:
    """测试替身不应调用的标题、摘要与单 JSON 请求接口：调用即失败。"""

    async def generate_title(
        self, *, pair_id: str, context: tuple[Message, ...]
    ) -> str:
        raise AssertionError("本测试不应请求生成标题")

    async def generate_summary(
        self, *, pair_id: str, assistant_prompt: str, context_text: str
    ) -> dict[str, Any]:
        raise AssertionError("本测试不应请求生成摘要")

    async def complete_json(
        self, *, system: str, user: str, max_tokens: int
    ) -> dict[str, Any]:
        raise AssertionError("本测试不应发送单 JSON 请求")


async def unexpected_approval(
    op: PendingOperation,
    approval_id: str,
    reason: str,
    conversation_id: str,
    task_id: str,
) -> ApprovalDecision:
    raise AssertionError(f"本测试不应请求用户审批：{op.summary}")


async def unexpected_decision(
    op: PendingOperation, approval_id: str, reason: str
) -> ApprovalDecision:
    """ApprovalManager.adjudicate 的 request_decision 占位：调用即失败。"""
    raise AssertionError(f"本测试不应请求用户裁决：{op.summary}")


async def allow_approval(
    op: PendingOperation,
    approval_id: str,
    reason: str,
    conversation_id: str,
    task_id: str,
) -> ApprovalDecision:
    return ApprovalDecision.ALLOW


async def deny_approval(
    op: PendingOperation,
    approval_id: str,
    reason: str,
    conversation_id: str,
    task_id: str,
) -> ApprovalDecision:
    return ApprovalDecision.DENY


class FixedDialogueModel(UnusedJsonModelMixin, DialogueModel):
    def __init__(self, *turns: CharacterTurn) -> None:
        self.turns = list(turns)
        self.requests: list[DialogueRequest] = []

    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        self.requests.append(request)
        turn = self.turns.pop(0)
        yield DialogueEvent(type="speech.delta", delta=turn.speech)
        yield DialogueEvent(type="character.final", turn=turn)


class RecordingCodingEngine(ScriptedCodingEngine):
    pass


class ScriptedReviewer:
    """按预先给定的 ReviewerVerdict 列表依次返回的审查替身。"""

    def __init__(self, verdicts: list[ReviewerVerdict] | None = None) -> None:
        self._verdicts = list(verdicts or [])
        self._index = 0
        self.requests: list[tuple[PendingOperation, list[Message]]] = []

    async def review(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict:
        self.requests.append((op, context))
        if self._index >= len(self._verdicts):
            return ReviewerVerdict(allow=True)
        verdict = self._verdicts[self._index]
        self._index += 1
        if not verdict.allow:
            assert verdict.reason, "否决时必须提供理由"
            assert verdict.suggestion, "否决时必须提供调整建议"
        return verdict

