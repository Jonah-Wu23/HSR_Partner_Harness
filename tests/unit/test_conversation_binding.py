import pytest

from pair_harness.core.contracts import CharacterTurn, ProjectRef, TaskRequestDraft
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel, RecordingCodingEngine


@pytest.mark.asyncio
async def test_engine_events_are_rebound_to_origin_conversation() -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(
            speech="交给古代机械。",
            delegation=TaskRequestDraft(instructions="执行"),
        ),
        CharacterTurn(speech="完成。"),
    )
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\work"),
        dialogue_model=dialogue,
        coding_engine=RecordingCodingEngine(),
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="origin-chat", text="请执行"
    )

    assert {event.conversation_id for event in outcome.engine_events} == {"origin-chat"}
    assert {message.conversation_id for message in outcome.messages} == {"origin-chat"}
    assert {event.task_id for event in outcome.engine_events} == {outcome.task.task_id}

