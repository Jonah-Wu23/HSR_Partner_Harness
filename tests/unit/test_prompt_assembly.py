from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pair_harness.character_cards.models import CharacterCard, HsrExtension
from pair_harness.core.character_prompt_assembler import assemble_turn_prompt
from pair_harness.core.memory import MemoryScope, PairMemory
from pair_harness.core.summary import ConversationSummary
from pair_harness.desktop_backend.protocol import encode_message, response_ok
from pair_harness.storage.records import ConversationSummary as StorageSummary
from tests.service_helpers import call, expect_service_error

PAIR_ID = "phainon_ancient_machine"
CARD_DESCRIPTION = "【设定】金色麦田与不肯熄灭的火种。"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _memory(memory_id: str, content: dict, *, status: str = "active") -> PairMemory:
    return PairMemory(
        memory_id=memory_id,
        scope=MemoryScope(
            account_id="acc-1",
            project_id="proj-1",
            pair_id=PAIR_ID,
            character_ref="builtin:phainon",
            assistant_identity="ancient_machine",
        ),
        content=content,
        status=status,
        updated_at=_NOW,
    )


def _summary(content: dict) -> ConversationSummary:
    return ConversationSummary(
        summary_id="s1",
        conversation_id="conv-1",
        status="completed",
        covers_from_message_id="m1",
        covers_to_message_id="m3",
        covers_message_count=3,
        content=content,
    )


def test_summary_and_memory_modules_sit_between_card_fields_and_event_trigger() -> None:
    card = CharacterCard(
        name="白厄",
        description="角色设定原文",
        system_prompt="系统提示",
        hsr=HsrExtension(
            event_system={
                "任务": {
                    "runtime_trigger": {"kind": "turn", "turn": 1},
                    "content": "第一回合事件原文",
                }
            }
        ),
    )
    result = assemble_turn_prompt(
        card,
        [],
        turn_index=1,
        summary=_summary({"剧情": "两人在雨夜相遇", "约定": ["不再提旧事"]}),
        memories=(_memory("mem-1", {"喜好": "安静"}),),
    )
    assert [module.kind for module in result.modules] == [
        "description",
        "system_prompt",
        "hsr.event_system",
        "chat_summary",
        "pair_memory",
        "hsr.event_trigger",
    ]
    summary_module, memory_module = result.modules[3], result.modules[4]
    assert summary_module.source_field == "summary:s1"
    # 模型内容原样呈现
    assert "两人在雨夜相遇" in summary_module.content
    assert "不再提旧事" in summary_module.content
    assert "安静" in memory_module.content
    assert result.system_text[summary_module.char_start : summary_module.char_end].startswith(
        "## 聊天摘要"
    )
    assert result.diagnostics["summary"]["summary_id"] == "s1"
    assert result.diagnostics["memory"]["memory_ids"] == ["mem-1"]


@pytest.mark.parametrize(
    ("summary", "memories"),
    [
        (None, ()),
        (
            ConversationSummary(
                summary_id="s1",
                conversation_id="conv-1",
                status="failed",
                error_code="summary_timeout",
                error="provider timeout",
            ),
            (),
        ),
        (_summary({}), (_memory("mem-empty", {}),)),
        (None, (_memory("mem-deleted", {"保留": "否"}, status="deleted"),)),
    ],
    ids=["nothing", "failed_summary", "empty_content", "deleted_memory"],
)
def test_summary_and_memory_without_injectable_content_add_no_module(
    summary: ConversationSummary | None, memories: tuple[PairMemory, ...]
) -> None:
    result = assemble_turn_prompt(
        CharacterCard(name="白厄", description="角色设定原文"),
        [],
        summary=summary,
        memories=memories,
    )
    assert [module.kind for module in result.modules] == ["description"]
    assert result.diagnostics["summary"] == {
        "injected": False,
        "summary_id": None,
        "char_count": 0,
    }
    assert result.diagnostics["memory"] == {
        "injected": False,
        "count": 0,
        "memory_ids": [],
        "char_count": 0,
    }


async def _publish_card(service) -> str:
    created = await call(service, "card-draft", "card.create_draft", name="装配角色")
    card_id = created["card_id"]
    await call(
        service,
        "card-update",
        "card.update",
        card_id=card_id,
        card={
            "name": "装配角色",
            "description": CARD_DESCRIPTION,
            "first_mes": "晚上好呀。",
        },
    )
    await call(service, "card-publish", "card.publish", card_id=card_id)
    return card_id


async def _bind_card_conversation(service) -> str:
    card_id = await _publish_card(service)
    binding = service.binding_repository.find_binding(card_id, PAIR_ID)
    assert binding is not None, "发布后的卡应有默认搭档绑定"
    await call(
        service,
        "conversation-create",
        "conversation.create",
        project_id=service.current_project_id,
        binding_id=binding.binding_id,
    )
    return service.current_conversation_id


def _insert_completed_summary(service, conversation_id: str, content: dict) -> str:
    """落库一条覆盖会话全部已有消息的 completed 摘要。"""
    messages = service.store.load_conversation(conversation_id).messages
    assert messages, "写摘要前会话必须有真实消息"
    summary_id = f"summary-{conversation_id}"
    service.store.upsert_summary(
        StorageSummary(
            summary_id=summary_id,
            conversation_id=conversation_id,
            covers_from_message_id=messages[0].message_id,
            covers_to_message_id=messages[-1].message_id,
            covers_message_count=len(messages),
            content=json.dumps(content, ensure_ascii=False),
            status="completed",
        )
    )
    return summary_id


async def _prompt_assembly(service, conversation_id: str, **params) -> dict:
    return await call(
        service,
        "prompt-assembly",
        "diagnostics.prompt_assembly",
        conversation_id=conversation_id,
        **params,
    )


async def test_bound_card_assembly_injects_summary_and_memory(service) -> None:
    conversation_id = await _bind_card_conversation(service)
    summary_id = _insert_completed_summary(
        service, conversation_id, {"剧情": "两人在雨夜相遇"}
    )
    await call(
        service,
        "memory-create",
        "memory.create",
        conversation_id=conversation_id,
        content={"喜好": "安静的地方"},
    )

    plain = await _prompt_assembly(service, conversation_id)
    assert (plain["source"], plain["reason"]) == ("card", None)
    assert [module["name"] for module in plain["modules"]] == ["角色设定", "聊天摘要", "配对记忆"]
    assert [module["memory_injected"] for module in plain["modules"]] == [False, True, True]
    # 默认不返回隐藏原文
    assert all(module["hidden_content"] is None for module in plain["modules"])
    assert any(summary_id in line for line in plain["diagnostics"])
    encode_message(response_ok("prompt-assembly", plain))

    hidden = await _prompt_assembly(service, conversation_id, include_hidden=True)
    contents = {module["name"]: module["hidden_content"] for module in hidden["modules"]}
    assert CARD_DESCRIPTION in contents["角色设定"]
    assert "两人在雨夜相遇" in contents["聊天摘要"]
    assert "安静的地方" in contents["配对记忆"]


async def test_unbound_conversation_assembles_builtin_character_with_summary_and_memory(
    service,
) -> None:
    conversation_id = service.current_conversation_id
    await service.orchestrator.submit_user_message(
        conversation_id=conversation_id, text="我们约定过一件事", target="character", pair_id=PAIR_ID
    )
    _insert_completed_summary(service, conversation_id, {"长期约定": "不再提旧事"})
    created = await call(
        service,
        "memory-create",
        "memory.create",
        conversation_id=conversation_id,
        content={"称呼": "并肩的伙伴"},
    )
    assert created["memory"]["character_ref"] == "builtin:phainon"

    result = await _prompt_assembly(service, conversation_id, include_hidden=True)
    assert result["source"] == "builtin"
    contents = {module["name"]: module["hidden_content"] for module in result["modules"]}
    assert list(contents) == ["角色设定", "聊天摘要", "配对记忆"]
    assert "你扮演白厄" in contents["角色设定"]
    assert "不再提旧事" in contents["聊天摘要"]
    assert "并肩的伙伴" in contents["配对记忆"]


async def test_conversation_without_project_assembles_card_without_memory(service) -> None:
    card_id = await _publish_card(service)
    conversation = service.store.create_conversation(
        pair_id=PAIR_ID,
        project_id=None,
        account_id=service.current_account_id,
        character_card_id=card_id,
    )
    # 无项目会话没有记忆作用域：记忆命令如实报错，装配按无记忆继续
    await expect_service_error(
        lambda: call(
            service, "memory-list", "memory.list", conversation_id=conversation.conversation_id
        ),
        "memory_invalid",
    )
    result = await _prompt_assembly(service, conversation.conversation_id, include_hidden=True)
    assert result["source"] == "card"
    assert [module["name"] for module in result["modules"]] == ["角色设定"]
    assert CARD_DESCRIPTION in result["modules"][0]["hidden_content"]


async def _unbound_conversation(service) -> str:
    return service.current_conversation_id


async def _conversation_bound_to_empty_draft(service) -> str:
    # 装配层只读会话上的角色卡 id；草稿没有绑定、无法经命令建会话，直接落一条会话。
    draft = await call(service, "card-draft", "card.create_draft", name="空草稿卡")
    conversation = service.store.create_conversation(
        pair_id=PAIR_ID,
        project_id=service.current_project_id,
        account_id=service.current_account_id,
        character_card_id=draft["card_id"],
    )
    return conversation.conversation_id


async def _conversation_bound_to_archived_card(service) -> str:
    cards = await call(service, "card-list", "card.list")
    builtin = next(item for item in cards["cards"] if str(item["card_id"]).startswith("builtin:"))
    copy = await call(service, "card-duplicate", "card.duplicate", card_id=builtin["card_id"])
    binding = service.binding_repository.find_binding(copy["card_id"], PAIR_ID)
    assert binding is not None, "复制出的可用卡应有默认搭档绑定"
    await call(
        service, "conversation-create", "conversation.create", binding_id=binding.binding_id
    )
    await call(service, "card-archive", "card.archive", card_id=copy["card_id"])
    return service.current_conversation_id


@pytest.mark.parametrize(
    ("setup", "source", "reason", "label"),
    [
        (_unbound_conversation, "none", "character_card_unbound", "未绑定角色卡"),
        (_conversation_bound_to_empty_draft, "card", "assembly_empty", "装配结果为空"),
        # 归档只让角色退出新建目录，已绑定的聊天仍按该卡装配
        (_conversation_bound_to_archived_card, "card", "assembly_empty", "装配结果为空"),
    ],
    ids=["unbound", "bound_empty_draft", "bound_archived_card"],
)
async def test_prompt_assembly_reports_why_no_module_was_assembled(
    service, setup, source: str, reason: str, label: str
) -> None:
    conversation_id = await setup(service)
    result = await _prompt_assembly(service, conversation_id)
    assert (result["source"], result["modules"], result["reason"]) == (source, [], reason)
    assert any(label in line for line in result["diagnostics"])
    encode_message(response_ok("prompt-assembly", result))


async def test_prompt_assembly_for_missing_conversation_fails(service) -> None:
    await expect_service_error(
        lambda: _prompt_assembly(service, "missing-conversation"), "conversation_not_found"
    )
