from __future__ import annotations

from collections.abc import Iterable

from .contracts import Message, MessageOrigin, MessageSource


def recent_roleplay_context(messages: Iterable[Message], limit: int = 12) -> tuple[Message, ...]:
    """只保留用户与角色的真实对话，排除助手与工具内部记录。

    委派卡（origin=character_delegation 的 user 镜像）是任务指令的副本，
    不是用户真实发言——把它留给模型会让模型误以为用户又发了一条要求。
    """
    eligible = [
        message
        for message in messages
        if message.source in (MessageSource.USER, MessageSource.CHARACTER)
        and message.origin != MessageOrigin.CHARACTER_DELEGATION
    ]
    return tuple(eligible[-limit:])

