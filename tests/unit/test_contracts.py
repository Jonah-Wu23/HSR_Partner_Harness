import pytest
from pydantic import ValidationError

from pair_harness.core.contracts import (
    CharacterTurn,
    DialogueEvent,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    Message,
    MessageKind,
    MessageSource,
    TaskRequest,
    TaskRequestDraft,
)


def test_contracts_are_immutable() -> None:
    message = Message(
        conversation_id="conversation-1",
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="hello",
    )

    with pytest.raises(ValidationError):
        message.text = "changed"  # type: ignore[misc]


def test_dialogue_event_requires_matching_payload() -> None:
    turn = CharacterTurn(
        speech="交给古代机械吧。",
        delegation=TaskRequestDraft(instructions="创建 hello.txt"),
    )
    assert DialogueEvent(type="character.final", turn=turn).turn == turn

    with pytest.raises(ValidationError):
        DialogueEvent(type="speech.delta")


def test_task_and_engine_event_keep_identity_fields() -> None:
    task = TaskRequest(
        conversation_id="conversation-1",
        origin_message_id="message-1",
        instructions="创建 hello.txt",
    )
    event = EngineEvent(
        conversation_id=task.conversation_id,
        task_id=task.task_id,
        engine_turn_id="turn-1",
        sequence=0,
        type=EngineEventType.TURN_STARTED,
    )

    assert event.task_id == task.task_id
    assert event.type == "turn.started"


def test_engine_session_reference_is_opaque_to_application() -> None:
    ref = EngineSessionRef(engine_type="codex-app-server", opaque_ref="encoded-private-data")
    assert ref.model_dump() == {
        "engine_type": "codex-app-server",
        "opaque_ref": "encoded-private-data",
    }

