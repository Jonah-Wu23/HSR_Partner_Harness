"""O2.3：取消链路测试。

执行中取消：生命周期落到 CANCELLED（终态）、回执状态 cancelled、
角色结果回应如实说明已停止；无活动任务或引擎 turn 尚未绑定时
cancel_active_task 返回 False，不产生任何引擎请求。
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
    TaskStatus,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel


class CancelableEngine(ScriptedCodingEngine):
    """tool.started 后挂起；收到 cancel_turn 后放行并以 cancelled 收尾。

    模拟 codex 的 turn/interrupt 行为：中断后不再产生后续工具事件，
    直接发出 TURN_COMPLETED(status="cancelled")。
    """

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
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(
            CharacterTurn(
                speech="古代机械，交给你了。",
                delegation=TaskRequestDraft(instructions="跑一下测试"),
            ),
            CharacterTurn(speech="已经停下来了，先缓一缓。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )


@pytest.mark.asyncio
async def test_cancel_active_task_marks_cancelled_receipt_and_reply() -> None:
    """O2.3：执行中取消——状态机、回执与角色回应一致为 cancelled。"""
    engine = CancelableEngine(started=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(engine)
    captured: dict = {}

    async def run() -> None:
        captured["outcome"] = await orchestrator.handle_character_input(
            conversation_id="c", text="跑一下测试"
        )

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(engine._started.wait(), timeout=5)
        assert orchestrator.state.active is not None
        assert orchestrator.state.active.engine_turn_id == "turn-cancel-1"

        assert await orchestrator.cancel_active_task() is True
        # 生命周期先行落到 CANCELLED（终态），后续收尾不重复转移
        assert orchestrator._active_lifecycle is not None
        assert orchestrator._active_lifecycle.status == TaskStatus.CANCELLED
        # 引擎收到 turn/interrupt 对应参数
        assert len(engine.cancelled) == 1
        session_ref, turn_id = engine.cancelled[0]
        assert turn_id == "turn-cancel-1"
        assert session_ref.engine_type == "scripted"
    finally:
        engine._release.set()
        await task

    outcome = captured["outcome"]
    assert orchestrator.state.active is None
    assert outcome.receipt is not None
    assert outcome.receipt.status == "cancelled"
    assert outcome.receipt.summary == "任务已取消"
    # 角色结果回应如实说明已停止（最后一条消息）
    assert outcome.messages[-1].source == MessageSource.CHARACTER
    assert "停" in outcome.messages[-1].text


@pytest.mark.asyncio
async def test_cancel_active_task_without_active_turn_returns_false() -> None:
    """O2.3：无活动任务时取消返回 False，不产生引擎请求。"""
    engine = ScriptedCodingEngine()
    orchestrator = _make_orchestrator(engine)

    assert await orchestrator.cancel_active_task() is False
    assert engine.cancelled == []


@pytest.mark.asyncio
async def test_cancel_before_engine_turn_bound_records_intent_and_interrupts_after_bind() -> None:
    """M1.2：引擎 turn 尚未绑定时取消记录意图，绑定后立即发送 interrupt。"""
    engine = BlockedEngine(entered=asyncio.Event(), release=asyncio.Event())
    orchestrator = _make_orchestrator(engine)
    captured: dict = {}

    async def run() -> None:
        captured["outcome"] = await orchestrator.handle_character_input(
            conversation_id="c", text="跑一下测试"
        )

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(engine._entered.wait(), timeout=5)
        assert orchestrator.state.active is not None
        assert orchestrator.state.active.engine_turn_id is None

        # 未绑定也可以取消：生命周期先到 CANCELLED，记录取消意图。
        assert await orchestrator.cancel_active_task() is True
        assert orchestrator._active_lifecycle is not None
        assert orchestrator._active_lifecycle.status == TaskStatus.CANCELLED
        assert orchestrator.state.active is not None
        assert orchestrator.state.active.cancellation_requested is True
        assert engine.cancelled == []
    finally:
        engine._release.set()
        await task

    # 首个事件到达后绑定 turn id，并立即补发 interrupt；回执为 cancelled。
    assert engine.requests
    assert len(engine.cancelled) == 1
    assert engine.cancelled[0][0].engine_type == "scripted"
    assert engine.cancelled[0][1]
    assert orchestrator.state.active is None
    assert captured["outcome"].receipt is not None
    assert captured["outcome"].receipt.status == "cancelled"
