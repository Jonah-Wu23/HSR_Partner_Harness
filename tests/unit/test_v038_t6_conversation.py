"""V0.3.8 T6：会话创建幂等与 mode 漂移修复的回归测试（真机验收 C6）。

覆盖（docs/plans/V0.3.8-修复实施计划.md §2 T6、契约 §14.2）：
- conversation.create 的 reuse_active 复用：同项目 + 同角色卡 + 活跃
  （archived=0）会话命中时返回既有会话（reused=true），不新建、不重复
  开场白；无角色卡不参与复用；缺省行为不变（无条件新建，reused=false）。
- mode 漂移：chat.submit 缺省 mode 不再改写会话 last_mode（“委派”标签与
  updated_at 不再被普通消息漂移）；显式携带 mode 仍按请求持久化。
- conversation.archive 补建判断用被归档会话自身的项目：归档非当前项目的
  最后聊天不得在当前项目凭空补“新聊天”。
"""

from __future__ import annotations

import pytest

# 复用 test_v035_wiring 的 command 辅助与 service 夹具（pytest 同目录导入）
from test_v035_wiring import command, service  # noqa: F401

from pair_harness.core.contracts import Message, MessageKind, MessageSource


def _bound_conversation(service, card_id: str, *, archived: bool = False):
    """在当前项目里建一个绑定指定角色卡的会话（绕过命令直接落库）。"""
    conversation = service.store.create_conversation(
        pair_id=service.pair_config.pair_id,
        project_id=service.current_project_id,
        title=f"卡会话-{card_id}",
        account_id=service.current_account_id,
        character_card_id=card_id,
    )
    if archived:
        service.store.archive_conversation(conversation.conversation_id)
        return service.store.get_conversation(conversation.conversation_id)
    return conversation


def _conversation_count(service) -> int:
    return len(service.store.list_conversations(service.current_project_id))


@pytest.mark.asyncio
async def test_conversation_create_reuse_active_reuses_active_card_conversation(service) -> None:
    """reuse_active=true 且同项目同卡活跃会话存在 → 复用（reused=true，不新建）。"""
    existing = _bound_conversation(service, "card-phainon")
    before = _conversation_count(service)

    result = await service.handle_command(
        command(
            "1",
            "conversation.create",
            character_card_id="card-phainon",
            reuse_active=True,
        )
    )

    assert result["reused"] is True
    assert service.current_conversation_id == existing.conversation_id
    assert _conversation_count(service) == before, "复用不得新建会话"


@pytest.mark.asyncio
async def test_conversation_create_reuse_active_creates_when_no_match(service) -> None:
    """reuse_active=true 但无同卡活跃会话 → 照常新建（reused=false）。"""
    _bound_conversation(service, "card-other")
    before = _conversation_count(service)

    result = await service.handle_command(
        command(
            "1",
            "conversation.create",
            character_card_id="card-new",
            reuse_active=True,
        )
    )

    assert result["reused"] is False
    assert _conversation_count(service) == before + 1


@pytest.mark.asyncio
async def test_conversation_create_default_always_creates(service) -> None:
    """缺省（不带 reuse_active）维持现状：无条件新建，即使同卡活跃会话存在。"""
    _bound_conversation(service, "card-phainon")
    before = _conversation_count(service)

    result = await service.handle_command(
        command("1", "conversation.create", character_card_id="card-phainon")
    )

    assert result["reused"] is False
    assert _conversation_count(service) == before + 1


@pytest.mark.asyncio
async def test_conversation_create_reuse_active_skips_archived(service) -> None:
    """归档会话不参与复用（活跃 = archived=0）。"""
    _bound_conversation(service, "card-phainon", archived=True)
    before = _conversation_count(service)

    result = await service.handle_command(
        command(
            "1",
            "conversation.create",
            character_card_id="card-phainon",
            reuse_active=True,
        )
    )

    assert result["reused"] is False
    assert _conversation_count(service) == before + 1


@pytest.mark.asyncio
async def test_conversation_create_reuse_active_without_card_creates(service) -> None:
    """无角色卡的普通会话不参与复用（契约 §14.2）：始终新建。"""
    result = await service.handle_command(
        command("1", "conversation.create", title="普通聊天", reuse_active=True)
    )
    assert result["reused"] is False


@pytest.mark.asyncio
async def test_chat_submit_without_mode_keeps_conversation_mode(service) -> None:
    """chat.submit 缺省 mode 不改写会话 last_mode（“委派”标签漂移根因）。"""
    conversation_id = service.current_conversation_id
    conversation = service.store.get_conversation(conversation_id)
    assert conversation.last_mode == "chat"

    await service.handle_command(
        command(
            "1",
            "chat.submit",
            conversation_id=conversation_id,
            target="character",
            text="普通消息（窗口全局可能处于协作模式）",
        )
    )

    assert service.store.get_conversation(conversation_id).last_mode == "chat"


@pytest.mark.asyncio
async def test_chat_submit_with_explicit_mode_persists(service) -> None:
    """显式携带 mode 的提交仍按请求持久化会话模式。"""
    conversation_id = service.current_conversation_id

    await service.handle_command(
        command(
            "1",
            "chat.submit",
            conversation_id=conversation_id,
            target="character",
            mode="collaboration",
            text="显式带模式的消息",
        )
    )

    assert service.store.get_conversation(conversation_id).last_mode == "collaboration"


@pytest.mark.asyncio
async def test_archive_other_project_keeps_current_project_intact(service) -> None:
    """归档非当前项目的最后聊天：当前项目不得凭空补“新聊天”。

    被归档会话所属项目按既有语义保持至少一个活跃聊天（补建发生在该项目）。
    """
    other_project = service.store.create_project(
        name="其他项目",
        root_path=str(service.tmp_path / "other"),
        account_id=service.current_account_id,
    )
    other_conversation = service.store.create_conversation(
        pair_id=service.pair_config.pair_id,
        project_id=other_project.project_id,
        title="其他项目聊天",
        account_id=service.current_account_id,
    )
    current_project_id = service.current_project_id
    before_current = _conversation_count(service)
    assert current_project_id != other_project.project_id

    await service.handle_command(
        command(
            "1",
            "conversation.archive",
            conversation_id=other_conversation.conversation_id,
        )
    )

    assert _conversation_count(service) == before_current, (
        "归档其他项目的最后聊天不得在当前项目补建新聊天"
    )
    remaining_other = service.store.list_conversations(other_project.project_id)
    assert len(remaining_other) == 1 and remaining_other[0].archived is False


@pytest.mark.asyncio
async def test_reused_conversation_bootstrap_targets_existing(service) -> None:
    """复用返回的 bootstrap 快照以既有会话为当前上下文，消息历史随行。"""
    existing = _bound_conversation(service, "card-history")
    service.store.save_message(
        Message(
            conversation_id=existing.conversation_id,
            pair_id=existing.pair_id,
            source=MessageSource.CHARACTER,
            kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
            text="既有历史",
        )
    )

    result = await service.handle_command(
        command(
            "1",
            "conversation.create",
            character_card_id="card-history",
            reuse_active=True,
        )
    )

    assert result["reused"] is True
    conversations = {
        item["conversation_id"]: item
        for project in result["projects"]
        for item in project["conversations"]
    }
    assert existing.conversation_id in conversations
    assert result["current_conversation_id"] == existing.conversation_id
