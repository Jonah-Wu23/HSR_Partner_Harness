from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class AudioControls(QWidget):
    """语音交互状态条：VAD 指示灯与停止语音按钮。

    set_vad_state 反映监听、说话、识别和误触发状态；
    set_playing 表示正在播放语音，同时启用停止按钮。
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.vad_label = QLabel("待机")
        self.vad_label.setObjectName("vadStatus")
        self.vad_label.setStyleSheet("color:#9AA3B2;font-size:12px;")
        self.stop_button = QPushButton("停止语音")
        self.stop_button.setObjectName("stopSpeech")
        self.stop_button.setEnabled(False)
        root.addWidget(self.vad_label)
        root.addStretch(1)
        root.addWidget(self.stop_button)
        self.stop_button.clicked.connect(self.stop_requested)

    def set_vad_state(self, state: str) -> None:
        self.vad_label.setText(self._VAD_LABELS.get(state, state))

    def set_playing(self, playing: bool) -> None:
        self.stop_button.setEnabled(playing)
        if playing:
            self.vad_label.setText("播放中")
