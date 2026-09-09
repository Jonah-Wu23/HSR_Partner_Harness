from __future__ import annotations

import threading
from collections import deque

from pair_harness.core.contracts import SpeechRequest

# DashScope SDK 的 api_key / base_websocket_api_url 是进程级全局变量；
# ASR 与 TTS 工作线程可能同时构造 SDK，必须共用同一把进程级锁，避免
# 一个账号/端点的配置被另一个正在初始化的 SDK 覆盖。
DASHSCOPE_CONFIG_LOCK = threading.Lock()


class SpeechQueue:
    """待朗读语音队列（V0.3.9 契约 §6：单调 epoch）。

    playing 表示正在播放；播放期间暂停 VAD，停止或播完后恢复。

    每次中断（用户发送、新角色完整消息、显式停止/跳过/切换/远程认领）都
    递增 epoch：入队条目记录入队时刻的 epoch，pop_next 只返回当前 epoch 的
    条目，旧 epoch 的迟到条目直接丢弃。播放循环按 epoch 校验后才写播放器，
    保证旧 epoch 的迟到 PCM 永不写入。skip_current 递增 epoch 但把待播项
    改挂到新 epoch——跳过只放弃当前句，不清空队列。
    """

    def __init__(self) -> None:
        self._items: deque[tuple[int, SpeechRequest]] = deque()
        self._playing = False
        self._epoch = 0

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def pending(self) -> int:
        return sum(1 for epoch, _ in self._items if epoch == self._epoch)

    @property
    def pending_message_id(self) -> str | None:
        """队首待播条目的 message_id（无待播项时 None）。"""
        for epoch, request in self._items:
            if epoch == self._epoch:
                return request.message_id
        return None

    def enqueue(self, request: SpeechRequest) -> None:
        self._items.append((self._epoch, request))

    def pop_next(self) -> SpeechRequest | None:
        while self._items:
            epoch, request = self._items.popleft()
            if epoch == self._epoch:
                return request
        return None

    def begin_playback(self) -> None:
        self._playing = True

    def end_playback(self) -> None:
        self._playing = False

    def interrupt(self) -> int:
        """中断：epoch 递增、清空队列、复位 playing，返回新 epoch。"""
        self._epoch += 1
        self._items.clear()
        self._playing = False
        return self._epoch

    def skip_current(self) -> int:
        """跳过当前句：epoch 递增，待播项改挂新 epoch（不清空队列）。"""
        self._epoch += 1
        self._items = deque(
            (self._epoch, request) for _, request in self._items
        )
        return self._epoch

    def stop(self) -> None:
        """停止播放并清空队列，VAD 随之恢复（等价于一次中断）。"""
        self.interrupt()
