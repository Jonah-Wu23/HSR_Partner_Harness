"""持久化对话投影纯逻辑（V0.3.9 契约冻结 §1/§2）。

契约出处：``.archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md`` §1（顺序与身份）、§2（投影）。

- ``messages``/``tool_runs`` 永久保存原文，投影只引用
  ``message_id/summary_id/tool_call_id``，不复制原文；
- 时间线优先使用非空 ``timeline_order``，旧记录缺失时按 ``created_at`` 与
  稳定 id 排序（不得用 SQLite rowid）；
- 世界书扫描只使用投影保留的真实 user/character 原文，不扫描摘要或记忆；
- 摘要触发后角色上下文保留最近 12 条符合定义的原文（其余原文仍留在数据库）。

本模块是纯逻辑，不读写数据库。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .contracts import FrozenModel, Message
from .summary import (
    ROLE_CONTEXT_LIMIT_AFTER_SUMMARY,
    ROLE_CONTEXT_LIMIT_PRE_SUMMARY,
    ConversationSummary,
    SummaryError,
    is_role_message,
    messages_after_coverage,
    role_messages,
    validate_summary_coverage,
)


class ProjectionError(ValueError):
    """投影结构不一致的真实失败。"""


def _created_at_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def message_timeline_key(message: Message) -> tuple:
    """消息的统一时间线排序键（契约 §1）。"""
    return (
        0 if message.timeline_order is not None else 1,
        int(message.timeline_order) if message.timeline_order is not None else 0,
        _created_at_text(message.created_at),
        message.message_id,
    )


def tool_timeline_key(tool_run: Any) -> tuple:
    """工具记录的统一时间线排序键（契约 §1）。"""
    order = getattr(tool_run, "timeline_order", None)
    if order is not None:
        return (0, int(order), "", int(getattr(tool_run, "sequence", 0)), str(tool_run.tool_call_id))
    return (
        1,
        0,
        "",
        int(getattr(tool_run, "sequence", 0)),
        str(tool_run.tool_call_id),
    )


class ProjectionItem(FrozenModel):
    """投影中的一条引用（只引用 id，不复制原文）。"""

    ordinal: int = Field(ge=0)
    item_kind: Literal["message", "summary", "tool_ref"]
    message_id: str | None = None
    summary_id: str | None = None
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def _validate_ref(self) -> "ProjectionItem":
        refs = {
            "message": self.message_id,
            "summary": self.summary_id,
            "tool_ref": self.tool_call_id,
        }
        expected = refs[self.item_kind]
        if not expected:
            raise ValueError(f"{self.item_kind} 项缺少引用 id")
        for kind, value in refs.items():
            if kind != self.item_kind and value:
                raise ValueError(f"{self.item_kind} 项不得携带 {kind} 引用")
        return self


class ConversationProjection(FrozenModel):
    """一个聊天的持久化投影（有序引用列表）。"""

    conversation_id: str
    items: tuple[ProjectionItem, ...] = ()


def build_projection(
    *,
    conversation_id: str,
    messages: Iterable[Message],
    summaries: Iterable[ConversationSummary] = (),
    tool_runs: Iterable[Any] = (),
) -> ConversationProjection:
    """按契约顺序构造投影：被成功摘要覆盖的原文折叠为摘要项。

    摘要项落在其覆盖终点（``covers_to_message_id``）的时间线位置；
    未覆盖的原文保留为消息项；工具记录保留为引用项。原文不复制。
    """
    ordered_messages = tuple(sorted(messages, key=message_timeline_key))
    completed = tuple(
        summary for summary in summaries if summary.status == "completed"
    )
    coverage: dict[str, str] = {}
    endpoints: dict[str, str] = {}
    for summary in completed:
        if summary.conversation_id != conversation_id:
            raise ProjectionError(
                f"摘要不属于该聊天：{summary.summary_id}（{summary.conversation_id}）"
            )
        validate_summary_coverage(ordered_messages, summary)
        assert summary.covers_to_message_id is not None
        endpoints[summary.summary_id] = summary.covers_to_message_id
        # validate_summary_coverage 已确认端点存在且起点不晚于终点。
        ordered_ids = [message.message_id for message in ordered_messages]
        start = ordered_ids.index(summary.covers_from_message_id)
        end = ordered_ids.index(summary.covers_to_message_id)
        covered_ids = [
            message.message_id for message in ordered_messages[start : end + 1]
        ]
        for message_id in covered_ids:
            previous = coverage.get(message_id)
            if previous is not None and previous != summary.summary_id:
                raise ProjectionError(
                    f"摘要覆盖区间重叠：消息 {message_id} 同时属于 "
                    f"{previous} 与 {summary.summary_id}"
                )
            coverage[message_id] = summary.summary_id

    entries: list[tuple[tuple, ProjectionItem]] = []
    for message in ordered_messages:
        summary_id = coverage.get(message.message_id)
        if summary_id is not None:
            if endpoints[summary_id] != message.message_id:
                continue
            entries.append(
                (
                    message_timeline_key(message),
                    ProjectionItem(
                        ordinal=0, item_kind="summary", summary_id=summary_id
                    ),
                )
            )
            continue
        entries.append(
            (
                message_timeline_key(message),
                ProjectionItem(
                    ordinal=0, item_kind="message", message_id=message.message_id
                ),
            )
        )
    for tool_run in tool_runs:
        entries.append(
            (
                tool_timeline_key(tool_run),
                ProjectionItem(
                    ordinal=0,
                    item_kind="tool_ref",
                    tool_call_id=str(tool_run.tool_call_id),
                ),
            )
        )
    entries.sort(key=lambda entry: entry[0])
    items = tuple(
        entry[1].model_copy(update={"ordinal": index})
        for index, entry in enumerate(entries)
    )
    return ConversationProjection(conversation_id=conversation_id, items=items)


def validate_projection(
    projection: ConversationProjection,
    *,
    messages: Iterable[Message] = (),
    summaries: Iterable[ConversationSummary] = (),
    tool_runs: Iterable[Any] = (),
) -> None:
    """校验投影自身一致：序号连续、引用存在且不重复、摘要覆盖不重叠。"""
    ordinals = [item.ordinal for item in projection.items]
    if ordinals != list(range(len(projection.items))):
        raise ProjectionError("投影序号必须从 0 连续递增")
    message_ids = {message.message_id for message in messages}
    summary_ids = {summary.summary_id for summary in summaries}
    tool_ids = {str(tool_run.tool_call_id) for tool_run in tool_runs}
    seen: set[tuple[str, str]] = set()
    for item in projection.items:
        if item.item_kind == "message":
            assert item.message_id is not None
            if message_ids and item.message_id not in message_ids:
                raise ProjectionError(f"投影引用了不存在的消息：{item.message_id}")
            key = ("message", item.message_id)
        elif item.item_kind == "summary":
            assert item.summary_id is not None
            if summary_ids and item.summary_id not in summary_ids:
                raise ProjectionError(f"投影引用了不存在的摘要：{item.summary_id}")
            key = ("summary", item.summary_id)
        else:
            assert item.tool_call_id is not None
            if tool_ids and item.tool_call_id not in tool_ids:
                raise ProjectionError(f"投影引用了不存在的工具记录：{item.tool_call_id}")
            key = ("tool_ref", item.tool_call_id)
        if key in seen:
            raise ProjectionError(f"投影引用重复：{key[0]} {key[1]}")
        seen.add(key)


def world_book_scan_texts(
    projection: ConversationProjection,
    messages: Iterable[Message],
    *,
    limit: int | None = None,
) -> tuple[str, ...]:
    """世界书扫描文本：投影保留的真实 user/character 原文（契约 §2）。

    摘要项、工具项、助手/系统消息与委派镜像都不参与扫描。
    """
    index: Mapping[str, Message] = {
        message.message_id: message for message in messages
    }
    texts: list[str] = []
    for item in projection.items:
        if item.item_kind != "message":
            continue
        assert item.message_id is not None
        message = index.get(item.message_id)
        if message is None:
            raise ProjectionError(f"投影引用了不存在的消息：{item.message_id}")
        if is_role_message(message):
            texts.append(message.text)
    if limit is not None and limit >= 0:
        return tuple(texts[-limit:]) if limit else ()
    return tuple(texts)


def role_context_window(
    messages: Iterable[Message], *, covered_to_message_id: str | None = None
) -> tuple[Message, ...]:
    """进入角色上下文的原文窗口（契约 §2）。

    - 尚无成功摘要覆盖：保留最近 ``ROLE_CONTEXT_LIMIT_PRE_SUMMARY`` 条；
    - 已有成功摘要覆盖：保留最近 ``ROLE_CONTEXT_LIMIT_AFTER_SUMMARY`` 条。
    """
    pending = role_messages(messages_after_coverage(messages, covered_to_message_id))
    limit = (
        ROLE_CONTEXT_LIMIT_AFTER_SUMMARY
        if covered_to_message_id
        else ROLE_CONTEXT_LIMIT_PRE_SUMMARY
    )
    return pending[-limit:]


def projection_diagnostics(
    projection: ConversationProjection,
    *,
    messages: Iterable[Message] = (),
) -> dict:
    """投影装配诊断（不返回原文，只返回结构事实）。"""
    counts = {"message": 0, "summary": 0, "tool_ref": 0}
    for item in projection.items:
        counts[item.item_kind] += 1
    scan_count = len(world_book_scan_texts(projection, messages))
    return {
        "conversation_id": projection.conversation_id,
        "item_count": len(projection.items),
        "message_items": counts["message"],
        "summary_items": counts["summary"],
        "tool_ref_items": counts["tool_ref"],
        "world_book_scan_messages": scan_count,
    }


__all__ = [
    "ConversationProjection",
    "ProjectionError",
    "ProjectionItem",
    "SummaryError",
    "build_projection",
    "message_timeline_key",
    "projection_diagnostics",
    "role_context_window",
    "tool_timeline_key",
    "validate_projection",
    "world_book_scan_texts",
]
