from __future__ import annotations

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
    """只有角色发言与助手自然语言进入 TTS，其余一律静音。"""
    return (source, kind) in {
        (MessageSource.CHARACTER, MessageKind.CHARACTER_SPEECH),
        (MessageSource.ASSISTANT, MessageKind.ASSISTANT_NATURAL_LANGUAGE),
    }
