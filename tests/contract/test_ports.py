import inspect

from pair_harness.core.ports import (
    CodingEngine,
    DialogueModel,
    SpeechRecognizer,
    SpeechSynthesizer,
    StateStore,
    VoiceActivityDetector,
)


def test_ports_are_abstract_and_replaceable() -> None:
    for port in (
        DialogueModel,
        CodingEngine,
        StateStore,
        SpeechRecognizer,
        SpeechSynthesizer,
        VoiceActivityDetector,
    ):
        assert inspect.isabstract(port)


def test_coding_engine_exposes_required_control_channels() -> None:
    required = {
        "open_session",
        "run_turn",
        "cancel_turn",
        "amend_turn",
        "resolve_approval",
    }
    assert required <= set(dir(CodingEngine))

