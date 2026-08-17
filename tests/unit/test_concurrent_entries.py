"""O2.5：编排器入口并发防护测试。

同一会话的入口按 asyncio.Lock 串行化：聊天轮（用户消息+角色台词）
整体落库、轮内顺序固定且互不交错；任务执行不在锁内——执行期间
到达的聊天轮可与运行中任务并发，运行中直接输入仍归一为修改。
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    MessageSource,
    ProjectRef,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel


class PausingEngine(ScriptedCodingEngine):
    """tool.started 推送后挂起，等待测试放行，模拟执行中的任务。"""

    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self._started = started
        self._release = release

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        async for event in super().run_turn(session_ref, request):
            yield event
            if event.type == EngineEventType.TOOL_STARTED:
                self._started.set()
                await self._release.wait()


def _make_orchestrator(
    engine: ScriptedCodingEngine, *turns: CharacterTurn
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )


def _chat_round_indices(history, texts) -> list[int]:
    """返回聊天轮各消息在历史中的索引（用户与角色台词各一条）。"""
    return [i for i, m in enumerate(history) if m.text in texts]


class AwaitingDialogueModel(FixedDialogueModel):
    """stream_reply 内部让出事件循环——制造锁内挂起点。

    没有这个挂起点时两条协程顺序跑完，``_conversation_lock`` 从未发生
    竞争，测试对"锁被删除"这一回归是断臂的；有了挂起点，第二条协程
    会在锁外被阻塞，锁的互斥才被真实验证。
    """

    async def stream_reply(self, request):
        await asyncio.sleep(0)
        async for event in super().stream_reply(request):
            await asyncio.sleep(0)
            yield event


@pytest.mark.asyncio
async def test_concurrent_chat_rounds_serialized_in_arrival_order() -> None:
    """O2.5：并发纯聊天——聊天轮按到达顺序整体落库，互不交错。

    对话模型在锁内让出事件循环：若会话锁被删除，乙轮的用户消息会插进
    甲轮的用户/角色台词之间（甲、乙、我在、我也在），本测试随即变红。
    """
    engine = ScriptedCodingEngine()
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=AwaitingDialogueModel(
            CharacterTurn(speech="我在，慢慢说。", delegation=None),
            CharacterTurn(speech="我也在，慢慢说。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    round_a = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="甲")
    )
    round_b = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="乙")
    )
    await asyncio.gather(round_a, round_b)

    history = orchestrator._history["c"]
    texts = [m.text for m in history]
    # 两轮各自的用户/角色台词相邻，且先到达的轮整体在前
    assert texts == ["甲", "我在，慢慢说。", "乙", "我也在，慢慢说。"]


@pytest.mark.asyncio
async def test_running_task_keeps_origin_project_and_pair_after_context_switch() -> None:
    """M4：切换聊天时，执行中的任务继续使用发起聊天的上下文。"""
    started = asyncio.Event()
    release = asyncio.Event()
    engine = PausingEngine(started=started, release=release)
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="交给古代机械。",
            delegation=TaskRequestDraft(instructions="检查项目"),
        ),
        CharacterTurn(speech="已经完成。", delegation=None),
    )

    task = asyncio.create_task(
        orchestrator.handle_direct_input(conversation_id="origin", text="检查项目")
    )
    await started.wait()
    orchestrator.select_context(
        project=ProjectRef(project_id="other", name="other", root_path="C:\\other"),
        pair_id="other_pair",
        conversation_id="other-conversation",
        approval_mode=ApprovalMode.FULL_AUTO,
        assistant_instructions="other instructions",
    )
    release.set()
    await task

    assert engine.opened_sessions[0][0].project_id == "p"
    assert orchestrator._history["origin"]
    assert {message.pair_id for message in orchestrator._history["origin"]} == {
        "phainon_ancient_machine"
    }


@pytest.mark.asyncio
async def test_chat_rounds_and_amendment_during_execution() -> None:
    """O2.5：执行中并发聊天轮 + 直接输入——历史确定、修改路由生效。

    聊天轮不等任务结束即完成（不与执行串行排队）；两轮消息各自相邻；
    运行中直接输入归一为用户来源 amendment。
    """
    engine = PausingEngine(started=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="任务开始了。",
            delegation=TaskRequestDraft(instructions="跑一下测试"),
        ),
        CharacterTurn(speech="聊一轮甲。", delegation=None),
        CharacterTurn(speech="聊一轮乙。", delegation=None),
        CharacterTurn(speech="做完了。", delegation=None),
    )
    first = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="请让古代机械跑测试")
    )
    try:
        await asyncio.wait_for(engine._started.wait(), timeout=5)

        round_a = asyncio.create_task(
            orchestrator.handle_character_input(conversation_id="c", text="甲")
        )
        round_b = asyncio.create_task(
            orchestrator.handle_character_input(conversation_id="c", text="乙")
        )
        direct = asyncio.create_task(
            orchestrator.handle_direct_input(conversation_id="c", text="改成先跑冒烟")
        )
        await asyncio.wait_for(asyncio.gather(round_a, round_b, direct), timeout=5)

        # 聊天轮与直接输入在任务结束前就已完成（不排队等执行结束）
        assert not first.done()

        history = orchestrator._history["c"]
        texts = [m.text for m in history]
        # 两轮聊天消息各自相邻（用户→角色），顺序确定
        i_ja = _chat_round_indices(history, {"甲", "聊一轮甲。"})
        i_yi = _chat_round_indices(history, {"乙", "聊一轮乙。"})
        assert len(i_ja) == 2 and i_ja[1] == i_ja[0] + 1
        assert len(i_yi) == 2 and i_yi[1] == i_yi[0] + 1
        # 到达顺序：甲轮整体在乙轮之前，直接输入消息最后
        assert i_ja[0] < i_yi[0] < texts.index("改成先跑冒烟")

        # 运行中直接输入归一为用户来源 amendment，未开启新任务
        assert len(engine.amendments) == 1
        _, _, amendment = engine.amendments[0]
        assert amendment.origin == "user"
        assert amendment.instructions == "改成先跑冒烟"
        assert len(engine.requests) == 1
    finally:
        engine._release.set()
        outcome = await first

    # 任务按原计划正常完成，结果回应在最后
    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    assert orchestrator._history["c"][-1].source == MessageSource.CHARACTER


@pytest.mark.asyncio
async def test_direct_input_from_other_conversation_runs_concurrently() -> None:
    """V0.3.2 M4：并发单位是 conversation。

    聊天 A 的任务运行中，聊天 B 的直发输入立即启动自己的任务——不再被
    全局单任务闸门拒绝，也不会归一为 A 的 amendment。"""
    engine = PausingEngine(started=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="任务开始了。",
            delegation=TaskRequestDraft(instructions="跑测试"),
        ),
        CharacterTurn(speech="A 做完了。"),
        CharacterTurn(speech="B 结果收到。"),
    )
    running = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="chat-a", text="开始")
    )
    try:
        await asyncio.wait_for(engine._started.wait(), timeout=5)
        direct = asyncio.create_task(
            orchestrator.handle_direct_input(
                conversation_id="chat-b", text="改成只跑单测"
            )
        )
        # B 的回合推进到自己的工具事件（同一 started 事件第二次置位）
        await asyncio.wait_for(engine._started.wait(), timeout=5)
        assert orchestrator.state.get_for_conversation("chat-a") is not None
        assert orchestrator.state.get_for_conversation("chat-b") is not None
        engine._release.set()
        outcome_b = await asyncio.wait_for(direct, timeout=5)
        outcome_a = await running
        assert engine.amendments == []
        assert outcome_b.receipt is not None
        assert outcome_a.receipt is not None
        # 各自的历史互不串线
        assert {m.conversation_id for m in outcome_b.messages} == {"chat-b"}
        assert {m.conversation_id for m in outcome_a.messages} <= {"chat-a"}
    finally:
        engine._release.set()
        await running
