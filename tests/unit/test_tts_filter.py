from pair_harness.core.contracts import MessageKind, MessageSource
from pair_harness.core.voice_policy import is_tts_eligible


def test_character_speech_and_assistant_natural_language_are_eligible() -> None:
    assert is_tts_eligible(MessageSource.CHARACTER, MessageKind.CHARACTER_SPEECH)
    assert is_tts_eligible(MessageSource.ASSISTANT, MessageKind.ASSISTANT_NATURAL_LANGUAGE)


def test_all_non_speech_messages_stay_silent() -> None:
    silent = [
        (MessageSource.USER, MessageKind.USER_TEXT),
        (MessageSource.ASSISTANT, MessageKind.CODE),
        (MessageSource.ASSISTANT, MessageKind.COMMAND),
        (MessageSource.TOOL, MessageKind.TOOL_RECORD),
        (MessageSource.SYSTEM, MessageKind.SYSTEM_STATUS),
        (MessageSource.SYSTEM, MessageKind.APPROVAL),
    ]
    for source, kind in silent:
        assert not is_tts_eligible(source, kind), (source, kind)
