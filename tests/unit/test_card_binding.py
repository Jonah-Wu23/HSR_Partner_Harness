from __future__ import annotations

import sqlite3
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


def _drop_binding_row(service, card_id: str) -> None:
    """造出 v14 迁移留下的状态：卡有归档/可用状态但没有默认绑定。"""
    service.store.connection.execute(
        "DELETE FROM partner_bindings WHERE character_card_id = ?", (card_id,)
    )
    service.store.connection.commit()


async def test_unarchive_repairs_missing_binding_in_one_transaction(service) -> None:
    """归档卡缺绑定时，恢复在同一事务里补建绑定并推进一次目录版本。"""
    card_id = await _publish_card(service, "旧库归档卡")
    await call(service, "1", "card.archive", card_id=card_id)
    _drop_binding_row(service, card_id)
    before = service.binding_repository.catalog_version()
    service.event_log.items.clear()

    restored = await call(service, "2", "card.unarchive", card_id=card_id)
    assert restored == {"card_id": card_id, "archived": False}
    binding = service.binding_repository.find_binding(card_id, DEFAULT_PAIR_ID)
    assert binding is not None
    assert service.binding_repository.catalog_version() == before + 1
    assert len(service.event_log.payloads("pair.updated")) == 1

    # 恢复后的卡真实可用：目录里可选，按该绑定能建出会话。
    catalog = await call(service, "3", "pair.list")
    option = next(item for item in catalog["pairs"] if item["character_card_id"] == card_id)
    assert option["binding_id"] == binding.binding_id
    created = await call(service, "4", "conversation.create", binding_id=binding.binding_id)
    assert created["current_conversation"]["character_card_id"] == card_id

    # 重复恢复幂等：不建第二行绑定、不推进版本、不重复广播。
    service.event_log.items.clear()
    await call(service, "5", "card.unarchive", card_id=card_id)
    rows = [
        item
        for item in service.binding_repository.list_bindings(include_disabled=True)
        if item.character_card_id == card_id
    ]
    assert len(rows) == 1
    assert service.binding_repository.catalog_version() == before + 1
    assert service.event_log.items == []


async def test_publish_rolls_back_when_binding_creation_fails(service) -> None:
    """绑定创建失败：整笔回滚到 draft，无绑定、版本不变、零事件，重试后成功。"""
    card_id = (await call(service, "0", "card.create_draft", name="注入角色"))["card_id"]
    await call(
        service,
        "0b",
        "card.update",
        card_id=card_id,
        card={"name": "注入角色", "first_mes": "你好"},
    )
    before = service.binding_repository.catalog_version()
    service.event_log.items.clear()
    service.store.connection.execute(
        "CREATE TRIGGER fail_binding_insert BEFORE INSERT ON partner_bindings "
        "BEGIN SELECT RAISE(ABORT, '绑定写入被拦截'); END"
    )
    service.store.connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="绑定写入被拦截"):
        await call(service, "1", "card.publish", card_id=card_id)

    assert service.card_repository.get_card(card_id).state == "draft"
    assert service.binding_repository.find_binding(card_id, DEFAULT_PAIR_ID) is None
    assert service.binding_repository.catalog_version() == before
    assert service.event_log.items == []

    service.store.connection.execute("DROP TRIGGER fail_binding_insert")
    service.store.connection.commit()
    published = await call(service, "2", "card.publish", card_id=card_id)
    assert published == {"card_id": card_id, "state": "saved"}
    assert service.binding_repository.find_binding(card_id, DEFAULT_PAIR_ID) is not None
    assert service.binding_repository.catalog_version() == before + 1
    assert len(service.event_log.payloads("card.updated")) == 1
    assert len(service.event_log.payloads("pair.updated")) == 1


async def test_publish_rolls_back_when_catalog_version_bump_fails(service) -> None:
    """版本递增失败：状态跃迁与刚建的绑定一起回滚，重试后卡与绑定同时成立。"""
    card_id = (await call(service, "0", "card.create_draft", name="注入角色"))["card_id"]
    await call(
        service,
        "0b",
        "card.update",
        card_id=card_id,
        card={"name": "注入角色", "first_mes": "你好"},
    )
    missing = service.store.connection.execute(
        "SELECT count(*) FROM app_state WHERE key = 'partner_catalog.version'"
    ).fetchone()[0]
    assert missing == 0, "注入前提：目录版本行尚不存在，写入走 INSERT"
    service.event_log.items.clear()
    service.store.connection.execute(
        "CREATE TRIGGER fail_catalog_version BEFORE INSERT ON app_state "
        "WHEN NEW.key = 'partner_catalog.version' "
        "BEGIN SELECT RAISE(ABORT, '目录版本写入被拦截'); END"
    )
    service.store.connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="目录版本写入被拦截"):
        await call(service, "1", "card.publish", card_id=card_id)

    assert service.card_repository.get_card(card_id).state == "draft"
    assert service.binding_repository.find_binding(card_id, DEFAULT_PAIR_ID) is None
    assert service.binding_repository.catalog_version() == 0
    assert service.event_log.items == []

    service.store.connection.execute("DROP TRIGGER fail_catalog_version")
    service.store.connection.commit()
    assert (await call(service, "2", "card.publish", card_id=card_id))["state"] == "saved"
    assert service.binding_repository.find_binding(card_id, DEFAULT_PAIR_ID) is not None
    assert service.binding_repository.catalog_version() == 1


async def test_republish_repairs_missing_binding_and_stays_idempotent(service) -> None:
    """重复发布：已有绑定原样返回；缺绑定则补建并推进一次版本后广播。"""
    card_id = await _publish_card(service, "重复发布角色")
    version = service.binding_repository.catalog_version()
    service.event_log.items.clear()

    again = await call(service, "1", "card.publish", card_id=card_id)
    assert again == {"card_id": card_id, "state": "saved"}
    assert service.binding_repository.catalog_version() == version
    assert service.event_log.items == []

    _drop_binding_row(service, card_id)
    repaired = await call(service, "2", "card.publish", card_id=card_id)
    assert repaired == {"card_id": card_id, "state": "saved"}
    assert service.binding_repository.find_binding(card_id, DEFAULT_PAIR_ID) is not None
    assert service.binding_repository.catalog_version() == version + 1
    assert len(service.event_log.payloads("card.updated")) == 1
    assert len(service.event_log.payloads("pair.updated")) == 1

    service.event_log.items.clear()
    await call(service, "3", "card.publish", card_id=card_id)
    assert [
        item
        for item in service.binding_repository.list_bindings(include_disabled=True)
        if item.character_card_id == card_id
    ]
    assert service.binding_repository.catalog_version() == version + 1
    assert service.event_log.items == []


def _changed_conversation_ids(service) -> list[str]:
    return [
        payload["conversation"]["conversation_id"]
        for payload in service.event_log.payloads("conversation.changed")
    ]


async def test_card_entity_changes_broadcast_conversation_identity(service) -> None:
    """改名、换头像、去头像与删除都让已有聊天拿到新身份，删除后 missing。"""
    card_id = await _publish_card(service, "旧名字", first_mes="你好")
    conversation = await _create_with_card(service, "1", card_id)
    conversation_id = conversation.conversation_id

    service.event_log.items.clear()
    await call(
        service,
        "2",
        "card.update",
        card_id=card_id,
        card={"name": "新名字", "first_mes": "你好"},
    )
    assert _changed_conversation_ids(service) == [conversation_id]
    identity = service.event_log.payloads("conversation.changed")[0]["conversation"][
        "character_identity"
    ]
    assert identity["name"] == "新名字"
    assert identity["missing"] is False

    service.event_log.items.clear()
    await call(service, "3", "card.set_avatar", card_id=card_id, path=str(PNG_FIXTURE))
    avatar_ref = service.event_log.payloads("conversation.changed")[0]["conversation"][
        "character_identity"
    ]["avatar_ref"]
    assert avatar_ref

    service.event_log.items.clear()
    await call(service, "4", "card.remove_avatar", card_id=card_id)
    assert (
        service.event_log.payloads("conversation.changed")[0]["conversation"][
            "character_identity"
        ]["avatar_ref"]
        is None
    )

    # 归档卡不在目录里（不发 pair.updated），但已有聊天照常拿到 missing 身份。
    await call(service, "5", "card.archive", card_id=card_id)
    service.event_log.items.clear()
    await call(service, "6", "card.delete", card_id=card_id, confirm=True)
    assert service.event_log.payloads("pair.updated") == []
    assert _changed_conversation_ids(service) == [conversation_id]
    deleted = service.event_log.payloads("conversation.changed")[0]["conversation"]
    assert deleted["character_identity"]["missing"] is True
    assert deleted["character_card_id"] == card_id


async def test_identity_broadcast_reaches_archived_conversations(service) -> None:
    """已归档会话仍会被改名或删除触发的 conversation.changed 覆盖到。"""
    card_id = await _publish_card(service, "待删角色", first_mes="你好")
    conversation = await _create_with_card(service, "1", card_id)
    # 归档当前会话会把界面切到新建的内置会话，原会话留在归档列表里。
    await call(service, "2", "conversation.archive", conversation_id=conversation.conversation_id)
    service.event_log.items.clear()

    await call(service, "3", "card.delete", card_id=card_id, confirm=True)
    changed = [
        payload
        for payload in service.event_log.payloads("conversation.changed")
        if payload["conversation"]["conversation_id"] == conversation.conversation_id
    ]
    assert len(changed) == 1
    assert changed[0]["conversation"]["archived"] is True
    assert changed[0]["conversation"]["character_identity"]["missing"] is True

