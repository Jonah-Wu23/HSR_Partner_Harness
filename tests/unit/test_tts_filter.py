from __future__ import annotations

import pytest

from pair_harness.core.contracts import MessageKind, MessageSource
from pair_harness.core.voice_policy import is_readable_text, is_tts_eligible


@pytest.mark.parametrize(
    ("source", "kind", "eligible"),
    [
        (MessageSource.CHARACTER, MessageKind.CHARACTER_SPEECH, True),
        (MessageSource.USER, MessageKind.USER_TEXT, False),
        (MessageSource.ASSISTANT, MessageKind.ASSISTANT_NATURAL_LANGUAGE, False),
        (MessageSource.ASSISTANT, MessageKind.CODE, False),
        (MessageSource.ASSISTANT, MessageKind.COMMAND, False),
        (MessageSource.TOOL, MessageKind.TOOL_RECORD, False),
        (MessageSource.SYSTEM, MessageKind.SYSTEM_STATUS, False),
        (MessageSource.SYSTEM, MessageKind.APPROVAL, False),
    ],
)
def test_only_character_speech_is_tts_eligible(source, kind, eligible) -> None:
    assert is_tts_eligible(source, kind) is eligible


@pytest.mark.parametrize(
    ("text", "readable"),
    [
        ("你好，我是白厄。", True),
        ("git status", True),
        ("……", False),
        ("。。。", False),
        ("---", False),
        ("   ", False),
        ("", False),
    ],
)
def test_punctuation_only_text_is_not_readable(text, readable) -> None:
    assert is_readable_text(text) is readable