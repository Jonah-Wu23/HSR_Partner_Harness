"""委派失败重试与失败可见性。

委派判定权交给语言模型自己（运行时协议的 delegate 字段），代码只查
结构一致性：模型自报需要委派（delegate=true）却没返回 delegation 即
协议违规，触发纠偏重试；重试耗尽后仍不提交结构则标记真实失败，由
编排器向角色侧暴露——不再用正则或关键词猜用户意图。

以及失败结果回传角色后的立即重试链路：角色在失败结果轮重新委派 →
编排器自动重试一次 → 达到上限后不再执行并留下可见系统提示。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient, Request, Response
from httpx._transports.mock import MockTransport

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterResultSummary,
    CharacterTurn,
    EngineSessionRef,
    MessageOrigin,
    MessageStatus,
    ProjectRef,
    ProjectRuntimeContext,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel

PAIR_ID = "march7_fourth_mirror"


def _sse(content: str) -> bytes:
    delta = json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)
    return f"data: {delta}\n".encode("utf-8") + b"data: [DONE]\n"


def _scripted_transport(scripts: list[str]) -> tuple[MockTransport, list[dict]]:
    bodies: list[dict] = []

    def handler(request: Request) -> Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        return Response(200, content=_sse(scripts.pop(0)))

    return MockTransport(handler), bodies


def _request(
    *,
    text: str,
    mode: str = "collaboration",
    result: CharacterResultSummary | None = None,
):
    from pair_harness.core.contracts import DialogueRequest, Message, MessageKind, MessageSource

    user = Message(
        conversation_id="c",
        pair_id=PAIR_ID,
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text=text,
    )
    return DialogueRequest(
        pair_id=PAIR_ID,
        conversation_id="c",
        user_message=user,
        result_summary=result,
        runtime_context=ProjectRuntimeContext(
            project_name="HSR Partner Harness",
            project_abs_dir=r"E:\AI\HSR Partner Harness",
            conversation_mode=mode,  # type: ignore[arg-type]
        ),
    )


def _model(transport: MockTransport) -> OpenAICompatibleDialogueModel:
    client = AsyncClient(base_url="https://example.com/v1", transport=transport)
    return OpenAICompatibleDialogueModel(
        base_url="https://example.com/v1",
        api_key="test-key",
        model="test-model",
        client=client,
    )


async def _final_turn(model: OpenAICompatibleDialogueModel, request) -> CharacterTurn:
    events = [event async for event in model.stream_reply(request)]
    finals = [event for event in events if event.type == "character.final"]
    assert len(finals) == 1
    return finals[0].turn


# ---------------------------------------------------------------------------
# 委派判定交给模型自报（delegate 字段），代码只查一致性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_declared_delegation_triggers_retry_on_any_provider() -> None:
    """模型自报 delegate=true 却没带 delegation → 通用端点也要纠偏重试。

    用户说法不受词典约束（“这个项目是做什么的呢”与“删掉 Hello World 点
    txt”都是同样的触发形态，只要模型自己声明需要委派）。
    """
    transport, bodies = _scripted_transport(
        [
            '{"speech":"咱得让第四面镜帮忙看看才知道具体是啥。","delegate":true}',
            '{"speech":"咱让第四面镜去翻翻项目文件。","delegate":true,'
            '"delegation":{"type":"task","instructions":"查看项目结构并说明用途"}}',
        ]
    )
    model = _model(transport)

    turn = await _final_turn(model, _request(text="这个项目是做什么的呢？"))

    assert len(bodies) == 2
    # 纠偏消息注入第二次请求
    retry_messages = bodies[1]["messages"]
    assert any(
        m["role"] == "system" and "协议违规" in m["content"]
        for m in retry_messages
    )
    assert isinstance(turn.delegation, TaskRequestDraft)
    assert turn.delegation.instructions == "查看项目结构并说明用途"
    assert turn.delegation_missed is False


@pytest.mark.asyncio
async def test_declared_delegation_without_resource_words_still_retries() -> None:
    """用户措辞不含任何资源词（截图中删除 Hello World 点 txt 的形态）：
    只要模型自报 delegate=true 就必须纠偏，不再依赖关键词。"""
    transport, bodies = _scripted_transport(
        [
            '{"speech":"好嘞，这就让第四面镜把那个 Hello World.txt 收拾掉。","delegate":true}',
            '{"speech":"这就去。","delegate":true,'
            '"delegation":{"type":"task","instructions":"删除 Hello World.txt"}}',
        ]
    )
    model = _model(transport)

    turn = await _final_turn(
        model, _request(text="那啥，你现在让他把这个 Hello World 点 txt 删除。")
    )

    assert len(bodies) == 2
    assert isinstance(turn.delegation, TaskRequestDraft)
    assert turn.delegation.instructions == "删除 Hello World.txt"
    assert turn.delegation_missed is False


@pytest.mark.asyncio
async def test_missing_delegation_after_retry_marks_missed() -> None:
    """纠偏重试耗尽后模型仍自报委派却不提交结构：真实失败标记，不得静默通过。

    台词取自三月七实测失败记录（口头答应交给第四面镜，却没有返回
    结构化 delegation）。
    """
    transport, bodies = _scripted_transport(
        [
            '{"speech":"咱得让第四面镜帮忙看看才知道具体是啥。你等等，咱这就让他去翻翻项目文件。","delegate":true}',
            '{"speech":"咱让第四面镜去查了，一会儿就有消息。","delegate":true}',
        ]
    )
    model = _model(transport)

    turn = await _final_turn(model, _request(text="这个项目是做什么的呢？"))

    assert len(bodies) == 2
    assert turn.delegation is None
    assert turn.delegation_missed is True


@pytest.mark.asyncio
async def test_chat_mode_never_retries_or_marks() -> None:
    """聊天模式没有委派能力边界，即使模型自报 delegate=true 也不执行。"""
    transport, bodies = _scripted_transport(
        ['{"speech":"咱们随便聊聊。","delegate":true}']
    )
    model = _model(transport)

    turn = await _final_turn(model, _request(text="这个项目是做什么的呢？", mode="chat"))

    assert len(bodies) == 1
    assert turn.delegation_missed is False


@pytest.mark.asyncio
async def test_missing_delegate_field_triggers_rejudgement_retry() -> None:
    """协作模式下输出缺 delegate 字段（协议不完整）：纠偏让模型重新判断。

    模型重判为纯聊天（delegate=false）时不委派、不标记失败。
    """
    transport, bodies = _scripted_transport(
        [
            '{"speech":"今天天气不错。"}',
            '{"speech":"今天天气不错呀，出去走走？","delegate":false}',
        ]
    )
    model = _model(transport)

    turn = await _final_turn(model, _request(text="今天心情怎么样？"))

    assert len(bodies) == 2
    assert turn.delegation is None
    assert turn.delegation_missed is False


@pytest.mark.asyncio
async def test_still_incomplete_after_retry_marks_missed() -> None:
    """纠偏后输出仍不完整（无 delegate 也无 delegation）：标记真实失败。"""
    transport, bodies = _scripted_transport(
        [
            '{"speech":"好嘞，这就让第四面镜去收拾。"}',
            '{"speech":"这就让第四面镜去收拾，咱看着它动手。"}',
        ]
    )
    model = _model(transport)

    turn = await _final_turn(
        model, _request(text="那啥，你现在让他把这个 Hello World 点 txt 删除。")
    )

    assert len(bodies) == 2
    assert turn.delegation is None
    assert turn.delegation_missed is True


@pytest.mark.asyncio
async def test_declaration_without_delegation_speech_mention_still_retries() -> None:
    """自报 true 且台词提到搭档，但无 delegation —— 同样触发纠偏。"""
    transport, bodies = _scripted_transport(
        [
            '{"speech":"第四面镜，这就交给你了。","delegate":true}',
            '{"speech":"交给你了。","delegate":true,'
            '"delegation":{"type":"task","instructions":"整理报告"}}',
        ]
    )
    model = _model(transport)

    turn = await _final_turn(model, _request(text="帮我把报告整理一下"))

    assert len(bodies) == 2
    assert isinstance(turn.delegation, TaskRequestDraft)
    assert turn.delegation.instructions == "整理报告"


# ---------------------------------------------------------------------------
# 失败结果轮：角色立即重新委派
# ---------------------------------------------------------------------------


def _failed_result() -> CharacterResultSummary:
    return CharacterResultSummary(
        task_id="t-1",
        status="failed",
        summary="任务执行失败",
        limitations=("模拟工具失败",),
    )


@pytest.mark.asyncio
async def test_failed_result_turn_keeps_redelegation() -> None:
    """失败结果轮重新委派：台词与 delegation 原样放行，供编排器自动重试。"""
    transport, _bodies = _scripted_transport(
        [
            '{"speech":"没做成，我让第四面镜马上重试一次。",'
            '"delegation":{"type":"task","instructions":"重试任务"}}'
        ]
    )
    model = _model(transport)

    turn = await _final_turn(model, _request(text="execution-result", result=_failed_result()))

    assert isinstance(turn.delegation, TaskRequestDraft)
    assert turn.delegation.instructions == "重试任务"
    assert turn.speech == "没做成，我让第四面镜马上重试一次。"


@pytest.mark.asyncio
async def test_failed_result_turn_passes_through_verbatim() -> None:
    """失败结果轮台词原样放行：不再有 truthful 守卫改写。"""
    transport, _bodies = _scripted_transport(
        [
            '{"speech":"我已经把文件删掉了。",'
            '"delegation":{"type":"task","instructions":"重试任务"}}'
        ]
    )
    model = _model(transport)

    turn = await _final_turn(model, _request(text="execution-result", result=_failed_result()))

    assert turn.speech == "我已经把文件删掉了。"
    assert isinstance(turn.delegation, TaskRequestDraft)


@pytest.mark.asyncio
async def test_completed_result_turn_passes_through_verbatim() -> None:
    """成功结果轮同样原样放行：委派与否交给模型，代码不再剥离。"""
    result = CharacterResultSummary(task_id="t-1", status="completed", summary="完成")
    transport, _bodies = _scripted_transport(
        [
            '{"speech":"做完了。","delegation":{"type":"task","instructions":"多余任务"}}'
        ]
    )
    model = _model(transport)

    turn = await _final_turn(model, _request(text="execution-result", result=result))

    assert turn.speech == "做完了。"
    assert isinstance(turn.delegation, TaskRequestDraft)
    assert turn.delegation.instructions == "多余任务"


# ---------------------------------------------------------------------------
# 编排器：失败可见 + 失败后自动重试一次
# ---------------------------------------------------------------------------


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
        pair_id=PAIR_ID,
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )


def _delegation_cards(outcome) -> list:
    return [
        m
        for m in outcome.messages
        if m.origin == MessageOrigin.CHARACTER_DELEGATION and m.message_id.startswith("delegation:")
    ]


@pytest.mark.asyncio
async def test_delegation_missed_auto_retry_then_notice() -> None:
    """委派未形成：自动补一轮，仍失败才落系统提示。"""
    engine = _FlakyEngine(fail_turns=0)
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(speech="咱让第四面镜去翻项目资料了。", delegation_missed=True),
        CharacterTurn(speech="咱再试一次。", delegation_missed=True),
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="这个项目是做什么的呢？"
    )

    # 自动补了一轮对话，仍无结构化委派 → 可见系统提示，任务未交给助手
    assert orchestrator.dialogue_model.requests and len(
        orchestrator.dialogue_model.requests
    ) == 2
    notices = [m for m in outcome.messages if m.kind == "system.status"]
    assert len(notices) == 1
    assert "自动重试后仍未成功" in notices[0].text
    assert engine.requests == []


@pytest.mark.asyncio
async def test_delegation_missed_auto_retry_succeeds() -> None:
    """委派未形成：自动补一轮后角色成功委派 → 任务正常执行。"""
    engine = _FlakyEngine(fail_turns=0)
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(speech="咱让第四面镜去翻项目资料了。", delegation_missed=True),
        CharacterTurn(
            speech="这回正经委派。",
            delegation=TaskRequestDraft(instructions="查看项目结构"),
        ),
        CharacterTurn(speech="做完了。"),
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="这个项目是做什么的呢？"
    )

    assert [r.instructions for r in engine.requests] == ["查看项目结构"]
    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    cards = _delegation_cards(outcome)
    assert len(cards) == 1
    assert cards[0].status == MessageStatus.DONE
    assert not any("自动重试后仍未成功" in m.text for m in outcome.messages)


@pytest.mark.asyncio
async def test_failed_delegation_with_redelegate_retries_once_and_succeeds() -> None:
    """失败结果轮角色重新委派 → 自动重试一次 → 成功收尾。"""
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
        conversation_id="c", text="请让第四面镜执行任务一"
    )

    assert [r.instructions for r in engine.requests] == ["执行任务一", "重试任务"]
    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    cards = _delegation_cards(outcome)
    assert len(cards) == 2
    assert [c.status for c in cards] == [MessageStatus.FAILED, MessageStatus.DONE]
    # 没有触发重试上限提示
    assert not any("已自动重试一次仍未成功" in m.text for m in outcome.messages)
    # 结果轮 synthetic 消息是清晰的中文指引，不再是无意义英文信号
    assert len(orchestrator.dialogue_model.requests) == 3
    result_requests = [
        r
        for r in orchestrator.dialogue_model.requests
        if r.result_summary is not None
    ]
    assert len(result_requests) == 2
    for r in result_requests:
        assert "任务已经结束" in r.user_message.text
        assert r.user_message.text != "execution-result"


@pytest.mark.asyncio
async def test_retry_cap_after_second_failure_stops_with_notice() -> None:
    """重试后仍失败：不再执行第三次委派，留下可见系统提示。"""
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
        conversation_id="c", text="请让第四面镜执行任务一"
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
