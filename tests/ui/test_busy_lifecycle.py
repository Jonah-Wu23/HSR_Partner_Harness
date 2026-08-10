from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    DialogueEvent,
    EngineEvent,
    EngineSessionRef,
    ProjectRef,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.ports import DialogueModel
from pair_harness.ui.main_window import MainWindow
from tests.fakes import FixedDialogueModel


class ProbeEngine(ScriptedCodingEngine):
    """在 run_turn 执行期间调用探针，验证 busy 状态已生效。"""

    def __init__(self, probe) -> None:
        super().__init__()
        self._probe = probe

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self._probe()
        async for event in super().run_turn(session_ref, request):
            yield event


class PlainChatModel(DialogueModel):
    """只返回纯聊天台词，不带委派。"""

    async def stream_reply(self, request) -> AsyncIterator[DialogueEvent]:
        yield DialogueEvent(
            type="character.final",
            turn=CharacterTurn(speech="我在，慢慢说。", delegation=None),
        )


def make_orchestrator(
    window: MainWindow, dialogue_model: DialogueModel, engine: ScriptedCodingEngine
) -> ConversationOrchestrator:
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=dialogue_model,
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )
    orchestrator.on_execution_started = lambda: window.set_busy(True)
    orchestrator.on_execution_finished = lambda: window.set_busy(False)
    return orchestrator


@pytest.mark.asyncio
async def test_plain_chat_never_enters_busy(qtbot) -> None:
    """O1.4：纯角色聊天不触发 busy，取消按钮保持禁用。"""
    window = MainWindow()
    qtbot.addWidget(window)
    orchestrator = make_orchestrator(window, PlainChatModel(), ScriptedCodingEngine())

    await orchestrator.handle_character_input(conversation_id="c", text="陪我聊聊")

    assert not window.cancel_button.isEnabled()


@pytest.mark.asyncio
async def test_delegation_enters_busy_and_resets_after_execution(qtbot) -> None:
    """O1.4：产生委派的输入在执行期间 busy，任务结束后复位。"""
    window = MainWindow()
    qtbot.addWidget(window)
    busy_during_execution = []

    def probe() -> None:
        busy_during_execution.append(window.cancel_button.isEnabled())

    model = FixedDialogueModel(
        CharacterTurn(
            speech="古代机械，交给你了。",
            delegation=TaskRequestDraft(instructions="跑一下测试"),
        ),
        CharacterTurn(speech="做完了，我们继续。", delegation=None),
    )
    orchestrator = make_orchestrator(window, model, ProbeEngine(probe))

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="请让古代机械跑测试"
    )

    # 执行中探针观察到 busy；任务结束回调复位
    assert busy_during_execution == [True]
    assert outcome.receipt is not None
    assert not window.cancel_button.isEnabled()
