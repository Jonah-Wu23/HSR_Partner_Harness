from __future__ import annotations

import threading
from collections import deque

from pair_harness.core.contracts import SpeechRequest

# DashScope SDK 的 api_key / base_websocket_api_url 是进程级全局变量；
# ASR 与 TTS 工作线程可能同时构造 SDK，必须共用同一把进程级锁，避免
# 一个账号/端点的配置被另一个正在初始化的 SDK 覆盖。
DASHSCOPE_CONFIG_LOCK = threading.Lock()


class SpeechQueue:
    """待朗读语音队列。

    playing 表示正在播放；播放期间暂停 VAD，停止或播完后恢复。
    """

    def __init__(self) -> None:
        self._items: deque[SpeechRequest] = deque()
        self._playing = False

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def pending(self) -> int:
        return len(self._items)

    def enqueue(self, request: SpeechRequest) -> None:
        self._items.append(request)

    def pop_next(self) -> SpeechRequest | None:
        return self._items.popleft() if self._items else None

    def begin_playback(self) -> None:
        self._playing = True

    def end_playback(self) -> None:
        self._playing = False

    def stop(self) -> None:
        """停止播放并清空队列，VAD 随之恢复。"""
        self._items.clear()
        self._playing = False
