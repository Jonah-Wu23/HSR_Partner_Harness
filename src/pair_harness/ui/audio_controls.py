from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from pair_harness.ui.theme import DARK_TOKENS


class AudioControls(QWidget):
    """语音交互状态条：VAD 指示灯与停止语音按钮。

    set_vad_state 反映监听、说话、识别和误触发状态；
    set_playing 表示正在播放语音，同时启用停止按钮。
    状态圆点颜色取自主题令牌，set_palette 用于主题切换时重刷。
    """

    stop_requested = pyqtSignal()

    _VAD_LABELS = {
        "idle": "待机",
        "listening": "聆听中",
        "speech_started": "说话中",
        "speech_ended": "识别中",
        "false_trigger": "误触发",
        "playing": "播放中",
    }

    # 各状态圆点对应的令牌键
    _DOT_TOKEN_KEYS = {
        "idle": "text_muted",
        "listening": "success",
        "speech_started": "accent",
        "speech_ended": "text_secondary",
        "false_trigger": "warning",
        "playing": "accent",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = DARK_TOKENS
        self._state = "idle"
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.vad_dot = QLabel()
        self.vad_dot.setObjectName("vadDot")
        self.vad_dot.setFixedSize(10, 10)
        self.vad_label = QLabel("待机")
        self.vad_label.setObjectName("vadStatus")
        self.stop_button = QPushButton("停止语音")
        self.stop_button.setObjectName("stopSpeech")
        self.stop_button.setProperty("kind", "danger")
        self.stop_button.setEnabled(False)
        root.addWidget(self.vad_dot, 0, Qt.AlignVCenter)
        root.addWidget(self.vad_label)
        root.addStretch(1)
        root.addWidget(self.stop_button)
        self.stop_button.clicked.connect(self.stop_requested)
        self._refresh_style()

    def set_palette(self, tokens: dict[str, str]) -> None:
        """主题切换时更新令牌并按当前状态重刷颜色。"""
        self._tokens = tokens
        self._refresh_style()

    def set_vad_state(self, state: str) -> None:
        self._state = state
        self.vad_label.setText(self._VAD_LABELS.get(state, state))
        self._refresh_style()

    def set_playing(self, playing: bool) -> None:
        self.stop_button.setEnabled(playing)
        if playing:
            self._state = "playing"
            self.vad_label.setText("播放中")
            self._refresh_style()

    def _refresh_style(self) -> None:
        t = self._tokens
        color = t[self._DOT_TOKEN_KEYS.get(self._state, "text_muted")]
        self.vad_dot.setStyleSheet(
            f"background:{color};border-radius:5px;"
        )
        self.vad_label.setStyleSheet(
            f"color:{t['text_secondary']};font-size:12px;"
        )
