"""voice_policy：助手永不使用 TTS 的冻结行为表（V0.3.3）。"""
from __future__ import annotations

from pair_harness.core.contracts import MessageKind, MessageSource
from pair_harness.core.voice_policy import is_readable_text, is_tts_eligible


def test_character_speech_is_eligible() -> None:
    assert is_tts_eligible(MessageSource.CHARACTER, MessageKind.CHARACTER_SPEECH)


def test_assistant_natural_language_is_no_longer_eligible() -> None:
    # V0.3.3：助手永不使用 TTS——助手自然语言不再放行。
    assert not is_tts_eligible(
        MessageSource.ASSISTANT, MessageKind.ASSISTANT_NATURAL_LANGUAGE
    )


def test_all_other_messages_stay_silent() -> None:
    silent = [
        (MessageSource.USER, MessageKind.USER_TEXT),
        (MessageSource.ASSISTANT, MessageKind.ASSISTANT_NATURAL_LANGUAGE),
        (MessageSource.ASSISTANT, MessageKind.CODE),
        (MessageSource.ASSISTANT, MessageKind.COMMAND),
        (MessageSource.TOOL, MessageKind.TOOL_RECORD),
        (MessageSource.SYSTEM, MessageKind.SYSTEM_STATUS),
        (MessageSource.SYSTEM, MessageKind.APPROVAL),
    ]
    for source, kind in silent:
        assert not is_tts_eligible(source, kind), (source, kind)


def test_is_readable_text_filters_punctuation_only() -> None:
    assert is_readable_text("你好，我是白厄。") is True
    assert is_readable_text("git status") is True
    assert is_readable_text("……") is False
    assert is_readable_text("。。。") is False
    assert is_readable_text("   ") is False
    assert is_readable_text("") is False