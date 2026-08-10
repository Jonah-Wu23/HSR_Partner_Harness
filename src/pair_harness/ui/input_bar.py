from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class InputBar(QWidget):
    submitted = pyqtSignal(str, str)
    push_to_talk_pressed = pyqtSignal()
    push_to_talk_released = pyqtSignal()
    approval_mode_changed = pyqtSignal(str)

    # 审批模式下拉框的三项，取值为 ApprovalMode 枚举值
    APPROVAL_MODES = (
        ("request_approval", "请求批准"),
        ("review", "帮我审核"),
        ("full_auto", "完全允许运行"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        controls = QHBoxLayout()
        self.approval_mode_combo = QComboBox()
        self.approval_mode_combo.setObjectName("approvalModeCombo")
        for value, label in self.APPROVAL_MODES:
            self.approval_mode_combo.addItem(label, value)
        self.target_label = QLabel("发送给：")
        self.target_combo = QComboBox()
        self.target_combo.setObjectName("targetCombo")
        self.target_combo.addItem("白厄", "character")
        self.target_combo.addItem("神秘的古代机械", "assistant")
        self.vad_button = QPushButton("VAD")
        self.vad_button.setObjectName("vadButton")
        self.vad_button.setCheckable(True)
        self.ptt_button = QPushButton("按住说话")
        self.ptt_button.setObjectName("pttButton")
        self.text_input = QLineEdit()
        self.text_input.setObjectName("messageInput")
        self.text_input.setPlaceholderText("输入消息…")
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("sendButton")
        # 计划 A5：审批模式下拉框位于输入区左下角
        controls.addWidget(self.approval_mode_combo)
        controls.addWidget(self.target_label)
        controls.addWidget(self.target_combo)
        controls.addWidget(self.vad_button)
        controls.addWidget(self.ptt_button)
        controls.addWidget(self.text_input, 1)
        controls.addWidget(self.send_button)
        root.addLayout(controls)
        self.target_combo.currentIndexChanged.connect(self._sync_target)
        self.approval_mode_combo.currentIndexChanged.connect(self._sync_approval_mode)
        self.send_button.clicked.connect(self._submit)
        self.text_input.returnPressed.connect(self._submit)
        self.ptt_button.pressed.connect(self.push_to_talk_pressed)
        self.ptt_button.released.connect(self.push_to_talk_released)

    @property
    def target(self) -> str:
        return str(self.target_combo.currentData())

    @property
    def approval_mode(self) -> str:
        return str(self.approval_mode_combo.currentData())

    def set_approval_mode(self, mode: str) -> None:
        """恢复项目保存的审批模式，不触发切换信号。"""
        index = self.approval_mode_combo.findData(mode)
        if index < 0:
            raise ValueError(mode)
        self.approval_mode_combo.blockSignals(True)
        self.approval_mode_combo.setCurrentIndex(index)
        self.approval_mode_combo.blockSignals(False)

    def _sync_approval_mode(self) -> None:
        self.approval_mode_changed.emit(self.approval_mode)

    def set_collaboration_mode(self, enabled: bool) -> None:
        self.target_label.setVisible(enabled)
        self.target_combo.setVisible(enabled)
        if not enabled:
            self.target_combo.setCurrentIndex(0)
        self._sync_target()

    def _sync_target(self) -> None:
        self.vad_button.setVisible(self.target == "character")

    def _submit(self) -> None:
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self.submitted.emit(self.target, text)

