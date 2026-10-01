import pytest

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
from tests.fakes import ScriptedReviewer, unexpected_decision


def _shell(command: str) -> PendingOperation:
    return PendingOperation(tool_kind="shell", command=command)


def _file_write(path: str) -> PendingOperation:
    return PendingOperation(tool_kind="file_write", paths=[path])


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
        _shell("pytest"),
        requested_event=requested_event(),
        context=[],
        request_decision=unexpected_decision,
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
        _shell("pytest"),
        requested_event=requested_event(),
        context=[],
        request_decision=decide,
    )

    assert outcome.decision == ApprovalDecision.ALLOW
    assert len(calls) == 1
    op, approval_id, reason = calls[0]
    assert op.command == "pytest"
    # approval_id 取自引擎的审批请求
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
@pytest.mark.parametrize(
    ("operations", "asked"),
    [
        # shell 签名取前两个词元；命中高风险规则的命令不写缓存
        (
            [
                _shell("git status"),
                _shell("git status"),
                _shell("git push --force origin main"),
                _shell("git push --force origin main"),
            ],
            [0, 2, 3],
        ),
        # file 类签名包含父目录
        (
            [
                _file_write("proj/src/a.py"),
                _file_write("proj/src/b.py"),
                _file_write("proj/other/c.py"),
            ],
            [0, 2],
        ),
        # 敏感路径不写缓存
        ([_file_write("C:/proj/.env"), _file_write("C:/proj/.env")], [0, 1]),
    ],
    ids=["shell", "file-parent-dir", "sensitive-path"],
)
async def test_allow_for_conversation_caches_by_operation_signature(
    operations: list[PendingOperation], asked: list[int]
) -> None:
    manager = ApprovalManager(
        mode=ApprovalMode.REQUEST_APPROVAL,
        rules=default_risk_rules(),
    )
    asked_ids: list[str] = []

    async def allow_for_conversation(op, approval_id: str, reason: str) -> ApprovalDecision:
        asked_ids.append(approval_id)
        return ApprovalDecision.ALLOW_FOR_CONVERSATION

    for index, op in enumerate(operations):
        outcome = await manager.adjudicate(
            op,
            requested_event=requested_event(approval_id=str(index)),
            context=[],
            request_decision=allow_for_conversation,
        )
        assert outcome.decision == ApprovalDecision.ALLOW_FOR_CONVERSATION
        # 命中缓存时直接放行，不产生 approval.resolved
        assert len(outcome.events) == (1 if index in asked else 0)
    assert asked_ids == [str(index) for index in asked]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "op",
    [_shell("pytest"), _file_write("proj/src/a.py")],
    ids=["shell", "file-write"],
)
async def test_review_low_risk_allows_without_reviewer(op: PendingOperation) -> None:
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
    )
    outcome = await manager.adjudicate(
        op,
        requested_event=requested_event(),
        context=[],
        request_decision=unexpected_decision,
    )
    assert outcome.decision == ApprovalDecision.ALLOW
    assert outcome.events == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "decision", "resolution_reason"),
    [
        (
            ReviewerVerdict(allow=False, reason="无法确认", suggestion="补充路径"),
            ApprovalDecision.DENY,
            "无法确认",
        ),
        (ReviewerVerdict(allow=True), ApprovalDecision.ALLOW, "审查通过"),
    ],
)
async def test_review_operation_without_command_or_paths_goes_to_reviewer(
    verdict: ReviewerVerdict, decision: ApprovalDecision, resolution_reason: str
) -> None:
    # 不带命令与路径的操作无法判断风险，交审查智能体裁决
    reviewer = ScriptedReviewer([verdict])
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
        reviewer=reviewer,
    )
    outcome = await manager.adjudicate(
        PendingOperation(tool_kind="file_write", summary="工具操作"),
        requested_event=requested_event(),
        context=[],
        request_decision=unexpected_decision,
    )
    assert len(reviewer.requests) == 1
    assert outcome.decision == decision
    assert outcome.events[0].payload["resolution_reason"] == resolution_reason


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
        _shell("rm -rf build"),
        requested_event=requested_event(command="rm -rf build", approval_id="7"),
        context=[],
        request_decision=unexpected_decision,
    )
    assert outcome.decision == ApprovalDecision.DENY
    assert len(reviewer.requests) == 1
    resolved = [e for e in outcome.events if e.type == "approval.resolved"]
    assert len(resolved) == 1
    payload = resolved[0].payload
    assert payload["approval_id"] == "7"
    assert payload["decision"] == "deny"
    assert payload["actor"] == "reviewer"
    assert payload["resolution_reason"] == "危险"
    assert payload["suggestion"] == "用 shutil 替代"


@pytest.mark.asyncio
async def test_review_high_risk_without_reviewer_denies() -> None:
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
    )
    outcome = await manager.adjudicate(
        _shell("rm -rf build"),
        requested_event=requested_event(command="rm -rf build"),
        context=[],
        request_decision=unexpected_decision,
    )
    assert outcome.decision == ApprovalDecision.DENY
    resolved = [e for e in outcome.events if e.type == "approval.resolved"]
    assert resolved[0].payload["resolution_reason"] == "未配置审查智能体"
