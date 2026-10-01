from __future__ import annotations

import re

from pair_harness.core.contracts import MessageKind, MessageSource


def is_tts_eligible(source: MessageSource, kind: MessageKind) -> bool:
    """只有角色发言进入 TTS；助手与其余来源一律静音。"""
    return (source, kind) == (MessageSource.CHARACTER, MessageKind.CHARACTER_SPEECH)


# 仅空白与标点（含省略号、连接号、引号、括号），不含可朗读的自然语言。
_PUNCTUATION_ONLY_RE = re.compile(
    r"^[\s，。！？；：、,.!?;:'\"“”‘’…—–~··`~@#$%^&*()\[\]{}<>《》【】（）—\-_|/\\+=]+$"
)


def is_readable_text(text: str) -> bool:
    """是否包含可朗读的自然语言（去除空白与标点后仍有内容）。

    只有标点的段落（如 ``……``、``---``）静音；DashScope 收到空文本或
    纯标点文本会报 ``input text is invalid``。
    """
    stripped = text.strip()
    if not stripped:
        return False
    return not bool(_PUNCTUATION_ONLY_RE.match(stripped))

