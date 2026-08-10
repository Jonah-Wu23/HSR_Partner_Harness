import pytest

from pair_harness.adapters.reviewer import ScriptedReviewer
from pair_harness.core.contracts import PendingOperation, ReviewerVerdict
from pair_harness.core.risk_rules import default_risk_rules


@pytest.mark.asyncio
async def test_scripted_reviewer_returns_verdicts_in_order() -> None:
    reviewer = ScriptedReviewer(
        [
            ReviewerVerdict(allow=True),
            ReviewerVerdict(allow=False, reason="危险", suggestion="换个方式"),
        ]
    )
    op = PendingOperation(tool_kind="shell", command="rm -rf /", summary="删除")
    v1 = await reviewer.review(op, [])
    assert v1.allow is True
    v2 = await reviewer.review(op, [])
    assert v2.allow is False
    assert v2.reason == "危险"
    assert v2.suggestion == "换个方式"


@pytest.mark.asyncio
async def test_default_reviewer_allows_when_no_verdicts_configured() -> None:
    reviewer = ScriptedReviewer()
    op = PendingOperation(tool_kind="shell", command="ls", summary="列出")
    verdict = await reviewer.review(op, [])
    assert verdict.allow is True


@pytest.mark.asyncio
async def test_deny_verdict_requires_reason_and_suggestion() -> None:
    rules = default_risk_rules()
    reviewer = ScriptedReviewer([ReviewerVerdict(allow=False, reason="", suggestion="")])
    op = PendingOperation(tool_kind="shell", command="rm x", summary="删除")
    with pytest.raises(AssertionError):
        await reviewer.review(op, [])
