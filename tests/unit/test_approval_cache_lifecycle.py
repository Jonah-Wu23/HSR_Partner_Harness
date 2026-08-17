"""O4.2：审批缓存生命周期 —— close_conversation 后“本对话内允许”失效。

场景：同一会话内同签名操作第二次执行直接放行（缓存命中、不再询问
用户）；close_conversation（聊天结束/切换钩子）后缓存失效，且会话的
ApprovalManager 不再常驻——再次执行重新询问，且管理器为新建实例。
"""

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    PendingOperation,
    ProjectRef,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel


def _make_orchestrator(
    engine: ScriptedCodingEngine, callback
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(
            CharacterTurn(speech="做完了。"),
            CharacterTurn(speech="又做完了。"),
            CharacterTurn(speech="又又做完了。"),
        ),
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        approval_callback=callback,
    )


@pytest.mark.asyncio
async def test_close_conversation_invalidates_session_allow_cache() -> None:
    """切换/关闭聊天后，同签名操作必须重新询问审批。"""
    calls: list[str] = []

    async def ask(
        op: PendingOperation,
        approval_id: str,
        reason: str,
        conversation_id: str = "",
        task_id: str = "",
    ) -> ApprovalDecision:
        calls.append(approval_id)
        return ApprovalDecision.ALLOW_FOR_CONVERSATION

    engine = ScriptedCodingEngine()
    orchestrator = _make_orchestrator(engine, ask)

    # 第一次执行：需要审批，允许“本对话内”
    outcome = await orchestrator.handle_direct_input(
        conversation_id="c", text="跑演示"
    )
    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    assert len(calls) == 1
    # 缓存已写入（ALLOW_FOR_CONVERSATION 且未命中高风险规则）
    assert orchestrator._approval_managers["c"]._session_allow

    # 第二次执行：同签名操作缓存命中，不再询问
    outcome = await orchestrator.handle_direct_input(
        conversation_id="c", text="再跑一次"
    )
    assert outcome.receipt.status == "completed"
    assert len(calls) == 1  # 缓存命中，未再询问

    # 聊天结束/切换钩子：清空缓存并移除常驻管理器
    orchestrator.close_conversation("c")
    assert "c" not in orchestrator._approval_managers

    # 第三次执行：缓存失效，重新询问；管理器为新建实例
    outcome = await orchestrator.handle_direct_input(
        conversation_id="c", text="第三次"
    )
    assert outcome.receipt.status == "completed"
    assert len(calls) == 2
    assert orchestrator._approval_managers["c"]._session_allow


@pytest.mark.asyncio
async def test_close_conversation_unknown_id_is_noop() -> None:
    """未打开过的会话关闭是无害空操作，不影响其他会话缓存。"""
    calls: list[str] = []

    async def ask(
        op: PendingOperation,
        approval_id: str,
        reason: str,
        conversation_id: str = "",
        task_id: str = "",
    ) -> ApprovalDecision:
        calls.append(approval_id)
        return ApprovalDecision.ALLOW_FOR_CONVERSATION

    engine = ScriptedCodingEngine()
    orchestrator = _make_orchestrator(engine, ask)

    await orchestrator.handle_direct_input(conversation_id="c", text="跑演示")
    assert orchestrator._approval_managers["c"]._session_allow

    orchestrator.close_conversation("other")
    assert "c" in orchestrator._approval_managers
    assert orchestrator._approval_managers["c"]._session_allow
    assert len(calls) == 1
