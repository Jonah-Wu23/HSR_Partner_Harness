from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterResultSummary,
    CharacterTurn,
    DialogueRequest,
    EngineSessionRef,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    ProjectRef,
    ProjectRuntimeContext,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel, make_context, unexpected_approval

PAIR_ID = "march7_fourth_mirror"


def _model_replying(content: str) -> OpenAICompatibleDialogueModel:
    """回放一条 Chat Completions 流式响应的角色模型。"""
    delta = json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)
    body = f"data: {delta}\n\n".encode("utf-8") + b"data: [DONE]\n\n"

    def handler(request: Request) -> Response:
        return Response(200, headers={"content-type": "text/event-stream"}, content=body)

    client = AsyncClient(base_url="https://example.com/v1", transport=MockTransport(handler))
    return OpenAICompatibleDialogueModel(
        base_url="https://example.com/v1",
        api_key="test-key",
        model="test-model",
        client=client,
    )


def _result_request(result: CharacterResultSummary) -> DialogueRequest:
    return DialogueRequest(
        pair_id=PAIR_ID,
        conversation_id="c",
        user_message=Message(
            conversation_id="c",
            pair_id=PAIR_ID,
            source=MessageSource.SYSTEM,
            kind=MessageKind.SYSTEM_STATUS,
            text="本轮任务已经结束，请回应执行结果。",
        ),
        result_summary=result,
        runtime_context=ProjectRuntimeContext(
            project_name="HSR Partner Harness",
            project_abs_dir=r"E:\AI\HSR Partner Harness",
            conversation_mode="collaboration",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "content", "speech", "instructions"),
    [
        (
            "failed",
            '{"speech":"没做成，我让第四面镜马上重试一次。",'
            '"delegation":{"type":"task","instructions":"重试任务"}}',
            "没做成，我让第四面镜马上重试一次。",
            "重试任务",
        ),
        # 台词与结果不符时同样原样交给编排器
        (
            "failed",
            '{"speech":"我已经把文件删掉了。",'
            '"delegation":{"type":"task","instructions":"重试任务"}}',
            "我已经把文件删掉了。",
            "重试任务",
        ),
        (
            "completed",
            '{"speech":"做完了。","delegation":{"type":"task","instructions":"多余任务"}}',
            "做完了。",
            "多余任务",
        ),
    ],
)
async def test_result_turn_reply_passes_through_verbatim(
    status: str, content: str, speech: str, instructions: str
) -> None:
    """结果轮的台词与委派原样交给编排器，是否重试由编排器按回执状态决定。"""
    result = CharacterResultSummary(task_id="t-1", status=status, summary="任务结果")

    events = [event async for event in _model_replying(content).stream_reply(_result_request(result))]

    [final] = [event for event in events if event.type == "character.final"]
    assert final.turn.speech == speech
    assert isinstance(final.turn.delegation, TaskRequestDraft)
    assert final.turn.delegation.instructions == instructions


class _FlakyEngine(ScriptedCodingEngine):
    """前 fail_turns 个 turn 失败，之后成功。"""

    def __init__(self, fail_turns: int) -> None:
        super().__init__()
        self._fail_turns = fail_turns

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator:
        self.fail_tool = len(self.requests) < self._fail_turns
        async for event in super().run_turn(session_ref, request):
            yield event


def _make_orchestrator(
    engine: ScriptedCodingEngine, *turns: CharacterTurn
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=engine,
        store=None,
        approval_callback=unexpected_approval,
    )


def _context():
    return make_context(
        ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        conversation_id="c",
        pair_id=PAIR_ID,
        approval_mode=ApprovalMode.FULL_AUTO,
    )


def _delegation_cards(outcome) -> list:
    return [
        m
        for m in outcome.messages
        if m.origin == MessageOrigin.CHARACTER_DELEGATION and m.message_id.startswith("delegation:")
    ]


@pytest.mark.asyncio
async def test_delegation_missed_shows_notice_and_runs_no_task(caplog) -> None:
    """角色自报委派却没有结构化委派：落系统提示并记录警告，不再请求角色，也不交给助手。"""
    engine = _FlakyEngine(fail_turns=0)
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(speech="咱让第四面镜去翻项目资料了。", delegation_missed=True),
    )

    with caplog.at_level("WARNING", logger="pair_harness.core.orchestrator"):
        outcome = await orchestrator.handle_character_input(
            conversation_id="c", text="这个项目是做什么的呢？", context=_context()
        )

    assert len(orchestrator.dialogue_model.requests) == 1
    notices = [m for m in outcome.messages if m.kind == "system.status"]
    assert [m.text for m in notices] == [
        "角色声明要委派，但没有返回结构化委派，本次没有任务交给助手执行。"
    ]
    assert engine.requests == []
    assert outcome.task is None
    assert any(record.levelname == "WARNING" for record in caplog.records)


@pytest.mark.asyncio
async def test_failed_delegation_with_redelegate_retries_once_and_succeeds() -> None:
    """失败结果轮里角色重新委派时自动重试一次，重试成功后正常收尾。"""
    engine = _FlakyEngine(fail_turns=1)
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="交给第四面镜。",
            delegation=TaskRequestDraft(instructions="执行任务一"),
        ),
        CharacterTurn(
            speech="没做成，我让第四面镜马上重试。",
            delegation=TaskRequestDraft(instructions="重试任务"),
        ),
        CharacterTurn(speech="这次做成了。"),
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="请让第四面镜执行任务一", context=_context()
    )

    assert [r.instructions for r in engine.requests] == ["执行任务一", "重试任务"]
    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    cards = _delegation_cards(outcome)
    assert len(cards) == 2
    assert [c.status for c in cards] == [MessageStatus.FAILED, MessageStatus.DONE]
    assert not any("已自动重试一次仍未成功" in m.text for m in outcome.messages)
    # 两次执行各有一个携带结果摘要的结果轮
    result_statuses = [
        r.result_summary.status
        for r in orchestrator.dialogue_model.requests
        if r.result_summary is not None
    ]
    assert result_statuses == ["failed", "completed"]


@pytest.mark.asyncio
async def test_retry_cap_after_second_failure_stops_with_notice() -> None:
    """重试后仍失败时不再执行角色的第三次委派，并留下可见系统提示。"""
    engine = _FlakyEngine(fail_turns=10)
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="交给第四面镜。",
            delegation=TaskRequestDraft(instructions="执行任务一"),
        ),
        CharacterTurn(
            speech="没做成，重试一次。",
            delegation=TaskRequestDraft(instructions="重试任务"),
        ),
        CharacterTurn(
            speech="还是没做成，再试。",
            delegation=TaskRequestDraft(instructions="第三次任务"),
        ),
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="请让第四面镜执行任务一", context=_context()
    )

    # 只执行了首任务和一次重试，第三次委派被上限拦下
    assert [r.instructions for r in engine.requests] == ["执行任务一", "重试任务"]
    assert outcome.receipt is not None
    assert outcome.receipt.status == "failed"
    notices = [m for m in outcome.messages if "已自动重试一次仍未成功" in m.text]
    assert len(notices) == 1
    cards = _delegation_cards(outcome)
    assert len(cards) == 2
    assert all(c.status == MessageStatus.FAILED for c in cards)
