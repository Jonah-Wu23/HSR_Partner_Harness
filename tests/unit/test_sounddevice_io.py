"""AudioPlayer 长生命周期输出流测试（V0.2 M2-4）。

以假 sounddevice 模块驱动播放器，不触真实音频设备：验证输出流
惰性创建/异常重建、块间与空闲间隙不断流、有界缓冲钳制超速生产者、
stop 立即清缓冲并丢弃积压、close 后写入为无操作。
"""

from __future__ import annotations

import sys
import time
import types
from collections.abc import Iterator
from unittest import mock

import numpy as np
import pytest

# 导入 sounddevice_io 前注入假 sounddevice：无音频设备环境下不触 PortAudio
fake_sd = types.ModuleType("sounddevice")


class FakeOutputStream:
    """记录写入块与关闭状态的假 OutputStream。"""

    instances: list["FakeOutputStream"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.writes: list[np.ndarray] = []
        self.started = False
        self.closed = False
        FakeOutputStream.instances.append(self)

    def start(self) -> None:
        self.started = True

    def write(self, samples) -> None:
        self.writes.append(np.array(samples, copy=True))

    def stop(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


fake_sd.OutputStream = FakeOutputStream

with mock.patch.dict(sys.modules, {"sounddevice": fake_sd}):
    from pair_harness.adapters.audio.sounddevice_io import AudioPlayer


def _chunk(ms: int = 20) -> bytes:
    """ms 毫秒 @ 16 kHz 单声道 int16 的静音块。"""
    return b"\x00" * (16_000 * 2 * ms // 1000)


@pytest.fixture(autouse=True)
def _fresh_streams() -> Iterator[None]:
    """每个用例独立统计创建的流实例，并还原可能被替换的慢写流。"""
    FakeOutputStream.instances.clear()
    fake_sd.OutputStream = FakeOutputStream
    yield


def _wait_stream(index: int = 0, timeout: float = 2.0) -> FakeOutputStream:
    """等待播放线程惰性创建第 index 个流（建流在消费线程中异步发生）。"""
    deadline = time.monotonic() + timeout
    while len(FakeOutputStream.instances) <= index and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(FakeOutputStream.instances) > index
    return FakeOutputStream.instances[index]


def _wait_writes(stream: FakeOutputStream, count: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while len(stream.writes) < count and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(stream.writes) == count


# ---------------------------------------------------------------- 长生命周期流


def test_single_stream_reused_across_chunks_and_idle_gaps() -> None:
    """块间间隙与空闲等待不关闭流：全程单一 OutputStream。"""
    player = AudioPlayer(sample_rate=16_000, channels=1, buffer_chunks=16)
    player.start()
    try:
        player.play_blocking(_chunk())
        player.play_blocking(_chunk())
        stream = _wait_stream()
        _wait_writes(stream, 2)
        # 空闲间隙（缓冲耗尽、线程短暂等待）后继续写同一流
        player.play_blocking(_chunk())
        _wait_writes(stream, 3)

        assert len(FakeOutputStream.instances) == 1  # 全程单一流
        assert not stream.closed  # 长生命周期：句间不关闭
        assert stream.started
        assert stream.kwargs["samplerate"] == 16_000
    finally:
        player.close()
        assert _wait_stream().closed  # shutdown 才关闭


def test_stream_created_lazily_on_first_chunk() -> None:
    """输出流惰性创建：线程空闲时不建流，首块写入才创建。"""
    player = AudioPlayer(sample_rate=16_000, channels=1)
    player.start()
    try:
        time.sleep(0.1)
        assert FakeOutputStream.instances == []
        player.play_blocking(_chunk())
        stream = _wait_stream()
        _wait_writes(stream, 1)
        assert len(FakeOutputStream.instances) == 1
    finally:
        player.close()


# ---------------------------------------------------------------- 有界缓冲


def test_bounded_buffer_throttles_fast_producer() -> None:
    """缓冲上限钳制生产节奏：慢消费下批量入队被阻塞，且不丢块。"""

    class SlowStream(FakeOutputStream):
        def write(self, samples) -> None:
            time.sleep(0.05)  # 慢消费：每次写流 50 ms
            super().write(samples)

    fake_sd.OutputStream = SlowStream
    player = AudioPlayer(sample_rate=16_000, channels=1, buffer_chunks=2)
    player.start()
    try:
        started = time.monotonic()
        for _ in range(10):
            player.play_blocking(_chunk())
        elapsed = time.monotonic() - started
        # 缓冲上限 2 块：10 块不可能瞬间全部入队（生产被消费节奏钳制）
        assert elapsed >= 0.15
        stream = _wait_stream()
        _wait_writes(stream, 10)
    finally:
        player.close()
        fake_sd.OutputStream = FakeOutputStream


# ---------------------------------------------------------------- stop / close


def test_stop_clears_buffer_immediately_and_rebuilds_stream() -> None:
    """stop 立即清空缓冲并关闭流（丢弃积压）；下次播放惰性重建新流。"""

    class SlowStream(FakeOutputStream):
        def write(self, samples) -> None:
            time.sleep(0.05)
            super().write(samples)

    fake_sd.OutputStream = SlowStream
    player = AudioPlayer(sample_rate=16_000, channels=1, buffer_chunks=2)
    player.start()
    try:
        for _ in range(6):
            player.play_blocking(_chunk())
        time.sleep(0.03)  # 慢消费下缓冲必有积压
        assert len(player._buffer) > 0

        started = time.monotonic()
        player.stop()
        assert time.monotonic() - started < 0.2  # 立即返回，不等慢消费
        assert len(player._buffer) == 0  # 缓冲被清空
        assert _wait_stream().closed  # 流被关闭（丢弃积压）

        # 停止后仍可播放：惰性重建新流
        player.play_blocking(_chunk())
        rebuilt = _wait_stream(1)
        _wait_writes(rebuilt, 1)
        assert len(FakeOutputStream.instances) == 2  # 新流已重建
        assert len(rebuilt.writes) == 1
    finally:
        player.close()
        fake_sd.OutputStream = FakeOutputStream


def test_play_blocking_after_close_is_noop() -> None:
    """shutdown 后写入为无操作：不抛错、不重启线程、不建流。"""
    player = AudioPlayer(sample_rate=16_000, channels=1)
    player.start()
    player.close()
    player.play_blocking(_chunk())
    time.sleep(0.1)
    assert FakeOutputStream.instances == []


def test_empty_pcm_blocks_are_ignored() -> None:
    """空 PCM 块（final 标记）不写入缓冲。"""
    player = AudioPlayer(sample_rate=16_000, channels=1)
    player.start()
    try:
        player.play_blocking(b"")
        player.play_blocking(_chunk())
        stream = _wait_stream()
        _wait_writes(stream, 1)
        assert len(stream.writes) == 1
    finally:
        player.close()
