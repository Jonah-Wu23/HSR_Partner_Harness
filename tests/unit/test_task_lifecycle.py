from collections.abc import AsyncIterator

import pytest

from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    EngineEvent,
    EngineEventType,
    ProjectRef,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel, RecordingCodingEngine


@pytest.mark.asyncio
async def test_tool_failure_overrides_assistant_success_text() -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(
            speech="交给古代机械。",
            delegation=TaskRequestDraft(instructions="执行演示"),
        ),
        CharacterTurn(speech="这次没有成功，我会陪你看清问题。"),
    )
    engine = RecordingCodingEngine(fail_tool=True)
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\work"),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="请执行")

    assert outcome.receipt is not None
    assert outcome.receipt.status == "failed"
    assert outcome.receipt.errors == ("模拟工具失败",)
    assert outcome.messages[-1].text.startswith("这次没有成功")


class RecoveringCodingEngine(RecordingCodingEngine):
    """工具步骤失败后仍由引擎正常结束 turn。"""

    async def run_turn(
        self, session_ref, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        async for event in super().run_turn(session_ref, request):
            if event.type == EngineEventType.TURN_FAILED:
                yield event.model_copy(update={"type": EngineEventType.TURN_COMPLETED})
            else:
                yield event


@pytest.mark.asyncio
async def test_intermediate_tool_failure_does_not_override_successful_turn() -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(
            speech="交给古代机械。",
            delegation=TaskRequestDraft(instructions="执行演示"),
        ),
        CharacterTurn(speech="最终结果已经完成。"),
    )
    engine = RecoveringCodingEngine(fail_tool=True)
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\work"),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="请执行")

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    assert outcome.receipt.errors == ("模拟工具失败",)
    assert outcome.messages[-1].text == "最终结果已经完成。"


@pytest.mark.asyncio
async def test_direct_input_becomes_same_formal_task() -> None:
    dialogue = FixedDialogueModel(CharacterTurn(speech="完成了。"))
    engine = RecordingCodingEngine()
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\work"),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    outcome = await orchestrator.handle_direct_input(conversation_id="c", text="运行测试")

    assert outcome.task == engine.requests[0]
    assert outcome.task.origin_message_id == outcome.messages[0].message_id
