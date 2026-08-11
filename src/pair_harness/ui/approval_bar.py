from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from pair_harness.ui.theme import DARK_TOKENS


class ApprovalBar(QFrame):
    """输入区正下方的审批区（设计文档 §4.3）。

    - 请求批准模式：显示操作摘要与“允许 / 本对话内允许 / 否决”三个按钮，
      点击任一按钮后发出 decided 信号并立即隐藏；
    - 帮我审核模式：只显示审查状态与审查智能体的最终裁决文字，不提供按钮；
    - 完全允许运行模式：本控件不出现；
    - 多个审批请求排队，逐条显示，不同时展开。
    """

    # O1.7：裁决信号携带 approval_id 与决策，UI 按 id 对应 future
    decided = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("approvalBar")
        self._tokens = DARK_TOKENS
        self._queue: list[tuple[str, str, str]] = []
        self._current_id: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("approvalSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        buttons = QHBoxLayout()
        self.allow_button = QPushButton("允许")
        self.allow_button.setObjectName("approvalAllow")
        # 按钮语义化：样式由全局 QSS 按 kind 属性提供
        self.allow_button.setProperty("kind", "primary")
        self.allow_for_conversation_button = QPushButton("本对话内允许")
        self.allow_for_conversation_button.setObjectName("approvalAllowForConversation")
        self.allow_for_conversation_button.setProperty("kind", "ghost")
        self.deny_button = QPushButton("否决")
        self.deny_button.setObjectName("approvalDeny")
        self.deny_button.setProperty("kind", "danger")
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
        self.set_palette(DARK_TOKENS)
        self.hide()

    def set_palette(self, tokens: dict) -> None:
        """按主题令牌重刷容器与标签样式（警示感：卡片底 + 警告色描边）。"""
        self._tokens = tokens
        self.setStyleSheet(
            "QFrame#approvalBar{"
            f"background:{tokens['card_bg']};"
            f"border:1px solid {tokens['warning']};"
            f"border-radius:{tokens['radius_card']};"
            f"color:{tokens['text_primary']};}}"
        )
        self.summary_label.setStyleSheet(
            f"color:{tokens['text_primary']};font-size:13px;"
        )
        # 裁决标签颜色依赖当前文本，切主题时同步重刷
        self._style_verdict(self.verdict_label.text())

    def _style_verdict(self, text: str) -> None:
        """按裁决内容着色：允许=success，否决=danger，其余=text_secondary。"""
        if text.startswith("审查结果：允许"):
            color = self._tokens["success"]
        elif text.startswith("审查结果：否决"):
            color = self._tokens["danger"]
        else:
            color = self._tokens["text_secondary"]
        self.verdict_label.setStyleSheet(f"color:{color};font-size:13px;")

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
        """请求批准模式：显示操作摘要与三个按钮，记录当前审批 id。"""
        self._current_id = approval_id
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
        self._style_verdict(text)
        self.verdict_label.show()
        self.show()

    def _decide(self, decision: str) -> None:
        self.hide()
        if self._queue:
            self._queue.pop(0)
        self.decided.emit(self._current_id, decision)
        if self._queue:
            self.show_request(*self._queue[0])
