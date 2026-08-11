from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from pair_harness.config.pairs import PairTheme
from pair_harness.core.contracts import Message, MessageSource, enum_value

# O4.5：角色/助手气泡颜色由 PairConfig.theme 驱动（B3 前置，设计 §4.5）——
# 白厄蓝（character_deep/character_text/character_primary）、古代机械金
# （assistant_shadow/assistant_bright/assistant_primary）。theme 未配置时
# 回退到内置默认色，保证无配置场景行为不变。
DEFAULT_CHARACTER_STYLE = "background:#3A548C;color:#C7D4E3;border:1px solid #8AA4D4;"
DEFAULT_ASSISTANT_STYLE = "background:#332A20;color:#F0E2C5;border:1px solid #B08D57;"

# 用户、工具、系统消息使用不随搭档切换的中性样式（设计 §4.5）
NEUTRAL_STYLES = {
    MessageSource.USER: "background:#343B4D;color:#E5E7EB;border:1px solid #4A5268;",
    MessageSource.TOOL: "background:#17191D;color:#D1D5DB;border:1px solid #373A40;",
    MessageSource.SYSTEM: "background:#24262B;color:#9CA3AF;border:1px solid #373A40;",
}

# 气泡来源标签：界面上不显示枚举名（O1.2）。
# TOOL 条目保留：旧聊天历史中可能残留工具消息，重开时仍能正常渲染。
SOURCE_LABELS = {
    MessageSource.USER: "用户",
    MessageSource.CHARACTER: "角色",
    MessageSource.ASSISTANT: "助手",
    MessageSource.TOOL: "工具",
    MessageSource.SYSTEM: "系统",
}


def bubble_style(source: MessageSource, theme: PairTheme | None) -> str:
    """按消息来源计算气泡样式。

    角色与助手读取 theme 三色：character 取深层背景/浅色文字/主色，
    assistant 取阴影背景/亮色文字/主色；theme 缺省回退默认色。
    用户/工具/系统始终使用中性固定样式。
    """
    if source == MessageSource.CHARACTER:
        if theme is not None:
            return (
                f"background:{theme.character_deep};color:{theme.character_text};"
                f"border:1px solid {theme.character_primary};"
            )
        return DEFAULT_CHARACTER_STYLE
    if source == MessageSource.ASSISTANT:
        if theme is not None:
            return (
                f"background:{theme.assistant_shadow};color:{theme.assistant_bright};"
                f"border:1px solid {theme.assistant_primary};"
            )
        return DEFAULT_ASSISTANT_STYLE
    return NEUTRAL_STYLES[source]


class MessageBubble(QFrame):
    def __init__(
        self, message: Message, theme: PairTheme | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.message = message
        # objectName 只使用枚举值（不含点号），保证 QSS ID 选择器可用（O1.2）
        self.setObjectName(f"message-{enum_value(message.source)}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setStyleSheet(
            f"QFrame#{self.objectName()}{{{bubble_style(message.source, theme)}"
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
        # O4.5：QLabel 默认 AutoText 会把消息文本当富文本解析（含 <...> 时
        # 渲染错乱），统一按纯文本显示
        self.text_label.setTextFormat(Qt.PlainText)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text_label.setStyleSheet("background:transparent;")
        layout.addWidget(self.source_label)
        layout.addWidget(self.text_label)


class MessageList(QScrollArea):
    def __init__(self, theme: PairTheme | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(8)
        self.setWidget(self.container)
        self.bubbles: list[MessageBubble] = []

    def add_message(self, message: Message) -> MessageBubble:
        bubble = MessageBubble(message, theme=self._theme)
        self.bubbles.append(bubble)
        self.layout.addWidget(bubble)
        return bubble

    def clear_messages(self) -> None:
        while self.bubbles:
            bubble = self.bubbles.pop()
            self.layout.removeWidget(bubble)
            bubble.deleteLater()

