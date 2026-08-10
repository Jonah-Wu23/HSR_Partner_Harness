"""O2.4：运行中修改优先路由测试。

设计 §3.2：运行中用户直接发给助手的新指令拥有最高优先级——
归一为 TaskAmendment 走 amend_turn（来源标记 user）；角色再委派
新任务等冲突场景转为用户可见的系统提示，不再静默失败。
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
    MessageKind,
    ProjectRef,
    TaskAmendmentDraft,
    TaskRequest,
    TaskRequestDraft,
    TaskStatus,
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


class UnboundEngine(ScriptedCodingEngine):
    """首个事件前挂起：引擎 turn 尚未绑定，修改无法路由。"""

    def __init__(self, entered: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self._entered = entered
        self._release = release

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self.requests.append(request)
        self._entered.set()
        await self._release.wait()
        async for event in super().run_turn(session_ref, request):
            yield event


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


@pytest.mark.asyncio
async def test_direct_input_while_busy_becomes_user_amendment() -> None:
    """O2.4：运行中直接输入归一为用户来源的 TaskAmendment，不走新任务。"""
    engine = PausingEngine(started=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="古代机械，交给你了。",
            delegation=TaskRequestDraft(instructions="跑一下测试"),
        ),
        CharacterTurn(speech="做完了。", delegation=None),
    )
    first = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="请让古代机械跑测试")
    )
    try:
        await asyncio.wait_for(engine._started.wait(), timeout=5)
        active = orchestrator.state.active
        assert active is not None and active.engine_turn_id is not None

        outcome = await orchestrator.handle_direct_input(
            conversation_id="c", text="改成先跑冒烟"
        )

        # 只产生用户消息，没有第二个任务
        assert [m.kind for m in outcome.messages] == [MessageKind.USER_TEXT]
        assert len(engine.requests) == 1
        # amendment 走 amend_turn，来源可区分为用户
        assert len(engine.amendments) == 1
        session_ref, turn_id, amendment = engine.amendments[0]
        assert turn_id == active.engine_turn_id
        assert amendment.origin == "user"
        assert amendment.instructions == "改成先跑冒烟"
        assert amendment.target_task_id == active.task_id
        assert amendment.origin_message_id == outcome.messages[0].message_id
        assert amendment.revision == 1
        # 生命周期回落 RUNNING，任务继续执行
        assert orchestrator._active_lifecycle is not None
        assert orchestrator._active_lifecycle.status == TaskStatus.RUNNING
    finally:
        engine._release.set()
        await first


@pytest.mark.asyncio
async def test_character_delegation_while_busy_shows_visible_notice() -> None:
    """O2.4：任务运行中角色再委派新任务——冲突系统提示可见，不静默。"""
    engine = PausingEngine(started=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="古代机械，交给你了。",
            delegation=TaskRequestDraft(instructions="任务一"),
        ),
        CharacterTurn(
            speech="古代机械，再来一个。",
            delegation=TaskRequestDraft(instructions="任务二"),
        ),
        CharacterTurn(speech="做完了。", delegation=None),
    )
    first = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="请让古代机械跑任务一")
    )
    try:
        await asyncio.wait_for(engine._started.wait(), timeout=5)

        outcome = await orchestrator.handle_character_input(
            conversation_id="c", text="再让古代机械跑任务二"
        )

        # 冲突提示以系统消息留在时间线
        notices = [
            m for m in outcome.messages if m.kind == MessageKind.SYSTEM_STATUS
        ]
        assert len(notices) == 1
        assert "任务仍在执行" in notices[0].text
        assert "暂未受理" in notices[0].text
        # 第二个任务没有进入引擎
        assert len(engine.requests) == 1
    finally:
        engine._release.set()
        await first


@pytest.mark.asyncio
async def test_character_amendment_while_busy_marks_character_origin() -> None:
    """O2.4：角色建议的修改保持 character 来源，与用户指令区分。"""
    engine = PausingEngine(started=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="古代机械，交给你了。",
            delegation=TaskRequestDraft(instructions="任务一"),
        ),
        CharacterTurn(
            speech="古代机械，改一下。",
            delegation=TaskAmendmentDraft(instructions="改为执行冒烟"),
        ),
        CharacterTurn(speech="做完了。", delegation=None),
    )
    first = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="请让古代机械跑任务一")
    )
    try:
        await asyncio.wait_for(engine._started.wait(), timeout=5)

        await orchestrator.handle_character_input(conversation_id="c", text="请让古代机械改一下")

        assert len(engine.amendments) == 1
        _, _, amendment = engine.amendments[0]
        assert amendment.origin == "character"
        assert amendment.instructions == "改为执行冒烟"
    finally:
        engine._release.set()
        await first


@pytest.mark.asyncio
async def test_direct_input_while_turn_unbound_shows_visible_notice() -> None:
    """O2.4：引擎 turn 尚未绑定时直接输入无法路由，转可见提示。"""
    engine = UnboundEngine(entered=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(
        engine,
        CharacterTurn(
            speech="古代机械，交给你了。",
            delegation=TaskRequestDraft(instructions="跑一下测试"),
        ),
        CharacterTurn(speech="做完了。", delegation=None),
    )
    first = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="请让古代机械跑测试")
    )
    try:
        await asyncio.wait_for(engine._entered.wait(), timeout=5)
        assert orchestrator.state.active is not None
        assert orchestrator.state.active.engine_turn_id is None

        outcome = await orchestrator.handle_direct_input(
            conversation_id="c", text="改成先跑冒烟"
        )

        notices = [m for m in outcome.messages if m.kind == MessageKind.SYSTEM_STATUS]
        assert len(notices) == 1
        assert "修改未能应用" in notices[0].text
        assert engine.amendments == []
    finally:
        engine._release.set()
        await first
