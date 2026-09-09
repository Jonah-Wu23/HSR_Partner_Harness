"""V0.3.9 契约 §1/§2：持久化投影、世界书扫描源与角色上下文窗口。

契约出处：``.archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md`` §1（时间线顺序）、§2（投影）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from pair_harness.core.contracts import (
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
)
from pair_harness.core.projection import (
    ConversationProjection,
    ProjectionError,
    ProjectionItem,
    build_projection,
    message_timeline_key,
    projection_diagnostics,
    role_context_window,
    tool_timeline_key,
    validate_projection,
    world_book_scan_texts,
)
from pair_harness.core.summary import (
    ROLE_CONTEXT_LIMIT_AFTER_SUMMARY,
    ROLE_CONTEXT_LIMIT_PRE_SUMMARY,
    completed_summary,
    role_messages,
)

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _message(
    index: int,
    text: str | None = None,
    *,
    source: MessageSource = MessageSource.USER,
    origin: MessageOrigin = MessageOrigin.USER,
    kind: MessageKind = MessageKind.USER_TEXT,
    status: MessageStatus = MessageStatus.DONE,
    timeline_order: int | None = None,
    conversation_id: str = "conv-1",
) -> Message:
    return Message(
        message_id=f"m{index}",
        conversation_id=conversation_id,
        pair_id="phainon_ancient_machine",
        source=source,
        kind=kind,
        text=text if text is not None else f"消息{index}",
        origin=origin,
        status=status,
        created_at=_T0 + timedelta(seconds=index),
        timeline_order=timeline_order,
    )


@dataclass(frozen=True)
class _ToolRun:
    tool_call_id: str
    sequence: int = 0
    timeline_order: int | None = None


def test_projection_item_requires_exactly_one_reference() -> None:
    ProjectionItem(ordinal=0, item_kind="message", message_id="m1")
    ProjectionItem(ordinal=1, item_kind="summary", summary_id="s1")
    ProjectionItem(ordinal=2, item_kind="tool_ref", tool_call_id="t1")
    with pytest.raises(Exception):
        ProjectionItem(ordinal=0, item_kind="message")
    with pytest.raises(Exception):
        ProjectionItem(ordinal=0, item_kind="message", message_id="m1", summary_id="s1")


def test_projection_replaces_covered_range_with_summary_reference() -> None:
    messages = [_message(i) for i in range(1, 6)]
    messages.append(
        _message(6, source=MessageSource.ASSISTANT, kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE)
    )
    summary = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m4",
        covers_message_count=4,
        content={"topics": ["寒暄"]},
    )
    projection = build_projection(
        conversation_id="conv-1", messages=messages, summaries=[summary]
    )
    kinds = [(item.item_kind, item.message_id or item.summary_id) for item in projection.items]
    assert kinds == [
        ("summary", "s1"),
        ("message", "m5"),
        ("message", "m6"),
    ]
    assert [item.ordinal for item in projection.items] == [0, 1, 2]
    # 原文不被复制进投影：只有引用
    assert all(not hasattr(item, "text") for item in projection.items)


def test_projection_without_summaries_keeps_all_messages_in_order() -> None:
    messages = [_message(i) for i in range(1, 4)]
    projection = build_projection(conversation_id="conv-1", messages=messages)
    assert [item.message_id for item in projection.items] == ["m1", "m2", "m3"]


def test_projection_orders_by_timeline_order_then_created_at() -> None:
    messages = [
        _message(1, timeline_order=2),
        _message(2, timeline_order=1),
        _message(3),
    ]
    projection = build_projection(conversation_id="conv-1", messages=messages)
    assert [item.message_id for item in projection.items] == ["m2", "m1", "m3"]


def test_projection_merges_tool_refs_into_same_timeline() -> None:
    messages = [_message(1, timeline_order=1), _message(2, timeline_order=3)]
    tools = [_ToolRun("t1", timeline_order=2)]
    projection = build_projection(
        conversation_id="conv-1", messages=messages, tool_runs=tools
    )
    assert [item.item_kind for item in projection.items] == [
        "message",
        "tool_ref",
        "message",
    ]
    assert projection.items[1].tool_call_id == "t1"


def test_projection_rejects_overlapping_summaries() -> None:
    messages = [_message(i) for i in range(1, 6)]
    first = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m3",
        covers_message_count=3,
        content={"a": 1},
    )
    second = completed_summary(
        summary_id="s2",
        conversation_id="conv-1",
        covers_from_message_id="m2",
        covers_to_message_id="m4",
        covers_message_count=3,
        content={"b": 1},
    )
    with pytest.raises(ProjectionError):
        build_projection(
            conversation_id="conv-1", messages=messages, summaries=[first, second]
        )


def test_projection_rejects_summary_from_other_conversation() -> None:
    messages = [_message(i) for i in range(1, 3)]
    foreign = completed_summary(
        summary_id="s1",
        conversation_id="conv-other",
        covers_from_message_id="m1",
        covers_to_message_id="m2",
        covers_message_count=2,
        content={"a": 1},
    )
    with pytest.raises(ProjectionError):
        build_projection(
            conversation_id="conv-1", messages=messages, summaries=[foreign]
        )


def test_validate_projection_checks_ordinals_and_refs() -> None:
    messages = [_message(1), _message(2)]
    projection = build_projection(conversation_id="conv-1", messages=messages)
    validate_projection(projection, messages=messages)

    bad_ordinal = ConversationProjection(
        conversation_id="conv-1",
        items=(ProjectionItem(ordinal=1, item_kind="message", message_id="m1"),),
    )
    with pytest.raises(ProjectionError):
        validate_projection(bad_ordinal, messages=messages)

    unknown = ConversationProjection(
        conversation_id="conv-1",
        items=(ProjectionItem(ordinal=0, item_kind="message", message_id="missing"),),
    )
    with pytest.raises(ProjectionError):
        validate_projection(unknown, messages=messages)

    duplicated = ConversationProjection(
        conversation_id="conv-1",
        items=(
            ProjectionItem(ordinal=0, item_kind="message", message_id="m1"),
            ProjectionItem(ordinal=1, item_kind="message", message_id="m1"),
        ),
    )
    with pytest.raises(ProjectionError):
        validate_projection(duplicated, messages=messages)


def test_world_book_scan_uses_only_projection_retained_real_roleplay_text() -> None:
    messages = [
        _message(1, "第一句"),
        _message(2, "第二句"),
        _message(3, "委派指令", origin=MessageOrigin.CHARACTER_DELEGATION),
        _message(4, "助手回复", source=MessageSource.ASSISTANT, kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE),
        _message(5, "角色台词", source=MessageSource.CHARACTER, kind=MessageKind.CHARACTER_SPEECH),
        _message(6, "系统提示", source=MessageSource.SYSTEM, kind=MessageKind.SYSTEM_STATUS),
    ]
    summary = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m2",
        covers_message_count=2,
        content={"topics": ["寒暄"]},
    )
    projection = build_projection(
        conversation_id="conv-1", messages=messages, summaries=[summary]
    )
    texts = world_book_scan_texts(projection, messages)
    assert texts == ("角色台词",)
    # 摘要内容与委派镜像都不得进入扫描源
    assert all("寒暄" not in text for text in texts)
    assert all("委派指令" not in text for text in texts)
    assert world_book_scan_texts(projection, messages, limit=0) == ()


def test_world_book_scan_raises_when_projection_references_missing_message() -> None:
    projection = ConversationProjection(
        conversation_id="conv-1",
        items=(ProjectionItem(ordinal=0, item_kind="message", message_id="missing"),),
    )
    with pytest.raises(ProjectionError):
        world_book_scan_texts(projection, [_message(1)])


def test_role_context_window_uses_contract_limits() -> None:
    many = [_message(i) for i in range(1, 61)]
    assert len(role_context_window(many)) == ROLE_CONTEXT_LIMIT_PRE_SUMMARY
    window = role_context_window(many, covered_to_message_id="m5")
    assert len(window) == ROLE_CONTEXT_LIMIT_AFTER_SUMMARY
    assert [m.message_id for m in window] == [f"m{i}" for i in range(49, 61)]


def test_role_context_window_keeps_only_role_messages_after_coverage() -> None:
    messages = [
        _message(1),
        _message(2, source=MessageSource.ASSISTANT, kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE),
        _message(3),
        _message(4, "   "),
    ]
    window = role_context_window(messages)
    assert [m.message_id for m in window] == ["m1", "m3"]
    assert role_messages(messages) == (messages[0], messages[2])


def test_timeline_keys_prefer_timeline_order() -> None:
    with_order = _message(1, timeline_order=5)
    without_order = _message(2)
    assert message_timeline_key(with_order) < message_timeline_key(without_order)
    assert tool_timeline_key(_ToolRun("t1", timeline_order=1)) < tool_timeline_key(
        _ToolRun("t2")
    )


def test_projection_diagnostics_counts_without_content() -> None:
    messages = [_message(i) for i in range(1, 4)]
    summary = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m2",
        covers_message_count=2,
        content={"secret": "hidden"},
    )
    projection = build_projection(
        conversation_id="conv-1", messages=messages, summaries=[summary]
    )
    diagnostics = projection_diagnostics(projection, messages=messages)
    assert diagnostics["item_count"] == 2
    assert diagnostics["summary_items"] == 1
    assert diagnostics["message_items"] == 1
    assert diagnostics["world_book_scan_messages"] == 1
    assert "hidden" not in str(diagnostics)
