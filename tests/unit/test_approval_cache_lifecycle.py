import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    PendingOperation,
    ProjectRef,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel, direct_input, make_context

CONTEXT = make_context(
    ProjectRef(project_id="p", name="p", root_path="C:\\project"),
    conversation_id="c",
    approval_mode=ApprovalMode.REQUEST_APPROVAL,
)


@pytest.mark.asyncio
async def test_close_conversation_invalidates_session_allow_cache() -> None:
    calls: list[str] = []

    async def ask(
        op: PendingOperation,
        approval_id: str,
        reason: str,
        conversation_id: str,
        task_id: str,
    ) -> ApprovalDecision:
        calls.append(approval_id)
        return ApprovalDecision.ALLOW_FOR_CONVERSATION

    orchestrator = ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(
            CharacterTurn(speech="做完了。"),
            CharacterTurn(speech="又做完了。"),
            CharacterTurn(speech="又又做完了。"),
        ),
        coding_engine=ScriptedCodingEngine(),
        approval_callback=ask,
    )

    for text in ("跑演示", "再跑一次"):
        outcome = await direct_input(
            orchestrator, conversation_id="c", text=text, context=CONTEXT
        )
        assert outcome.receipt is not None
        assert outcome.receipt.status == "completed"
    # 第二次执行命中“本对话内允许”缓存，不再询问
    assert len(calls) == 1

    # 没有运行中任务的会话关闭时同时移除审批管理器
    orchestrator.close_conversation("c")
    assert "c" not in orchestrator._approval_managers

    outcome = await direct_input(
        orchestrator, conversation_id="c", text="第三次", context=CONTEXT
    )
    assert outcome.receipt.status == "completed"
    assert len(calls) == 2
