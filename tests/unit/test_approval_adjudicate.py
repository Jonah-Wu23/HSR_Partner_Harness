"""O3.1：ApprovalManager.adjudicate —— 引擎侧挂起请求的裁决。

与 gate() 的差异：approval_id 来自引擎（requestApproval 请求 id），
裁决结果由调用方经 resolve_approval 转发，adjudicate 只合成 resolved 事件。
"""

import pytest

from pair_harness.adapters.reviewer import ScriptedReviewer
from pair_harness.core.approval import ApprovalManager
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    EngineEvent,
    EngineEventType,
    PendingOperation,
    ReviewerVerdict,
)
from pair_harness.core.risk_rules import default_risk_rules


def requested_event(command: str = "pytest", approval_id: str = "100") -> EngineEvent:
    return EngineEvent(
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
        sequence=5,
        type=EngineEventType.APPROVAL_REQUESTED,
        tool_call_id="tool-1",
        payload={
            "approval_id": approval_id,
            "request_id": int(approval_id),
            "reason": "需要用户审批",
            "tool_kind": "shell",
            "command": command,
            "paths": [],
            "summary": command,
        },
    )


@pytest.mark.asyncio
async def test_full_auto_returns_allow_without_events() -> None:
    manager = ApprovalManager(
        mode=ApprovalMode.FULL_AUTO,
        rules=default_risk_rules(),
    )
    outcome = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="pytest"),
        requested_event=requested_event(),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
    )
    assert outcome.decision == ApprovalDecision.ALLOW
    assert outcome.events == ()


@pytest.mark.asyncio
async def test_request_approval_asks_decision_and_synthesizes_resolved() -> None:
    manager = ApprovalManager(
        mode=ApprovalMode.REQUEST_APPROVAL,
        rules=default_risk_rules(),
    )
    calls = []

    async def decide(op, approval_id: str, reason: str) -> ApprovalDecision:
        calls.append((op, approval_id, reason))
        return ApprovalDecision.ALLOW

    outcome = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="pytest"),
        requested_event=requested_event(),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
        request_decision=decide,
    )

    assert outcome.decision == ApprovalDecision.ALLOW
    assert len(calls) == 1
    op, approval_id, reason = calls[0]
    assert op.command == "pytest"
    # approval_id 贯通自引擎请求，而非本地新生成
    assert approval_id == "100"
    assert reason == "需要用户审批"
    resolved = [e for e in outcome.events if e.type == "approval.resolved"]
    assert len(resolved) == 1
    assert resolved[0].payload["approval_id"] == "100"
    assert resolved[0].payload["decision"] == "allow"
    assert resolved[0].payload["actor"] == "user"
    # resolved 事件序号紧随请求事件
    assert resolved[0].sequence == 6


@pytest.mark.asyncio
async def test_request_approval_without_callback_denies() -> None:
    manager = ApprovalManager(
        mode=ApprovalMode.REQUEST_APPROVAL,
        rules=default_risk_rules(),
    )
    outcome = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="pytest"),
        requested_event=requested_event(),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
    )
    assert outcome.decision == ApprovalDecision.DENY
    resolved = [e for e in outcome.events if e.type == "approval.resolved"]
    assert resolved[0].payload["reason"] == "未配置审批回调"


@pytest.mark.asyncio
async def test_allow_for_conversation_writes_cache_then_hits() -> None:
    """“本对话内允许”在原生路径同样写会话缓存，同签名后续请求直接放行。"""
    manager = ApprovalManager(
        mode=ApprovalMode.REQUEST_APPROVAL,
        rules=default_risk_rules(),
    )
    calls = []

    async def allow_once(op, approval_id: str, reason: str) -> ApprovalDecision:
        calls.append(approval_id)
        return ApprovalDecision.ALLOW_FOR_CONVERSATION

    first = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="git status"),
        requested_event=requested_event(command="git status", approval_id="1"),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
        request_decision=allow_once,
    )
    assert first.decision == ApprovalDecision.ALLOW_FOR_CONVERSATION

    second = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="git status"),
        requested_event=requested_event(command="git status", approval_id="2"),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
        request_decision=allow_once,
    )
    assert second.decision == ApprovalDecision.ALLOW_FOR_CONVERSATION
    # 缓存命中：回调只被调用一次
    assert calls == ["1"]


@pytest.mark.asyncio
async def test_high_risk_never_cached_via_adjudicate() -> None:
    """O1.5 收紧规则在原生路径同样生效：高风险操作不写会话缓存。"""
    manager = ApprovalManager(
        mode=ApprovalMode.REQUEST_APPROVAL,
        rules=default_risk_rules(),
    )

    async def allow(op, approval_id: str, reason: str) -> ApprovalDecision:
        return ApprovalDecision.ALLOW_FOR_CONVERSATION

    first = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="git push --force origin main"),
        requested_event=requested_event(command="git push --force origin main", approval_id="1"),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
        request_decision=allow,
    )
    assert first.decision == ApprovalDecision.ALLOW_FOR_CONVERSATION

    # 同签名再次请求仍需裁决（未写缓存）
    second = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="git push --force origin main"),
        requested_event=requested_event(command="git push --force origin main", approval_id="2"),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
        request_decision=allow,
    )
    assert second.decision == ApprovalDecision.ALLOW_FOR_CONVERSATION
    assert len(second.events) == 1  # 仍合成 resolved，说明没有直接命中


@pytest.mark.asyncio
async def test_review_low_risk_allows_without_reviewer() -> None:
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
    )
    outcome = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="pytest"),
        requested_event=requested_event(),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
    )
    assert outcome.decision == ApprovalDecision.ALLOW
    assert outcome.events == ()


@pytest.mark.asyncio
async def test_review_high_risk_calls_reviewer_and_synthesizes_resolved() -> None:
    reviewer = ScriptedReviewer(
        [ReviewerVerdict(allow=False, reason="危险", suggestion="用 shutil 替代")]
    )
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
        reviewer=reviewer,
    )
    outcome = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="rm -rf build"),
        requested_event=requested_event(command="rm -rf build", approval_id="7"),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
    )
    assert outcome.decision == ApprovalDecision.DENY
    assert len(reviewer.requests) == 1
    resolved = [e for e in outcome.events if e.type == "approval.resolved"]
    assert len(resolved) == 1
    payload = resolved[0].payload
    assert payload["approval_id"] == "7"
    assert payload["decision"] == "deny"
    assert payload["actor"] == "reviewer"
    assert payload["reason"] == "危险"
    assert payload["suggestion"] == "用 shutil 替代"


@pytest.mark.asyncio
async def test_review_high_risk_without_reviewer_denies() -> None:
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
    )
    outcome = await manager.adjudicate(
        PendingOperation(tool_kind="shell", command="rm -rf build"),
        requested_event=requested_event(command="rm -rf build"),
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn-1",
    )
    assert outcome.decision == ApprovalDecision.DENY
    resolved = [e for e in outcome.events if e.type == "approval.resolved"]
    assert resolved[0].payload["reason"] == "未配置审查智能体"
