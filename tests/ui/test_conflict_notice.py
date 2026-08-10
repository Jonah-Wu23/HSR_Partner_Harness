"""O2.4：UI 冲突提示可见性测试。

任务运行中角色再委派新任务：冲突系统提示经由流式通道上屏，
界面能看到“任务仍在执行”的提示，而不是静默失败。
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
    ProjectRef,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.ui.main_window import MainWindow
from pair_harness.ui.qt_bridge import OrchestratorBridge
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


@pytest.mark.asyncio
async def test_busy_delegation_conflict_notice_visible(qtbot) -> None:
    """O2.4：执行中角色再委派——冲突系统提示在界面上可见。"""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    bridge = OrchestratorBridge()
    bridge.message_ready.connect(window.add_message)
    engine = PausingEngine(started=asyncio.Event(), release=asyncio.Event())
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(
            CharacterTurn(
                speech="古代机械，交给你了。",
                delegation=TaskRequestDraft(instructions="任务一"),
            ),
            CharacterTurn(
                speech="古代机械，再来一个。",
                delegation=TaskRequestDraft(instructions="任务二"),
            ),
            CharacterTurn(speech="做完了。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )
    orchestrator.on_message = bridge.message_ready.emit

    first = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="请让古代机械跑任务一")
    )
    try:
        await asyncio.wait_for(engine._started.wait(), timeout=5)

        await orchestrator.handle_character_input(
            conversation_id="c", text="再让古代机械跑任务二"
        )

        texts = [b.text_label.text() for b in window.character_messages.bubbles]
        assert any("任务仍在执行" in t for t in texts), f"未见冲突提示，实际：{texts}"
    finally:
        engine._release.set()
        await first
