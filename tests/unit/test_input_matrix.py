from pair_harness.core.voice_policy import InputMethod, available_input_methods


def test_character_target_provides_vad_ptt_text() -> None:
    methods = available_input_methods(target="character")
    assert methods == (InputMethod.VAD, InputMethod.PUSH_TO_TALK, InputMethod.TEXT)


def test_assistant_target_omits_vad() -> None:
    methods = available_input_methods(target="assistant")
    assert InputMethod.VAD not in methods
    assert InputMethod.PUSH_TO_TALK in methods
    assert InputMethod.TEXT in methods
