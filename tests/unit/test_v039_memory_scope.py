"""V0.3.9 契约 §1：长期记忆作用域解析与结构校验。

契约出处：``docs/plans/V0.3.9-契约冻结.md`` §1。

作用域必须包含 ``account_id + project_id + pair_id + character_ref +
assistant_identity``；``character_ref`` 由聊天解析，``assistant_identity``
来自权威搭档配置且不可由 ``pair_id`` 替代。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pair_harness.core.memory import (
    BUILTIN_CHARACTER_PREFIX,
    CARD_CHARACTER_PREFIX,
    MEMORY_INVALID,
    MEMORY_NOT_FOUND,
    MEMORY_SCOPE_MISMATCH,
    ConversationIdentity,
    MemoryError,
    MemoryScope,
    PairMemory,
    active_memories,
    character_ref_card_id,
    character_ref_for,
    is_card_character_ref,
    memory_event_payload,
    require_memory_found,
    require_same_scope,
    resolve_memory_scope,
)


def _identity(
    *,
    account_id: str = "acc-1",
    project_id: str | None = "proj-1",
    conversation_id: str = "conv-1",
    pair_id: str = "phainon_ancient_machine",
    character_card_id: str | None = None,
    pair_character_id: str = "phainon",
    assistant_identity: str = "ancient_machine",
) -> ConversationIdentity:
    return ConversationIdentity(
        account_id=account_id,
        project_id=project_id,
        conversation_id=conversation_id,
        pair_id=pair_id,
        character_card_id=character_card_id,
        pair_character_id=pair_character_id,
        assistant_identity=assistant_identity,
    )


def test_builtin_character_ref_uses_pair_character_id() -> None:
    scope = resolve_memory_scope(_identity())
    assert scope is not None
    assert scope.character_ref == f"{BUILTIN_CHARACTER_PREFIX}phainon"
    assert scope.assistant_identity == "ancient_machine"
    assert not is_card_character_ref(scope.character_ref)
    assert character_ref_card_id(scope.character_ref) is None


def test_custom_card_character_ref_uses_card_id() -> None:
    scope = resolve_memory_scope(_identity(character_card_id="card-abc"))
    assert scope is not None
    assert scope.character_ref == f"{CARD_CHARACTER_PREFIX}card-abc"
    assert character_ref_card_id(scope.character_ref) == "card-abc"


def test_deleted_card_keeps_card_scope_and_never_falls_back_to_builtin() -> None:
    """角色卡删除后原作用域保留为孤立数据，不得静默并入内置角色。"""
    scope = resolve_memory_scope(_identity(character_card_id="card-deleted"))
    assert scope is not None
    assert scope.character_ref == "card:card-deleted"
    assert scope.character_ref != "builtin:phainon"


def test_daily_chat_without_project_has_no_memory_scope() -> None:
    assert resolve_memory_scope(_identity(project_id=None)) is None
    assert resolve_memory_scope(_identity(project_id="")) is None


def test_assistant_identity_is_part_of_scope_key() -> None:
    first = resolve_memory_scope(_identity(assistant_identity="ancient_machine"))
    second = resolve_memory_scope(_identity(assistant_identity="fourth_mirror"))
    assert first is not None and second is not None
    assert first.scope_key != second.scope_key


def test_scope_key_is_stable_and_field_ordered() -> None:
    scope = resolve_memory_scope(_identity())
    assert scope is not None
    assert scope.scope_key == (
        '{"account_id":"acc-1","assistant_identity":"ancient_machine",'
        '"character_ref":"builtin:phainon","pair_id":"phainon_ancient_machine",'
        '"project_id":"proj-1"}'
    )


def test_same_project_pair_character_assistant_shares_scope_across_chats() -> None:
    """同项目同配对同角色同助手可跨聊天共享（契约 §1）。"""
    chat_a = resolve_memory_scope(_identity(conversation_id="conv-a"))
    chat_b = resolve_memory_scope(_identity(conversation_id="conv-b"))
    assert chat_a is not None and chat_b is not None
    assert chat_a.scope_key == chat_b.scope_key


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
def test_any_scope_component_differs_means_no_sharing(changed) -> None:
    base = resolve_memory_scope(_identity())
    other = resolve_memory_scope(_identity(**changed))
    assert base is not None and other is not None
    assert base.scope_key != other.scope_key


def test_missing_assistant_identity_is_real_failure() -> None:
    with pytest.raises(MemoryError) as excinfo:
        resolve_memory_scope(_identity(assistant_identity="  "))
    assert excinfo.value.code == MEMORY_INVALID


def test_missing_account_or_pair_is_real_failure() -> None:
    with pytest.raises(MemoryError):
        resolve_memory_scope(_identity(account_id=""))
    with pytest.raises(MemoryError):
        resolve_memory_scope(_identity(pair_id=""))


def test_character_ref_for_rejects_empty_builtin_id() -> None:
    with pytest.raises(MemoryError) as excinfo:
        character_ref_for(character_card_id=None, pair_character_id="")
    assert excinfo.value.code == MEMORY_INVALID


def test_memory_scope_rejects_unknown_prefix() -> None:
    with pytest.raises(ValidationError):
        MemoryScope(
            account_id="a",
            project_id="p",
            pair_id="pair",
            character_ref="phainon",
            assistant_identity="ancient_machine",
        )


def _scope(**overrides) -> MemoryScope:
    values = {
        "account_id": "acc-1",
        "project_id": "proj-1",
        "pair_id": "phainon_ancient_machine",
        "character_ref": "builtin:phainon",
        "assistant_identity": "ancient_machine",
    }
    values.update(overrides)
    return MemoryScope(**values)


def _memory(memory_id: str = "mem-1", *, status: str = "active", scope=None) -> PairMemory:
    return PairMemory(
        memory_id=memory_id,
        scope=scope or _scope(),
        content={"facts": ["用户喜欢简短的回复"]},
        status=status,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_memory_content_must_be_json_object() -> None:
    with pytest.raises(ValidationError):
        PairMemory(memory_id="m", scope=_scope(), content=["not", "object"])
    with pytest.raises(ValidationError):
        PairMemory(memory_id="m", scope=_scope(), content="text")


def test_active_memories_filters_deleted() -> None:
    active = _memory("m1")
    deleted = _memory("m2", status="deleted")
    assert active_memories((active, deleted)) == (active,)


def test_require_same_scope_raises_contract_code() -> None:
    require_same_scope(_scope(), _scope())
    with pytest.raises(MemoryError) as excinfo:
        require_same_scope(_scope(), _scope(project_id="proj-2"))
    assert excinfo.value.code == MEMORY_SCOPE_MISMATCH


def test_require_memory_found_raises_contract_code() -> None:
    memory = _memory()
    assert require_memory_found(memory, "mem-1") is memory
    with pytest.raises(MemoryError) as excinfo:
        require_memory_found(None, "mem-x")
    assert excinfo.value.code == MEMORY_NOT_FOUND


def test_memory_event_payload_carries_full_identity() -> None:
    payload = memory_event_payload(_memory(), conversation_id="conv-1")
    assert payload["account_id"] == "acc-1"
    assert payload["project_id"] == "proj-1"
    assert payload["pair_id"] == "phainon_ancient_machine"
    assert payload["character_ref"] == "builtin:phainon"
    assert payload["assistant_identity"] == "ancient_machine"
    assert payload["conversation_id"] == "conv-1"
    assert payload["status"] == "active"
    assert "content" not in payload
