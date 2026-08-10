import pytest

from pair_harness.core.contracts import ApprovalMode, CharacterTurn, ProjectRef, TaskRequestDraft
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

