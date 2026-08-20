from __future__ import annotations

import re
from enum import Enum

from pair_harness.core.contracts import MessageKind, MessageSource


class InputMethod(str, Enum):
    VAD = "vad"
    PUSH_TO_TALK = "push_to_talk"
    TEXT = "text"


def available_input_methods(*, target: str) -> tuple[InputMethod, ...]:
    """输入矩阵：对角色说话提供 VAD；直接交给助手不提供 VAD。

    聊天模式与协作模式的"对角色说"一致，都包含 VAD、按键说话和文字；
    "直接交给助手"只提供按键说话和文字。
    """
    if target == "assistant":
        return (InputMethod.PUSH_TO_TALK, InputMethod.TEXT)
    return (InputMethod.VAD, InputMethod.PUSH_TO_TALK, InputMethod.TEXT)


def is_tts_eligible(source: MessageSource, kind: MessageKind) -> bool:
    """V0.3.3：助手永不使用 TTS——仅角色发言进入 TTS，其余一律静音。"""
    return (source, kind) == (MessageSource.CHARACTER, MessageKind.CHARACTER_SPEECH)


# 仅空白与标点（含省略号、连接号、引号、括号）——不含可朗读的自然语言。
_PUNCTUATION_ONLY_RE = re.compile(
    r"^[\s，。！？；：、,.!?;:'\"“”‘’…—–~··`~@#$%^&*()\[\]{}<>《》【】（）—\-_|/\\+=]+$"
)


def is_readable_text(text: str) -> bool:
    """是否包含可朗读的自然语言（去除空白与标点后仍有内容）。

    V0.2 问题 2：角色结构化输出解析失败降级为 ``……`` 时不得进入 TTS；
    只有标点的段落（如 ``……``、``---``）同样静音。DashScope 收到
    空/纯标点文本会报 ``input text is invalid``。
    """
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return not bool(_PUNCTUATION_ONLY_RE.match(stripped))


