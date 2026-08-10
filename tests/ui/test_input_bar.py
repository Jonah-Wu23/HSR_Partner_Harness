import pytest

from pair_harness.ui.input_bar import InputBar


def test_assistant_target_hides_vad(qtbot) -> None:
    bar = InputBar()
    qtbot.addWidget(bar)
    bar.show()
    bar.set_collaboration_mode(True)

    assert bar.vad_button.isVisible()
    bar.target_combo.setCurrentIndex(1)
    assert bar.target == "assistant"
    assert not bar.vad_button.isVisible()
    assert bar.ptt_button.isVisible()
    assert bar.text_input.isVisible()


def test_chat_mode_fixes_target_to_character(qtbot) -> None:
    bar = InputBar()
    qtbot.addWidget(bar)
    bar.target_combo.setCurrentIndex(1)
    bar.set_collaboration_mode(False)

    assert bar.target == "character"
    assert not bar.target_combo.isVisible()


def test_approval_mode_combo_has_three_modes_and_emits_on_change(qtbot) -> None:
    bar = InputBar()
    qtbot.addWidget(bar)

    # 计划 A5：三项依次为请求批准 / 帮我审核 / 完全允许运行
    assert [bar.approval_mode_combo.itemText(i) for i in range(bar.approval_mode_combo.count())] == [
        "请求批准",
        "帮我审核",
        "完全允许运行",
    ]
    assert bar.approval_mode == "request_approval"

    changes = []
    bar.approval_mode_changed.connect(changes.append)
    bar.approval_mode_combo.setCurrentIndex(1)
    assert changes == ["review"]
    bar.approval_mode_combo.setCurrentIndex(2)
    assert changes == ["review", "full_auto"]


def test_set_approval_mode_restores_selection_without_signal(qtbot) -> None:
    bar = InputBar()
    qtbot.addWidget(bar)
    changes = []
    bar.approval_mode_changed.connect(changes.append)

    bar.set_approval_mode("full_auto")
    assert bar.approval_mode == "full_auto"
    assert changes == []

    with pytest.raises(ValueError):
        bar.set_approval_mode("unknown")

