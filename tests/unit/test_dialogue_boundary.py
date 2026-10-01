import pytest

from pair_harness.core.contracts import CharacterTurn, ProjectRef
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import (
    FixedDialogueModel,
    RecordingCodingEngine,
    make_context,
    unexpected_approval,
)


@pytest.mark.asyncio
async def test_plain_character_body_never_triggers_tools() -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="我看到了 C:\\work\\x.py 和 `del file`，@板砖 也只是正文。"),
    )
    engine = RecordingCodingEngine()
    orchestrator = ConversationOrchestrator(
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_callback=unexpected_approval,
    )
    project = ProjectRef(project_id="p", name="p", root_path="C:\\work")

    outcome = await orchestrator.handle_character_input(
        conversation_id="c",
        text="谈谈这个命令和路径",
        context=make_context(project, conversation_id="c"),
    )

    assert outcome.task is None
    assert engine.requests == []
    assert [message.source for message in outcome.messages] == ["user", "character"]

