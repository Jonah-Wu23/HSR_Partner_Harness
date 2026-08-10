from __future__ import annotations

from collections.abc import Iterable

from .contracts import Message, MessageSource


def recent_roleplay_context(messages: Iterable[Message], limit: int = 12) -> tuple[Message, ...]:
    """Return only user/character dialogue, excluding assistant and tool internals."""
    eligible = [
        message
        for message in messages
        if message.source in (MessageSource.USER, MessageSource.CHARACTER)
    ]
    return tuple(eligible[-limit:])

