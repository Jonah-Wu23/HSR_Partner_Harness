from pair_harness.core.contracts import Message, MessageKind, MessageSource
from pair_harness.ui.main_window import MainWindow


def test_chat_and_collaboration_modes_change_layout(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.mode == "chat"
    assert not window.assistant_panel.isVisible()
    assert not window.input_bar.target_combo.isVisible()

    window.show()
    window.set_mode("collaboration")
    assert window.assistant_panel.isVisible()
    assert window.input_bar.target_combo.isVisible()
    assert window.pair_rail.count() == 1


def test_messages_are_routed_by_structured_source(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    character = Message(
        conversation_id="c",
        pair_id="phainon_ancient_machine",
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text="我在。",
        tts_eligible=True,
    )
    assistant = Message(
        conversation_id="c",
        pair_id="phainon_ancient_machine",
        source=MessageSource.ASSISTANT,
        kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
        text="正在执行。",
        tts_eligible=True,
    )
    window.add_message(character)
    window.add_message(assistant)

    assert window.character_messages.bubbles[-1].objectName() == "message-character"
    assert window.assistant_messages.bubbles[-1].objectName() == "message-assistant"


def test_approval_bar_sits_below_input_bar_and_is_hidden(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    # 设计 §4.3：审批区位于输入区正下方，默认隐藏
    assert not window.approval_bar.isVisible()
    assert window.input_bar.parent() is not None
    assert window.approval_bar.parent() is window.input_bar.parent()


def test_approval_mode_change_updates_window_and_emits_signal(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    changes = []
    window.approval_mode_changed.connect(changes.append)

    assert window.input_bar.approval_mode == "request_approval"
    window.input_bar.approval_mode_combo.setCurrentIndex(2)
    assert changes == ["full_auto"]
    assert window.input_bar.approval_mode == "full_auto"

    # 恢复项目保存的模式：不发切换信号
    window.set_approval_mode("review")
    assert window.input_bar.approval_mode == "review"
    assert changes == ["full_auto"]


def test_library_toggle_shows_and_hides_library(qtbot) -> None:
    from PyQt5.QtWidgets import QLabel

    window = MainWindow()
    qtbot.addWidget(window)
    window.set_project_library(QLabel("项目与聊天库"))
    window.show()

    assert not window.project_library.isVisible()
    window.library_button.click()
    assert window.project_library.isVisible()
    window.library_button.click()
    assert not window.project_library.isVisible()

