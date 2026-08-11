from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QToolButton, QVBoxLayout, QWidget

from pair_harness.core.contracts import ToolRun
from pair_harness.ui.theme import DARK_TOKENS, status_color


class ToolCard(QFrame):
    """“摘要优先的折叠卡片”：命令、变更与检查结果默认折叠。

    审批交互统一在输入区下方的 ApprovalBar，本卡片只展示状态。
    视觉为“上下文卡片”：卡片底色 + 左侧 3px 状态色条，全部色值取自主题令牌。
    """

    def __init__(self, tool_run: ToolRun, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tool_call_id = tool_run.tool_call_id
        self._status = tool_run.status
        self._tokens = DARK_TOKENS
        self.setObjectName("toolCard")
        layout = QVBoxLayout(self)
        self.toggle = QToolButton(text=tool_run.title, checkable=True, checked=False)
        self.toggle.setObjectName("toolToggle")
        # O4.5：魔法数字换 Qt 枚举（2=ToolButtonTextBesideIcon，1/2=UpArrow/DownArrow）
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.UpArrow)
        self.status_label = QLabel(tool_run.status)
        self.status_label.setObjectName("toolStatus")
        self.summary_label = QLabel(tool_run.summary)
        self.summary_label.setObjectName("toolSummary")
        self.details_label = QLabel(tool_run.details)
        self.details_label.setObjectName("toolDetails")
        self.details_label.setWordWrap(True)
        # O4.5：QLabel 默认 AutoText 会把内容当富文本解析，统一按纯文本显示
        self.status_label.setTextFormat(Qt.PlainText)
        self.summary_label.setTextFormat(Qt.PlainText)
        self.details_label.setTextFormat(Qt.PlainText)
        self.details_label.setVisible(False)
        self.toggle.toggled.connect(self._toggle_details)
        layout.addWidget(self.toggle)
        layout.addWidget(self.status_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.details_label)
        self._restyle()

    @property
    def expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_palette(self, tokens: dict[str, str]) -> None:
        """按主题令牌重刷卡片样式。"""
        self._tokens = tokens
        self._restyle()

    def _restyle(self) -> None:
        t = self._tokens
        color = status_color(self._status, t)
        # 卡片本体：底色 + 细边框 + 左侧 3px 状态色条
        self.setStyleSheet(
            f"QFrame#toolCard{{background:{t['card_bg']};"
            f"border:1px solid {t['border']};border-left:3px solid {color};"
            f"border-radius:{t['radius_card']};color:{t['text_primary']};}}"
        )
        self.status_label.setStyleSheet(f"color:{color};font-weight:600;")
        self.summary_label.setStyleSheet(f"color:{t['text_primary']};")
        # 详情区：等宽字体的“代码块”观感
        self.details_label.setStyleSheet(
            f"font-family:{t['font_mono']};background:{t['reasoning_bg']};"
            f"border:1px solid {t['reasoning_border']};border-radius:6px;"
            f"padding:8px;color:{t['reasoning_text']};"
        )

    def _toggle_details(self, expanded: bool) -> None:
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.UpArrow)
        self.details_label.setVisible(expanded)

    def update_run(self, tool_run: ToolRun) -> None:
        if tool_run.tool_call_id != self.tool_call_id:
            raise ValueError("cannot update a card with another tool_call_id")
        self._status = tool_run.status
        self.toggle.setText(tool_run.title)
        self.status_label.setText(tool_run.status)
        self.summary_label.setText(tool_run.summary)
        self.details_label.setText(tool_run.details)
        # 状态变化后重刷状态色条与状态文字颜色
        self._restyle()
