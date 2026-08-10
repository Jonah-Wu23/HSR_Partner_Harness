import json
from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.reviewer import DialogueModelReviewer, ScriptedReviewer
from pair_harness.core.contracts import (
    CharacterTurn,
    DialogueEvent,
    DialogueRequest,
    PendingOperation,
    ReviewerVerdict,
)
from pair_harness.core.risk_rules import default_risk_rules
from pair_harness.core.ports import DialogueModel


class DeltaAndFinalModel(DialogueModel):
    """模拟真实对话适配器：增量 delta 片段 + 全量 final 台词（O1.1 回归）。"""

    def __init__(self, final_speech: str) -> None:
        self._final_speech = final_speech

    async def stream_reply(
        self, request: DialogueRequest
    ) -> AsyncIterator[DialogueEvent]:
        yield DialogueEvent(type="speech.delta", delta='{"allow": tru')
        yield DialogueEvent(
            type="character.final", turn=CharacterTurn(speech=self._final_speech)
        )


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


@pytest.mark.asyncio
async def test_dialogue_reviewer_uses_final_only_when_delta_present() -> None:
    """O1.1：同时发送 delta 片段与 final 全量时，只取 final 解析，不拼接重复。"""
    verdict_json = json.dumps(
        {"allow": False, "reason": "命令会删除文件", "suggestion": "改用移动操作"}
    )
    model = DeltaAndFinalModel(verdict_json)
    reviewer = DialogueModelReviewer(model)
    op = PendingOperation(tool_kind="shell", command="rm x", summary="删除文件")
    verdict = await reviewer.review(op, [])
    assert verdict.allow is False
    assert verdict.reason == "命令会删除文件"
    assert verdict.suggestion == "改用移动操作"


@pytest.mark.asyncio
async def test_dialogue_reviewer_fails_closed_on_invalid_json() -> None:
    """O1.1：非法 JSON 输出保持 fail-closed 否决并给出固定理由。"""
    model = DeltaAndFinalModel("这不是 JSON")
    reviewer = DialogueModelReviewer(model)
    op = PendingOperation(tool_kind="shell", command="rm x", summary="删除文件")
    verdict = await reviewer.review(op, [])
    assert verdict.allow is False
    assert verdict.reason == "审查智能体返回格式错误"
    assert verdict.suggestion == "请重试"
