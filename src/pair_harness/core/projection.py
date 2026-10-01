from __future__ import annotations

from collections.abc import Iterable

from .contracts import Message
from .summary import (
    ROLE_CONTEXT_LIMIT_AFTER_SUMMARY,
    ROLE_CONTEXT_LIMIT_PRE_SUMMARY,
    messages_after_coverage,
    role_messages,
)


def role_context_window(
    messages: Iterable[Message], *, covered_to_message_id: str | None = None
) -> tuple[Message, ...]:
    """进入角色上下文的原文窗口。

    只保留覆盖终点之后、符合角色消息定义的原文：尚无成功摘要覆盖时保留
    最近 ``ROLE_CONTEXT_LIMIT_PRE_SUMMARY`` 条，已有成功摘要覆盖时保留
    最近 ``ROLE_CONTEXT_LIMIT_AFTER_SUMMARY`` 条。
    """
    pending = role_messages(messages_after_coverage(messages, covered_to_message_id))
    limit = (
        ROLE_CONTEXT_LIMIT_AFTER_SUMMARY
        if covered_to_message_id
        else ROLE_CONTEXT_LIMIT_PRE_SUMMARY
    )
    return pending[-limit:]
