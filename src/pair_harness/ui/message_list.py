from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from pair_harness.core.contracts import Message, MessageSource, enum_value


SOURCE_STYLES = {
    MessageSource.USER: "background:#343B4D;color:#E5E7EB;border:1px solid #4A5268;",
    MessageSource.CHARACTER: "background:#3A548C;color:#C7D4E3;border:1px solid #8AA4D4;",
    MessageSource.ASSISTANT: "background:#332A20;color:#F0E2C5;border:1px solid #B08D57;",
    MessageSource.TOOL: "background:#17191D;color:#D1D5DB;border:1px solid #373A40;",
    MessageSource.SYSTEM: "background:#24262B;color:#9CA3AF;border:1px solid #373A40;",
}

# 气泡来源标签：界面上不显示枚举名（O1.2）
SOURCE_LABELS = {
    MessageSource.USER: "用户",
    MessageSource.CHARACTER: "角色",
    MessageSource.ASSISTANT: "助手",
    MessageSource.TOOL: "工具",
    MessageSource.SYSTEM: "系统",
}


class MessageBubble(QFrame):
    def __init__(self, message: Message, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.message = message
        # objectName 只使用枚举值（不含点号），保证 QSS ID 选择器可用（O1.2）
        self.setObjectName(f"message-{enum_value(message.source)}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setStyleSheet(
            f"QFrame#{self.objectName()}{{{SOURCE_STYLES[message.source]}"
            "border-radius:10px;padding:8px;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.source_label = QLabel(SOURCE_LABELS[message.source])
        self.source_label.setObjectName("sourceLabel")
        self.source_label.setStyleSheet("font-size:11px;font-weight:600;background:transparent;")
        self.text_label = QLabel(message.text)
        self.text_label.setObjectName("textLabel")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text_label.setStyleSheet("background:transparent;")
        layout.addWidget(self.source_label)
        layout.addWidget(self.text_label)


class MessageList(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(8)
        self.setWidget(self.container)
        self.bubbles: list[MessageBubble] = []

    def add_message(self, message: Message) -> MessageBubble:
        bubble = MessageBubble(message)
        self.bubbles.append(bubble)
        self.layout.addWidget(bubble)
        return bubble

    def clear_messages(self) -> None:
        while self.bubbles:
            bubble = self.bubbles.pop()
            self.layout.removeWidget(bubble)
            bubble.deleteLater()

