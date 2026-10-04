from __future__ import annotations

from pathlib import Path

import pytest

from pair_harness.config.pairs import list_pair_configs
from tests.service_helpers import call, expect_service_error

DEFAULT_PAIR_ID = "phainon_ancient_machine"
PNG_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "character_cards" / "白厄（3.4前）.png"
)


async def _publish_card(
    service, name: str, *, description: str = "设定", first_mes: str = "你好"
) -> str:
    card_id = (await call(service, f"{name}-draft", "card.create_draft", name=name))["card_id"]
    await call(
        service,
        f"{name}-update",
        "card.update",
        card_id=card_id,
        card={"name": name, "description": description, "first_mes": first_mes},
    )
    await call(service, f"{name}-publish", "card.publish", card_id=card_id)
    return card_id


def _binding_id(service, card_id: str) -> str:
    """发布或导入自动建立的默认搭档绑定 id。"""
    binding = service.binding_repository.find_binding(card_id, DEFAULT_PAIR_ID)
    assert binding is not None, "可用卡应当有默认搭档绑定"
    return binding.binding_id


async def _create_with_card(service, request_id: str, card_id: str):
    await call(
        service,
        request_id,
        "conversation.create",
        binding_id=_binding_id(service, card_id),
        reuse_active=True,
    )
    return service.store.get_conversation(service.current_conversation_id)


async def _new_conversation(service, request_id: str):
    await call(service, request_id, "conversation.create")
    return service.store.get_conversation(service.current_conversation_id)


async def _assembly(service, conversation_id: str) -> dict:
    return await call(
        service,
        "assembly",
        "diagnostics.prompt_assembly",
        conversation_id=conversation_id,
        include_hidden=True,
    )


async def test_published_card_enters_catalog_and_binds_new_conversation(service) -> None:
    description = "【设定】金色的麦田与不肯熄灭的火种。"
    first_mes = "*他抬眼看到你时，笑意像被瞬间点燃一样亮了起来。*"
    card_id = await _publish_card(
        service, "绑定角色", description=description, first_mes=first_mes
    )
    binding_id = _binding_id(service, card_id)

    catalog = await call(service, "1", "pair.list")
    option = next(
        item for item in catalog["pairs"] if item["character_card_id"] == card_id
    )
    assert option["binding_id"] == binding_id
    assert option["source"] == "card"
    assert option["character"]["name"] == "绑定角色"
    # 发布在统一事务里推进目录版本。
    assert catalog["catalog_version"] > 0

    conversation = await _create_with_card(service, "2", card_id)
    assert conversation.character_card_id == card_id
    assert conversation.binding_id == binding_id
    messages = service.store.load_conversation(conversation.conversation_id).messages
    assert [(m.source, m.text) for m in messages] == [("character", first_mes)]

    # 对话与诊断共用装配入口；装配保留作者原文。
    assembly = await _assembly(service, conversation.conversation_id)
    assert assembly["source"] == "card"
    assert {"name": "角色设定", "content": description} in [
        {"name": m["name"], "content": m["hidden_content"]} for m in assembly["modules"]
    ]


async def test_unbound_conversation_has_no_card_assembly(service) -> None:
    conversation_id = service.current_conversation_id
    assert service.store.get_conversation(conversation_id).character_card_id is None

    assembly = await _assembly(service, conversation_id)
    assert (assembly["source"], assembly["reason"], assembly["modules"]) == (
        "none",
        "character_card_unbound",
        [],
    )
    await expect_service_error(
        lambda: _assembly(service, "no-such-conversation"), "conversation_not_found"
    )


async def test_active_card_is_not_inherited_by_new_conversations(service) -> None:
    """已发布卡设为「使用中」也不再被新会话隐式继承。"""
    card_id = await _publish_card(service, "使用中的角色")
    await call(service, "1", "card.select_active", card_id=card_id)

    conversation = await _new_conversation(service, "2")
    assert conversation.character_card_id is None
    assert conversation.binding_id == f"builtin:{DEFAULT_PAIR_ID}"
    assert (await _assembly(service, conversation.conversation_id))["reason"] == (
        "character_card_unbound"
    )


async def test_conversation_keeps_its_own_binding_when_another_card_is_used(service) -> None:
    card_a = await _publish_card(service, "卡片甲")
    conv_a = await _create_with_card(service, "1", card_a)

    card_b = await _publish_card(service, "卡片乙")
    conv_b = await _create_with_card(service, "2", card_b)

    assert conv_a.character_card_id == card_a
    assert conv_b.character_card_id == card_b
    # 已有聊天的绑定是创建时的快照。
    assert service.store.get_conversation(conv_a.conversation_id).character_card_id == card_a


async def test_draft_card_has_no_binding_and_creates_no_conversation(service) -> None:
    draft = await call(service, "1", "card.create_draft", name="草稿角色")
    assert service.binding_repository.find_binding(draft["card_id"], DEFAULT_PAIR_ID) is None
    before = {
        conversation.conversation_id
        for conversation in service.store.list_conversations(service.current_project_id)
    }

    await expect_service_error(
        lambda: call(
            service, "2", "conversation.create", character_card_id=draft["card_id"]
        ),
        "binding_not_found",
    )
    after = {
        conversation.conversation_id
        for conversation in service.store.list_conversations(service.current_project_id)
    }
    assert after == before


async def test_open_deleted_binding_emits_card_missing(service) -> None:
    card_id = await _publish_card(service, "将删角色")
    conversation = await _create_with_card(service, "1", card_id)
    await call(service, "2", "card.delete", card_id=card_id, confirm=True)

    opened = await call(
        service, "3", "conversation.open", conversation_id=conversation.conversation_id
    )
    missing = service.event_log.payloads("conversation.card_missing")
    assert [(e["conversation_id"], e["card_id"]) for e in missing] == [
        (conversation.conversation_id, card_id)
    ]
    assert missing[0]["message"]

    # 聊天保留绑定快照，装配回退内置角色，不换成其他卡。
    assert opened["conversation"]["character_card_id"] == card_id
    assert opened["conversation"]["character_identity"]["missing"] is True
    assembly = await _assembly(service, conversation.conversation_id)
    assert (assembly["source"], assembly["reason"]) == ("none", "character_card_missing")


async def test_png_import_binds_and_broadcasts_one_catalog_version(service) -> None:
    """PNG 导入在一个事务里落卡、建绑定、推进版本，并广播两个目录事件。"""
    before = (await call(service, "0", "pair.list"))["catalog_version"]
    imported = await call(service, "1", "card.import_png", path=str(PNG_FIXTURE))

    card_events = service.event_log.payloads("card.updated")
    pair_events = service.event_log.payloads("pair.updated")
    assert len(card_events) == 1 and len(pair_events) == 1
    assert card_events[0]["card_id"] == imported["card_id"]
    version = card_events[0]["catalog_version"]
    assert pair_events[0]["catalog_version"] == version > before

    listing = await call(service, "2", "pair.list")
    assert listing["catalog_version"] == version
    option = next(
        item for item in listing["pairs"] if item["character_card_id"] == imported["card_id"]
    )
    assert option["pair_id"] == DEFAULT_PAIR_ID
    assert option["character"]["avatar_ref"]

    avatar = await call(service, "3", "card.avatar", card_id=imported["card_id"])
    assert avatar["avatar"]["mime_type"] == "image/png"
    await expect_service_error(
        lambda: call(service, "4", "card.avatar", card_id="no-such-card"),
        "card_not_found",
    )


async def test_profile_change_and_archive_broadcast_their_own_events(service) -> None:
    """改名只发 card.updated；归档让目录移除并只发 pair.updated。"""
    card_id = await _publish_card(service, "事件角色")
    service.event_log.items.clear()

    await call(
        service,
        "1",
        "card.update",
        card_id=card_id,
        card={"name": "事件角色改名", "first_mes": "你好"},
    )
    assert [event["card_id"] for event in service.event_log.payloads("card.updated")] == [
        card_id
    ]
    assert service.event_log.payloads("pair.updated") == []
    renamed = await call(service, "2", "pair.list")
    assert next(
        item for item in renamed["pairs"] if item["character_card_id"] == card_id
    )["character"]["name"] == "事件角色改名"

    service.event_log.items.clear()
    await call(service, "3", "card.archive", card_id=card_id)
    assert service.event_log.payloads("card.updated") == []
    assert len(service.event_log.payloads("pair.updated")) == 1
    archived = await call(service, "4", "pair.list")
    assert all(item["character_card_id"] != card_id for item in archived["pairs"])

    service.event_log.items.clear()
    await call(service, "5", "card.unarchive", card_id=card_id)
    assert len(service.event_log.payloads("pair.updated")) == 1
    restored = await call(service, "6", "pair.list")
    assert any(item["character_card_id"] == card_id for item in restored["pairs"])


async def test_png_import_failure_leaves_no_card_binding_or_event(service) -> None:
    """头像资产写入失败时回滚数据库并清理本次新增资产，不广播任何事件。"""
    asset_root = service.store.database.parent / "character_assets"
    asset_root.parent.mkdir(parents=True, exist_ok=True)
    # 资产目录位置放普通文件：store_asset 的目录创建必然失败（真实 OS 错误）。
    asset_root.write_text("占位文件", encoding="utf-8")
    before_cards = [
        card.card_id for card in service.card_repository.list_cards(include_archived=True)
    ]
    before_version = service.binding_repository.catalog_version()
    service.event_log.items.clear()

    with pytest.raises(FileExistsError):
        await call(service, "1", "card.import_png", path=str(PNG_FIXTURE))

    assert [
        card.card_id for card in service.card_repository.list_cards(include_archived=True)
    ] == before_cards
    assert service.binding_repository.catalog_version() == before_version
    assert [
        binding
        for binding in service.binding_repository.list_bindings(include_disabled=True)
        if binding.character_card_id is not None
    ] == []
    assert service.event_log.payloads("card.updated") == []
    assert service.event_log.payloads("pair.updated") == []


async def test_rebinding_switches_catalog_assistant_and_new_conversation(service) -> None:
    """update_base_pair 后目录项助手实时变化，按同一 binding 新建会话用新搭档。"""
    first_mes = "换绑后的开场白。"
    card_id = await _publish_card(service, "换绑角色", first_mes=first_mes)
    binding_id = _binding_id(service, card_id)

    before = await call(service, "1", "pair.list")
    before_option = next(
        item for item in before["pairs"] if item["character_card_id"] == card_id
    )
    assert before_option["pair_id"] == DEFAULT_PAIR_ID
    original = await call(service, "2", "conversation.create", binding_id=binding_id)
    original_conversation_id = original["current_conversation_id"]
    assert original["current_conversation"]["pair_id"] == DEFAULT_PAIR_ID

    service.binding_repository.update_base_pair(binding_id, "firefly_sam")
    service.store.connection.commit()

    rebound = await call(service, "3", "pair.list")
    rebound_option = next(
        item for item in rebound["pairs"] if item["character_card_id"] == card_id
    )
    assert rebound_option["binding_id"] == binding_id
    assert rebound_option["pair_id"] == "firefly_sam"
    firefly = next(
        pair for pair in list_pair_configs() if pair.pair_id == "firefly_sam"
    )
    assert rebound_option["assistant"] == {
        "id": firefly.assistant.id,
        "name": firefly.assistant.name,
        "voice_id": firefly.assistant.voice_id,
    }

    created = await call(service, "4", "conversation.create", binding_id=binding_id)
    conversation = service.store.get_conversation(created["current_conversation_id"])
    assert conversation.conversation_id != original_conversation_id
    assert conversation.binding_id == binding_id
    assert conversation.pair_id == "firefly_sam"
    assert conversation.character_card_id == card_id
    messages = service.store.load_conversation(conversation.conversation_id).messages
    assert [(message.source, message.text) for message in messages] == [
        ("character", first_mes)
    ]
    # 换绑只影响新会话，既有会话保留创建时的搭档快照。
    assert service.store.get_conversation(original_conversation_id).pair_id == DEFAULT_PAIR_ID


async def test_card_bound_to_three_assistants_creates_consistent_conversations(service) -> None:
    """同一张卡绑定三个内置搭档：目录项与逐项会话的助手身份一致。"""
    card_id = await _publish_card(service, "三助手角色", first_mes="开场。")
    pairs = {pair.pair_id: pair for pair in list_pair_configs()}
    bindings: dict[str, str] = {}
    for pair_id in pairs:
        binding = service.binding_repository.find_binding(card_id, pair_id)
        if binding is None:
            binding = service.binding_repository.create_binding(card_id, pair_id)
            service.binding_repository.bump_catalog_version()
            service.store.connection.commit()
        bindings[pair_id] = binding.binding_id

    listing = await call(service, "1", "pair.list")
    options = [
        item for item in listing["pairs"] if item["character_card_id"] == card_id
    ]
    assert {item["binding_id"] for item in options} == set(bindings.values())

    for pair_id, binding_id in bindings.items():
        option = next(item for item in options if item["binding_id"] == binding_id)
        assert option["pair_id"] == pair_id
        assert option["assistant"]["name"] == pairs[pair_id].assistant.name
        created = await call(
            service, f"create-{pair_id}", "conversation.create", binding_id=binding_id
        )
        conversation = service.store.get_conversation(created["current_conversation_id"])
        assert conversation.binding_id == binding_id
        assert conversation.pair_id == pair_id
        assert conversation.character_card_id == card_id
        assert created["current_conversation"]["character_identity"]["name"] == "三助手角色"
        assert created["pair"]["pair_id"] == pair_id
        assert created["pair"]["assistant"]["name"] == pairs[pair_id].assistant.name

