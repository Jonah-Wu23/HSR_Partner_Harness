from pair_harness.ui.audio_controls import AudioControls


def test_vad_state_label_reflects_states(qtbot) -> None:
    controls = AudioControls()
    qtbot.addWidget(controls)
    controls.set_vad_state("listening")
    assert controls.vad_label.text() == "聆听中"
    controls.set_vad_state("speech_started")
    assert controls.vad_label.text() == "说话中"
    controls.set_vad_state("false_trigger")
    assert controls.vad_label.text() == "误触发"


def test_playing_enables_stop_and_marks_playing(qtbot) -> None:
    controls = AudioControls()
    qtbot.addWidget(controls)
    assert not controls.stop_button.isEnabled()
    controls.set_playing(True)
    assert controls.stop_button.isEnabled()
    assert controls.vad_label.text() == "播放中"
    controls.set_playing(False)
    assert not controls.stop_button.isEnabled()


def test_stop_button_emits_stop_requested(qtbot) -> None:
    controls = AudioControls()
    qtbot.addWidget(controls)
    controls.set_playing(True)
    with qtbot.waitSignal(controls.stop_requested):
        controls.stop_button.click()
