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


def test_bubble_shows_chinese_source_label_and_safe_object_name(qtbot) -> None:
    """O1.2：气泡来源标签为中文，objectName 不含枚举名与点号，样式表已应用。"""
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
    window.add_message(character)
    bubble = window.character_messages.bubbles[-1]
    assert bubble.objectName() == "message-character"
    assert "." not in bubble.objectName()
    assert "MessageSource" not in bubble.objectName()
    assert bubble.source_label.text() == "角色"
    assert "message-character" in bubble.styleSheet()
    # 其他来源的中文标签映射（按 add_message 的路由取对应列表）
    for source, label in [
        (MessageSource.USER, "用户"),
        (MessageSource.ASSISTANT, "助手"),
        (MessageSource.TOOL, "工具"),
        (MessageSource.SYSTEM, "系统"),
    ]:
        msg = Message(
            conversation_id="c",
            pair_id="phainon_ancient_machine",
            source=source,
            kind=MessageKind.SYSTEM_STATUS,
            text="x",
        )
        window.add_message(msg)
        target = (
            window.assistant_messages
            if source in (MessageSource.ASSISTANT, MessageSource.TOOL)
            else window.character_messages
        )
        assert target.bubbles[-1].source_label.text() == label


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


def test_approval_request_shows_real_reason_and_emits_id(qtbot) -> None:
    """O1.7：审批区展示真实理由，裁决信号按 approval_id 贯通。"""
    window = MainWindow()
    qtbot.addWidget(window)
    decisions = []
    window.approval_decided.connect(lambda approval_id, decision: decisions.append((approval_id, decision)))
    window.show()

    window.show_approval_request("approval-7", "写入环境变量", "需要用户审批")

    assert window.approval_bar.isVisible()
    assert "写入环境变量" in window.approval_bar.summary_label.text()
    assert "需要用户审批" in window.approval_bar.summary_label.text()
    window.approval_bar.allow_button.click()
    assert decisions == [("approval-7", "allow")]


def test_two_approval_requests_resolve_by_id(qtbot) -> None:
    """O1.7：两个连续审批请求按各自 id 裁决，不依赖 FIFO 巧合。"""
    window = MainWindow()
    qtbot.addWidget(window)
    decisions = []
    window.approval_decided.connect(lambda approval_id, decision: decisions.append((approval_id, decision)))
    window.show()

    window.show_approval_request("approval-a", "操作一", "需要用户审批")
    window.show_approval_request("approval-b", "操作二", "需要用户审批")
    assert window.approval_bar.pending_count == 2
    assert "操作一" in window.approval_bar.summary_label.text()

    window.approval_bar.deny_button.click()
    assert decisions == [("approval-a", "deny")]
    assert "操作二" in window.approval_bar.summary_label.text()
    window.approval_bar.allow_button.click()
    assert decisions == [("approval-a", "deny"), ("approval-b", "allow")]

