from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pair_harness.config.pairs import PairTheme
from pair_harness.core.contracts import Message, MessageSource, enum_value
from pair_harness.ui.theme import DARK_TOKENS, bubble_style_for, fade

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
        self._theme = theme
        # objectName 只使用枚举值（不含点号），保证 QSS ID 选择器可用（O1.2）
        self.setObjectName(f"message-{enum_value(message.source)}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.source_label = QLabel(SOURCE_LABELS[message.source])
        self.source_label.setObjectName("sourceLabel")
        layout.addWidget(self.source_label)

        self.reasoning_toggle: QToolButton | None = None
        self.reasoning_label: QLabel | None = None
        self.final_label: QLabel | None = None
        reasoning = str(message.payload.get("reasoning", "") or "").strip()
        if message.source in (MessageSource.CHARACTER, MessageSource.ASSISTANT) and reasoning:
            self.reasoning_toggle = QToolButton()
            self.reasoning_toggle.setObjectName("reasoningToggle")
            self.reasoning_toggle.setText("模型思考")
            self.reasoning_toggle.setCheckable(True)
            self.reasoning_toggle.setArrowType(Qt.RightArrow)
            self.reasoning_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.reasoning_toggle.setStyleSheet(
                "QToolButton{background:transparent;border:0;padding:2px;"
                "font-size:11px;font-weight:600;text-align:left;}"
            )
            self.reasoning_label = QLabel(reasoning)
            self.reasoning_label.setObjectName("reasoningLabel")
            self.reasoning_label.setWordWrap(True)
            self.reasoning_label.setTextFormat(Qt.PlainText)
            self.reasoning_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.reasoning_label.setVisible(False)
            self.reasoning_toggle.toggled.connect(self._toggle_reasoning)
            layout.addWidget(self.reasoning_toggle)
            layout.addWidget(self.reasoning_label)

            self.final_label = QLabel("最终回复")
            self.final_label.setObjectName("finalReplyLabel")
            layout.addWidget(self.final_label)

        self.text_label = QLabel(message.text)
        self.text_label.setObjectName("textLabel")
        self.text_label.setWordWrap(True)
        # O4.5：QLabel 默认 AutoText 会把消息文本当富文本解析（含 <...> 时
        # 渲染错乱），统一按纯文本显示
        self.text_label.setTextFormat(Qt.PlainText)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.text_label)

        # 颜色一律由令牌驱动；默认深色（DARK_TOKENS 输出与历史默认一致）
        self.set_palette(DARK_TOKENS)

    def set_palette(self, tokens: dict[str, str]) -> None:
        """按当前主题令牌重刷气泡与内部标签颜色。"""
        style = bubble_style_for(self.message.source, self._theme, tokens)
        self.setStyleSheet(
            f"QFrame#{self.objectName()}{{{style}"
            f"border-radius:{tokens['radius_bubble']};padding:8px;}}"
        )
        # 气泡正文颜色沿用气泡样式里的 color 值，保证深浅主题对比度
        text_color = style.split("color:", 1)[1].split(";", 1)[0]
        # 弱化标签用正文色的半透明形式，在彩色气泡底上也能读
        label_color = fade(text_color, 0.72)
        self.source_label.setStyleSheet(
            f"font-size:{tokens['px_meta']};font-weight:600;background:transparent;"
            f"color:{label_color};"
        )
        self.text_label.setStyleSheet(
            f"background:transparent;color:{text_color};"
            f"font-size:{tokens['px_body']};"
        )
        if self.reasoning_label is not None:
            self.reasoning_label.setStyleSheet(
                f"background:{tokens['reasoning_bg']};"
                f"border:1px solid {tokens['reasoning_border']};"
                f"border-radius:6px;padding:7px;color:{tokens['reasoning_text']};"
                f"font-size:{tokens['px_meta']};"
            )
        if self.reasoning_toggle is not None:
            self.reasoning_toggle.setStyleSheet(
                "QToolButton{background:transparent;border:0;padding:2px;"
                f"font-size:{tokens['px_meta']};font-weight:600;text-align:left;"
                f"color:{label_color};}}"
            )
        if self.final_label is not None:
            self.final_label.setStyleSheet(
                f"font-size:{tokens['px_meta']};font-weight:600;background:transparent;"
                f"color:{label_color};"
            )

    def _toggle_reasoning(self, expanded: bool) -> None:
        if self.reasoning_label is None or self.reasoning_toggle is None:
            return
        self.reasoning_label.setVisible(expanded)
        self.reasoning_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)


class MessageList(QScrollArea):
    def __init__(self, theme: PairTheme | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._tokens = DARK_TOKENS
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setAlignment(Qt.AlignTop)
        self.layout.setSpacing(10)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.setWidget(self.container)
        self.bubbles: list[MessageBubble] = []
        # 与 bubbles 一一对应的行布局，用于分侧对齐与清理
        self._rows: list[QHBoxLayout] = []
        # 视口与容器底色随主题（否则深色主题下滚动区会露白底）
        self.set_palette(DARK_TOKENS)

    def set_palette(self, tokens: dict[str, str]) -> None:
        """切换主题令牌并同步重刷所有现存气泡。"""
        self._tokens = tokens
        background = f"background:{tokens['panel_bg']};"
        self.container.setStyleSheet(background)
        self.viewport().setStyleSheet(background)
        for bubble in self.bubbles:
            bubble.set_palette(tokens)

    def add_message(self, message: Message) -> MessageBubble:
        bubble = MessageBubble(message, theme=self._theme)
        bubble.set_palette(self._tokens)
        bubble.setMaximumWidth(self._bubble_max_width())
        self.bubbles.append(bubble)
        # 用户气泡靠右，其余靠左：用行布局加弹簧实现
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if message.source == MessageSource.USER:
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
        self.layout.addLayout(row)
        self._rows.append(row)
        return bubble

    def clear_messages(self) -> None:
        while self.bubbles:
            bubble = self.bubbles.pop()
            row = self._rows.pop()
            self.layout.removeItem(row)
            row.removeWidget(bubble)
            bubble.deleteLater()
            row.deleteLater()

    def resizeEvent(self, event) -> None:
        """按视口宽度动态收紧气泡最大宽度（不超过 720px）。"""
        super().resizeEvent(event)
        limit = self._bubble_max_width()
        for bubble in self.bubbles:
            bubble.setMaximumWidth(limit)

    def _bubble_max_width(self) -> int:
        width = self.viewport().width()
        if width <= 0:
            return 720
        return min(720, int(width * 0.78))
