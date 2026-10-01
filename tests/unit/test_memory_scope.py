from __future__ import annotations

import pytest
from pydantic import ValidationError

from pair_harness.core.memory import (
    MEMORY_INVALID,
    ConversationIdentity,
    MemoryScope,
    PairMemory,
    PairMemoryError,
    resolve_memory_scope,
)


def _identity(**overrides) -> ConversationIdentity:
    values = {
        "account_id": "acc-1",
        "project_id": "proj-1",
        "conversation_id": "conv-1",
        "pair_id": "phainon_ancient_machine",
        "character_card_id": None,
        "pair_character_id": "phainon",
        "assistant_identity": "ancient_machine",
    }
    values.update(overrides)
    return ConversationIdentity(**values)


@pytest.mark.parametrize(
    ("character_card_id", "character_ref"),
    [
        (None, "builtin:phainon"),
        # 绑定卡即使已被删除，聊天仍持久化原 card id，作用域不并入内置角色
        ("card-abc", "card:card-abc"),
    ],
    ids=["builtin", "card"],
)
def test_character_ref_follows_conversation_card_binding(
    character_card_id: str | None, character_ref: str
) -> None:
    scope = resolve_memory_scope(_identity(character_card_id=character_card_id))
    assert scope is not None
    assert scope.character_ref == character_ref
    assert scope.assistant_identity == "ancient_machine"


@pytest.mark.parametrize("project_id", [None, ""])
def test_chat_without_project_has_no_memory_scope(project_id: str | None) -> None:
    assert resolve_memory_scope(_identity(project_id=project_id)) is None


def test_same_project_pair_character_assistant_shares_scope_across_chats() -> None:
    chat_a = resolve_memory_scope(_identity(conversation_id="conv-a"))
    chat_b = resolve_memory_scope(_identity(conversation_id="conv-b"))
    assert chat_a is not None
    assert chat_a == chat_b


@pytest.mark.parametrize(
    "changed",
    [
        {"project_id": "proj-2"},
        {"pair_id": "march7_fourth_mirror"},
        {"character_card_id": "card-other"},
        {"assistant_identity": "fourth_mirror"},
        {"account_id": "acc-2"},
    ],
)
def test_any_scope_component_differs_means_no_sharing(changed: dict) -> None:
    base = resolve_memory_scope(_identity())
    other = resolve_memory_scope(_identity(**changed))
    assert base is not None and other is not None
    assert base != other


@pytest.mark.parametrize(
    "missing",
    [
        {"assistant_identity": "  "},
        {"account_id": ""},
        {"pair_id": ""},
        {"pair_character_id": ""},
    ],
    ids=["assistant_identity", "account_id", "pair_id", "builtin_character_id"],
)
def test_incomplete_identity_is_real_failure(missing: dict) -> None:
    with pytest.raises(PairMemoryError) as excinfo:
        resolve_memory_scope(_identity(**missing))
    assert excinfo.value.code == MEMORY_INVALID


def test_memory_scope_rejects_unknown_character_prefix() -> None:
    with pytest.raises(ValidationError):
        MemoryScope(
            account_id="a",
            project_id="p",
            pair_id="pair",
            character_ref="phainon",
            assistant_identity="ancient_machine",
        )


@pytest.mark.parametrize("content", [["not", "object"], "text"])
def test_memory_content_must_be_json_object(content: object) -> None:
    scope = resolve_memory_scope(_identity())
    with pytest.raises(ValidationError):
        PairMemory(memory_id="m", scope=scope, content=content)
