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
    TaskStatus,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel, make_context, unexpected_approval

CONTEXT = make_context(
    ProjectRef(project_id="p", name="p", root_path="C:\\project"),
    conversation_id="c",
    approval_mode=ApprovalMode.FULL_AUTO,
)


class CancelableEngine(ScriptedCodingEngine):
    """tool.started 后挂起，收到 cancel_turn 后直接以 turn.completed(status=cancelled) 收尾。"""

    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self._started = started
        self._release = release
        self._interrupted = asyncio.Event()

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self.requests.append(request)
        common = {
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "engine_turn_id": "turn-cancel-1",
        }
        yield EngineEvent(sequence=0, type=EngineEventType.TURN_STARTED, **common)
        yield EngineEvent(
            sequence=1,
            type=EngineEventType.TOOL_STARTED,
            tool_call_id="tool-cancel-1",
            payload={"title": "长任务", "details": request.instructions},
            **common,
        )
        self._started.set()
        await self._release.wait()
        # 取消请求到达后立刻以 cancelled 收尾，不再产生后续事件
        await self._interrupted.wait()
        yield EngineEvent(
            sequence=2,
            type=EngineEventType.TURN_COMPLETED,
            payload={"status": "cancelled", "summary": "用户中断"},
            **common,
        )

    async def cancel_turn(self, session_ref: EngineSessionRef, turn_id: str) -> None:
        await super().cancel_turn(session_ref, turn_id)
        self._interrupted.set()


class BlockedEngine(ScriptedCodingEngine):
    """首个事件前挂起：引擎 turn 尚未绑定，取消应返回 False。"""

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


def _make_orchestrator(engine: ScriptedCodingEngine) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(
            CharacterTurn(
                speech="古代机械，交给你了。",
                delegation=TaskRequestDraft(instructions="跑一下测试"),
            ),
            CharacterTurn(speech="已经停下来了，先缓一缓。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_callback=unexpected_approval,
    )


@pytest.mark.asyncio
async def test_cancel_active_task_marks_cancelled_receipt_and_reply() -> None:
    """执行中取消后生命周期、回执与角色回应都落到 cancelled。"""
    engine = CancelableEngine(started=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(engine)
    captured: dict = {}

    async def run() -> None:
        captured["outcome"] = await orchestrator.handle_character_input(
            conversation_id="c", text="跑一下测试", context=CONTEXT
        )

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(engine._started.wait(), timeout=5)
        active = orchestrator.state.get_for_conversation("c")
        assert active is not None
        assert active.engine_turn_id == "turn-cancel-1"

        assert await orchestrator.cancel_active_task("c", active.task_id) is True
        # 生命周期先行落到 CANCELLED（终态），后续收尾不重复转移
        lifecycle = orchestrator._active_lifecycles.get(active.task_id)
        assert lifecycle is not None
        assert lifecycle.status == TaskStatus.CANCELLED
        # 引擎收到该 turn 的中断请求
        assert len(engine.cancelled) == 1
        session_ref, turn_id = engine.cancelled[0]
        assert turn_id == "turn-cancel-1"
        assert session_ref.engine_type == "scripted"
    finally:
        engine._release.set()
        await task

    outcome = captured["outcome"]
    assert orchestrator.state.get_for_conversation("c") is None
    assert outcome.receipt is not None
    assert outcome.receipt.status == "cancelled"
    # 引擎没有输出助手正文，回执摘要如实为空
    assert outcome.receipt.summary == ""
    # 角色结果回应如实说明已停止（最后一条消息）
    assert outcome.messages[-1].source == MessageSource.CHARACTER
    assert "停" in outcome.messages[-1].text


@pytest.mark.asyncio
async def test_cancel_active_task_without_active_turn_returns_false() -> None:
    engine = ScriptedCodingEngine()
    orchestrator = _make_orchestrator(engine)

    assert await orchestrator.cancel_active_task("c") is False
    assert engine.cancelled == []


@pytest.mark.asyncio
async def test_cancel_before_engine_turn_bound_records_intent_and_interrupts_after_bind() -> None:
    engine = BlockedEngine(entered=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(engine)
    captured: dict = {}

    async def run() -> None:
        captured["outcome"] = await orchestrator.handle_character_input(
            conversation_id="c", text="跑一下测试", context=CONTEXT
        )

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(engine._entered.wait(), timeout=5)
        active = orchestrator.state.get_for_conversation("c")
        assert active is not None
        assert active.engine_turn_id is None

        # 未绑定也可以取消：生命周期先到 CANCELLED，记录取消意图。
        assert await orchestrator.cancel_active_task("c", active.task_id) is True
        lifecycle = orchestrator._active_lifecycles.get(active.task_id)
        assert lifecycle is not None
        assert lifecycle.status == TaskStatus.CANCELLED
        active = orchestrator.state.get_for_conversation("c")
        assert active is not None
        assert active.cancellation_requested is True
        assert engine.cancelled == []
    finally:
        engine._release.set()
        await task

    # 首个事件到达后绑定 turn id，并立即补发 interrupt；回执为 cancelled。
    assert engine.requests
    assert len(engine.cancelled) == 1
    assert engine.cancelled[0][0].engine_type == "scripted"
    assert engine.cancelled[0][1]
    assert orchestrator.state.get_for_conversation("c") is None
    assert captured["outcome"].receipt is not None
    assert captured["outcome"].receipt.status == "cancelled"
