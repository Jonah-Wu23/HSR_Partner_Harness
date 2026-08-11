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
    """O1.1/B1：delta 片段不完整时回退 final 全量解析，不拼接重复。"""
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
async def test_dialogue_reviewer_parses_full_delta_stream() -> None:
    """B1 联调加固：审查模型直接输出纯 JSON（无 speech 包裹）时，角色适配器
    的 character.final 会把它降级成“……”；审查方必须拼接 speech.delta
    原始流解析，而不是依赖 final。"""
    verdict_json = json.dumps({"allow": False, "reason": "删除操作", "suggestion": "改用移动"})

    class FullDeltaModel(DialogueModel):
        async def stream_reply(
            self, request: DialogueRequest
        ) -> AsyncIterator[DialogueEvent]:
            # 模拟 OpenAI 适配器：delta 是完整 content 的增量流，
            # final 是对整体文本二次加工的结果（纯 JSON → 降级“……”）
            for i in range(0, len(verdict_json), 10):
                yield DialogueEvent(type="speech.delta", delta=verdict_json[i : i + 10])
            yield DialogueEvent(type="character.final", turn=CharacterTurn(speech="……"))

    reviewer = DialogueModelReviewer(FullDeltaModel())
    op = PendingOperation(tool_kind="shell", command="rm x", summary="删除文件")
    verdict = await reviewer.review(op, [])
    assert verdict.allow is False
    assert verdict.reason == "删除操作"
    assert verdict.suggestion == "改用移动"


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


@pytest.mark.asyncio
async def test_dialogue_reviewer_tolerates_markdown_fence() -> None:
    """B1 联调加固：真实模型输出可能包 markdown 代码块，仍能解析。"""
    verdict_json = json.dumps(
        {"allow": False, "reason": "删除操作", "suggestion": "改用移动"}
    )
    model = DeltaAndFinalModel(f"```json\n{verdict_json}\n```")
    reviewer = DialogueModelReviewer(model)
    op = PendingOperation(tool_kind="shell", command="rm x", summary="删除文件")
    verdict = await reviewer.review(op, [])
    assert verdict.allow is False
    assert verdict.reason == "删除操作"
    assert verdict.suggestion == "改用移动"


@pytest.mark.asyncio
async def test_dialogue_reviewer_tolerates_surrounding_text() -> None:
    """B1 联调加固：JSON 前后带解释文字时提取对象解析。"""
    verdict_json = json.dumps({"allow": True, "reason": "", "suggestion": ""})
    model = DeltaAndFinalModel(f"审查结论如下：{verdict_json}（以上为结论）")
    reviewer = DialogueModelReviewer(model)
    op = PendingOperation(tool_kind="shell", command="ls", summary="列出文件")
    verdict = await reviewer.review(op, [])
    assert verdict.allow is True


@pytest.mark.asyncio
async def test_dialogue_reviewer_fails_closed_on_fallback_speech() -> None:
    """B1 联调加固：适配器降级台词（“……”）按格式错误否决，不误判。"""
    model = DeltaAndFinalModel("……")
    reviewer = DialogueModelReviewer(model)
    op = PendingOperation(tool_kind="shell", command="rm x", summary="删除文件")
    verdict = await reviewer.review(op, [])
    assert verdict.allow is False
    assert verdict.reason == "审查智能体返回格式错误"
