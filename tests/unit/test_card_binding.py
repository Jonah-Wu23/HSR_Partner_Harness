from __future__ import annotations

from tests.service_helpers import call, expect_service_error


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


async def test_new_conversation_snapshots_active_card_and_inserts_greeting(service) -> None:
    description = "【设定】金色的麦田与不肯熄灭的火种。"
    first_mes = "*他抬眼看到你时，笑意像被瞬间点燃一样亮了起来。*"
    card_id = await _publish_card(
        service, "绑定角色", description=description, first_mes=first_mes
    )
    await call(service, "1", "card.select_active", card_id=card_id)

    conversation = await _new_conversation(service, "2")
    assert conversation.character_card_id == card_id
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


async def test_switching_active_only_affects_future_conversations(service) -> None:
    card_a = await _publish_card(service, "卡片甲")
    await call(service, "1", "card.select_active", card_id=card_a)
    conv_a = await _new_conversation(service, "2")

    card_b = await _publish_card(service, "卡片乙")
    await call(service, "3", "card.select_active", card_id=card_b)
    conv_b = await _new_conversation(service, "4")

    assert conv_a.character_card_id == card_a
    assert conv_b.character_card_id == card_b
    # 已有聊天的绑定是创建时的快照。
    assert service.store.get_conversation(conv_a.conversation_id).character_card_id == card_a


async def test_draft_active_card_does_not_bind_new_conversations(service) -> None:
    draft = await call(service, "1", "card.create_draft", name="草稿角色")
    await call(service, "2", "card.select_active", card_id=draft["card_id"])

    conversation = await _new_conversation(service, "3")
    assert conversation.character_card_id is None
    assert (await _assembly(service, conversation.conversation_id))["reason"] == (
        "character_card_unbound"
    )


async def test_open_deleted_binding_emits_card_missing(service) -> None:
    card_id = await _publish_card(service, "将删角色")
    await call(service, "1", "card.select_active", card_id=card_id)
    conversation = await _new_conversation(service, "2")
    await call(service, "3", "card.delete", card_id=card_id, confirm=True)

    opened = await call(
        service, "4", "conversation.open", conversation_id=conversation.conversation_id
    )
    missing = service.event_log.payloads("conversation.card_missing")
    assert [(e["conversation_id"], e["card_id"]) for e in missing] == [
        (conversation.conversation_id, card_id)
    ]
    assert missing[0]["message"]

    # 聊天保留绑定快照，装配回退内置角色，不换成其他卡。
    assert opened["conversation"]["character_card_id"] == card_id
    assembly = await _assembly(service, conversation.conversation_id)
    assert (assembly["source"], assembly["reason"]) == ("none", "character_card_missing")
