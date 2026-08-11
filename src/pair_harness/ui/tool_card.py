from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QToolButton, QVBoxLayout, QWidget

from pair_harness.core.contracts import ToolRun


class ToolCard(QFrame):
    """“摘要优先的折叠卡片”：命令、变更与检查结果默认折叠。

    审批交互统一在输入区下方的 ApprovalBar，本卡片只展示状态。
    """

    def __init__(self, tool_run: ToolRun, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tool_call_id = tool_run.tool_call_id
        self.setObjectName("toolCard")
        self.setStyleSheet(
            "QFrame#toolCard{background:#17191D;border:1px solid #373A40;"
            "border-radius:8px;color:#D1D5DB;}"
        )
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

    @property
    def expanded(self) -> bool:
        return self.toggle.isChecked()

    def _toggle_details(self, expanded: bool) -> None:
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.UpArrow)
        self.details_label.setVisible(expanded)

    def update_run(self, tool_run: ToolRun) -> None:
        if tool_run.tool_call_id != self.tool_call_id:
            raise ValueError("cannot update a card with another tool_call_id")
        self.toggle.setText(tool_run.title)
        self.status_label.setText(tool_run.status)
        self.summary_label.setText(tool_run.summary)
        self.details_label.setText(tool_run.details)

