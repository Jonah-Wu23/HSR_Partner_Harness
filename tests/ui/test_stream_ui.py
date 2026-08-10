"""O2.1：UI 流式增量渲染测试。

任务执行中途（工具事件已推送但任务未结束）界面必须已经出现
角色台词与运行中的工具卡片，不等整轮任务结束。
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    DialogueEvent,
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
async def test_ui_renders_character_line_and_running_tool_card_mid_execution(
    qtbot,
) -> None:
    """O2.1：执行中途界面已出现角色台词与运行中的工具卡片。"""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    bridge = OrchestratorBridge()
    bridge.message_ready.connect(window.add_message)
    bridge.tool_run_ready.connect(window.update_tool_run)
    bridge.engine_event_ready.connect(window.apply_engine_event)
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(
            CharacterTurn(
                speech="古代机械，交给你了。",
                delegation=TaskRequestDraft(instructions="跑一下测试"),
            ),
            CharacterTurn(speech="做完了，我们继续。", delegation=None),
        ),
        coding_engine=PausingEngine(
            started=asyncio.Event(), release=asyncio.Event()
        ),
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )
    orchestrator.on_message = bridge.message_ready.emit
    orchestrator.on_engine_event = bridge.engine_event_ready.emit

    task = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="跑一下测试")
    )
    try:
        # 等待引擎发出 tool.started 且 UI 已收到流式推送
        engine: PausingEngine = orchestrator.coding_engine  # type: ignore[assignment]
        await asyncio.wait_for(engine._started.wait(), timeout=5)

        # 委派台词已上屏
        texts = [
            b.text_label.text() for b in window.character_messages.bubbles
        ]
        assert any("交给你" in t for t in texts), f"未见委派台词，实际：{texts}"

        # 运行中的工具卡片已出现
        assert window.tool_cards, "执行中途应已有工具卡片"
        card = next(iter(window.tool_cards.values()))
        assert card.status_label.text() == "running"
        assert card.toggle.text() == "演示文件操作"
    finally:
        engine._release.set()
        await task

    # 任务结束后卡片更新为 succeeded
    card = next(iter(window.tool_cards.values()))
    assert card.status_label.text() == "succeeded"
    # 角色结果回应已上屏（第二条角色消息）
    texts = [b.text_label.text() for b in window.character_messages.bubbles]
    assert any("我们继续" in t for t in texts)
