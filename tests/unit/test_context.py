"""recent_roleplay_context：角色上下文只保留真实对话，剔除任务镜像。

委派卡（origin=character_delegation 的 user 镜像）是任务指令的副本，
不是用户真实发言；混进角色上下文会让模型误以为用户又发了一条要求。
"""

from __future__ import annotations

from pair_harness.core.context import recent_roleplay_context
from pair_harness.core.contracts import (
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
)


def _message(text: str, *, source: str, origin: str) -> Message:
    return Message(
        conversation_id="c",
        pair_id="phainon_ancient_machine",
        source=MessageSource(source),
        kind=MessageKind.USER_TEXT,
        text=text,
        origin=MessageOrigin(origin),
    )


def test_roleplay_context_excludes_delegation_mirror() -> None:
    user = _message("帮我看看这个项目", source="user", origin="user")
    character = _message("好，交给古代机械。", source="character", origin="user")
    delegation = _message(
        "在项目目录下创建 Hello World.txt",
        source="user",
        origin="character_delegation",
    )

    context = recent_roleplay_context((user, character, delegation))

    assert context == (user, character)
    assert all(m.origin != MessageOrigin.CHARACTER_DELEGATION for m in context)


def test_roleplay_context_keeps_real_user_and_character() -> None:
    user = _message("今天天气不错", source="user", origin="user")
    character = _message("是啊，出去走走？", source="character", origin="user")

    assert recent_roleplay_context((user, character)) == (user, character)
