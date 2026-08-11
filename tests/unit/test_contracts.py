import collections.abc
import typing

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
    PendingOperation,
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


def test_message_payload_is_declared_read_only_mapping() -> None:
    # O4.4：payload 注解为 Mapping——只读约定；内容本身仍是 dict，
    # 需要改写时先拷贝（frozen 模型禁止直接赋值）。
    hint = typing.get_type_hints(Message)["payload"]
    assert typing.get_origin(hint) in (typing.Mapping, collections.abc.Mapping)
    message = Message(
        conversation_id="conversation-1",
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="hello",
    )
    assert message.payload == {}
    with pytest.raises(ValidationError):
        message.payload = {"key": "value"}  # type: ignore[misc]


def test_message_uses_engine_turn_id_field_name() -> None:
    # O4.4：turn_id 更名为 engine_turn_id；extra="forbid" 下旧字段名
    # 会直接校验失败，由存储层做旧库兼容（见 sqlite_store._parse_message）。
    message = Message(
        conversation_id="conversation-1",
        pair_id="phainon_ancient_machine",
        source=MessageSource.ASSISTANT,
        kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
        text="正在处理",
        engine_turn_id="turn-7",
    )
    assert message.engine_turn_id == "turn-7"
    with pytest.raises(ValidationError):
        Message(
            conversation_id="conversation-1",
            pair_id="phainon_ancient_machine",
            source=MessageSource.ASSISTANT,
            kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
            text="正在处理",
            turn_id="turn-7",  # type: ignore[call-arg]
        )


def test_pending_operation_paths_are_immutable_tuple() -> None:
    # O4.4：paths 收敛为 tuple；传入 list 时由 pydantic 自动转换，
    # 后续不再可能被调用方就地修改。
    op = PendingOperation(
        tool_kind="file_write",
        paths=["docs/a.md", "docs/b.md"],
    )
    assert isinstance(op.paths, tuple)
    assert op.paths == ("docs/a.md", "docs/b.md")
    with pytest.raises(ValidationError):
        op.paths = ["docs/c.md"]  # type: ignore[misc]

