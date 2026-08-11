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
    reasoning_effort_changed = pyqtSignal(str)

    # 审批模式下拉框的三项，取值为 ApprovalMode 枚举值
    APPROVAL_MODES = (
        ("request_approval", "请求批准"),
        ("review", "帮我审核"),
        ("full_auto", "完全允许运行"),
    )
    REASONING_EFFORTS = (
        ("auto", "思考：自动"),
        ("low", "思考：低"),
        ("high", "思考：高"),
        ("max", "思考：最大"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 主题令牌（set_palette 注入），默认 None 表示尚未应用主题
        self._tokens: dict[str, str] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(6)
        self.approval_mode_combo = QComboBox()
        self.approval_mode_combo.setObjectName("approvalModeCombo")
        for value, label in self.APPROVAL_MODES:
            self.approval_mode_combo.addItem(label, value)
        self.reasoning_effort_combo = QComboBox()
        self.reasoning_effort_combo.setObjectName("reasoningEffortCombo")
        for value, label in self.REASONING_EFFORTS:
            self.reasoning_effort_combo.addItem(label, value)
        self.reasoning_effort_combo.setCurrentIndex(1)
        self.target_label = QLabel("发送给：")
        self.target_combo = QComboBox()
        self.target_combo.setObjectName("targetCombo")
        self.target_combo.addItem("白厄", "character")
        self.target_combo.addItem("神秘的古代机械", "assistant")
        self.vad_button = QPushButton("VAD")
        self.vad_button.setObjectName("vadButton")
        self.vad_button.setCheckable(True)
        self.vad_button.setProperty("kind", "ghost")
        self.ptt_button = QPushButton("按住说话")
        self.ptt_button.setObjectName("pttButton")
        self.ptt_button.setProperty("kind", "ghost")
        self.text_input = QLineEdit()
        self.text_input.setObjectName("messageInput")
        self.text_input.setPlaceholderText("输入消息…")
        self.text_input.setMinimumHeight(36)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("sendButton")
        self.send_button.setProperty("kind", "primary")
        # 上行（设置行）：审批模式 / 思考档位 / 发送对象，其余留白
        settings = QHBoxLayout()
        settings.setSpacing(8)
        settings.addWidget(self.approval_mode_combo)
        settings.addWidget(self.reasoning_effort_combo)
        settings.addWidget(self.target_label)
        settings.addWidget(self.target_combo)
        settings.addStretch(1)
        # 下行（输入行）：语音按钮 + 输入框 + 发送
        controls = QHBoxLayout()
        controls.addWidget(self.vad_button)
        controls.addWidget(self.ptt_button)
        controls.addWidget(self.text_input, 1)
        controls.addWidget(self.send_button)
        root.addLayout(settings)
        root.addLayout(controls)
        self.target_combo.currentIndexChanged.connect(self._sync_target)
        self.approval_mode_combo.currentIndexChanged.connect(self._sync_approval_mode)
        self.reasoning_effort_combo.currentIndexChanged.connect(
            self._sync_reasoning_effort
        )
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

    @property
    def reasoning_effort(self) -> str:
        return str(self.reasoning_effort_combo.currentData())

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

    def set_reasoning_effort(self, effort: str) -> None:
        """恢复项目保存的思考档位，不触发切换信号。"""
        index = self.reasoning_effort_combo.findData(effort)
        if index < 0:
            raise ValueError(effort)
        self.reasoning_effort_combo.blockSignals(True)
        self.reasoning_effort_combo.setCurrentIndex(index)
        self.reasoning_effort_combo.blockSignals(False)

    def _sync_reasoning_effort(self) -> None:
        self.reasoning_effort_changed.emit(self.reasoning_effort)

    def set_collaboration_mode(self, enabled: bool) -> None:
        self.target_label.setVisible(enabled)
        self.target_combo.setVisible(enabled)
        if not enabled:
            self.target_combo.setCurrentIndex(0)
        self._sync_target()
        # 隐藏期间错过主题切换的控件，重新可见后强制按当前 QSS 重刷
        for widget in (self.target_label, self.target_combo, self.vad_button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _sync_target(self) -> None:
        self.vad_button.setVisible(self.target == "character")

    def set_palette(self, tokens: dict[str, str]) -> None:
        """注入主题令牌并强制重刷样式。

        全局 QSS 切换后，kind 等动态属性变体需要 unpolish/polish 才会换色。
        """
        self._tokens = tokens
        # 全局 QWidget 颜色规则到不了特定子标签，显式给令牌色
        self.target_label.setStyleSheet(f"color:{tokens['text_secondary']};")
        # Qt 怪癖：隐藏/可见切换过的 QComboBox 在运行时换主题会滞留旧调色板，
        # unpolish/polish 清不掉；令牌级内联 QSS 能稳定重刷
        combo_qss = (
            f"QComboBox{{background:{tokens['card_bg']};"
            f"border:1px solid {tokens['border']};"
            f"border-radius:{tokens['radius_control']};padding:5px 10px;"
            f"min-height:20px;color:{tokens['text_primary']};}}"
            f"QComboBox:hover{{border-color:{tokens['border_strong']};}}"
            f"QComboBox:focus{{border-color:{tokens['accent']};}}"
            "QComboBox::drop-down{border:0;width:22px;}"
            f"QComboBox QAbstractItemView{{background:{tokens['panel_bg']};"
            f"border:1px solid {tokens['border_strong']};"
            f"selection-background-color:{tokens['accent_soft']};"
            f"selection-color:{tokens['text_primary']};outline:0;}}"
        )
        for combo in (
            self.approval_mode_combo,
            self.reasoning_effort_combo,
            self.target_combo,
        ):
            combo.setStyleSheet(combo_qss)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        for child in self.findChildren(QWidget):
            child.style().unpolish(child)
            child.style().polish(child)

    def set_asr_interim(self, text: str) -> None:
        """ASR partial 回显（B2.6 设计 §5.5）：显示在输入框，空串清空。

        不改动输入区既有行为：不触发提交，不清空用户已输入内容
        （转写只在输入框空闲时顶替显示）。
        """
        if text:
            self.text_input.setText(text)
        else:
            self.text_input.clear()

    def _submit(self) -> None:
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self.submitted.emit(self.target, text)
