import pytest

from pair_harness.core.contracts import CharacterTurn, ProjectRef, TaskRequestDraft
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import (
    FixedDialogueModel,
    RecordingCodingEngine,
    deny_approval,
    make_context,
)


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
        dialogue_model=dialogue,
        coding_engine=RecordingCodingEngine(),
        approval_callback=deny_approval,
    )
    project = ProjectRef(project_id="p", name="p", root_path="C:\\work")

    outcome = await orchestrator.handle_character_input(
        conversation_id="origin-chat",
        text="请执行",
        context=make_context(project, conversation_id="origin-chat"),
    )

    assert {event.conversation_id for event in outcome.engine_events} == {"origin-chat"}
    assert {message.conversation_id for message in outcome.messages} == {"origin-chat"}
    assert {event.task_id for event in outcome.engine_events} == {outcome.task.task_id}

