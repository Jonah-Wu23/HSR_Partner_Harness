from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ApprovalBar(QFrame):
    """输入区正下方的审批区（设计文档 §4.3）。

    - 请求批准模式：显示操作摘要与“允许 / 本对话内允许 / 否决”三个按钮，
      点击任一按钮后发出 decided 信号并立即隐藏；
    - 帮我审核模式：只显示审查状态与审查智能体的最终裁决文字，不提供按钮；
    - 完全允许运行模式：本控件不出现；
    - 多个审批请求排队，逐条显示，不同时展开。
    """

    decided = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("approvalBar")
        self.setStyleSheet(
            "QFrame#approvalBar{background:#1B1E25;border:1px solid #373A40;"
            "border-radius:8px;color:#E5E7EB;}"
        )
        self._queue: list[tuple[str, str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("approvalSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        buttons = QHBoxLayout()
        self.allow_button = QPushButton("允许")
        self.allow_button.setObjectName("approvalAllow")
        self.allow_for_conversation_button = QPushButton("本对话内允许")
        self.allow_for_conversation_button.setObjectName("approvalAllowForConversation")
        self.deny_button = QPushButton("否决")
        self.deny_button.setObjectName("approvalDeny")
        buttons.addWidget(self.allow_button)
        buttons.addWidget(self.allow_for_conversation_button)
        buttons.addWidget(self.deny_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.verdict_label = QLabel()
        self.verdict_label.setObjectName("approvalVerdict")
        self.verdict_label.setWordWrap(True)
        self.verdict_label.setVisible(False)
        layout.addWidget(self.verdict_label)

        self.allow_button.clicked.connect(lambda: self._decide("allow"))
        self.allow_for_conversation_button.clicked.connect(
            lambda: self._decide("allow_for_conversation")
        )
        self.deny_button.clicked.connect(lambda: self._decide("deny"))
        self.hide()

    @property
    def pending_count(self) -> int:
        """等待展示的审批请求数量。"""
        return len(self._queue)

    def enqueue_request(self, approval_id: str, summary: str, reason: str) -> None:
        """加入审批请求队列；当前无展示项时立即展开。"""
        self._queue.append((approval_id, summary, reason))
        if not self.isVisible():
            self.show_request(*self._queue[0])

    def show_request(self, approval_id: str, summary: str, reason: str) -> None:
        """请求批准模式：显示操作摘要与三个按钮。"""
        del approval_id
        self.summary_label.setText(f"{summary}（{reason}）" if reason else summary)
        self.allow_button.show()
        self.allow_for_conversation_button.show()
        self.deny_button.show()
        self.verdict_label.hide()
        self.show()

    def show_review(self, text: str) -> None:
        """帮我审核模式：只显示审查状态或裁决文字，不提供按钮。"""
        self.summary_label.setText("")
        self.allow_button.hide()
        self.allow_for_conversation_button.hide()
        self.deny_button.hide()
        self.verdict_label.setText(text)
        self.verdict_label.show()
        self.show()

    def _decide(self, decision: str) -> None:
        self.hide()
        if self._queue:
            self._queue.pop(0)
        self.decided.emit(decision)
        if self._queue:
            self.show_request(*self._queue[0])
