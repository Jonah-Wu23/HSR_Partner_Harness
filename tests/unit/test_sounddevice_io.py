from __future__ import annotations

import importlib
import sys
import time
import types
from unittest import mock

import numpy as np
import pytest

import pair_harness.adapters.audio as audio_package

# CI 与开发机上没有可用的声卡和麦克风，PortAudio 的输入输出流是硬件边界。导入
# sounddevice_io 时临时换上替身 sounddevice 模块，播放器与采集逻辑照常运行。
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

    def abort(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeCallbackAbort(Exception):
    """对应 sounddevice.CallbackAbort。"""


fake_sd.OutputStream = FakeOutputStream
fake_sd.CallbackAbort = FakeCallbackAbort

# 导入后还原 sys.modules 与包属性，绑定替身的模块只留在本文件。
_previous_module = getattr(audio_package, "sounddevice_io", None)
with mock.patch.dict(sys.modules, {"sounddevice": fake_sd}):
    sys.modules.pop("pair_harness.adapters.audio.sounddevice_io", None)
    sounddevice_io = importlib.import_module("pair_harness.adapters.audio.sounddevice_io")
if _previous_module is None:
    del audio_package.sounddevice_io
else:
    audio_package.sounddevice_io = _previous_module

AudioPlayer = sounddevice_io.AudioPlayer
MicrophoneCapture = sounddevice_io.MicrophoneCapture
_input_device_candidates = sounddevice_io._input_device_candidates
_resample_input = sounddevice_io._resample_input


def _chunk(ms: int = 20) -> bytes:
    """ms 毫秒 @ 16 kHz 单声道 int16 的静音块。"""
    return b"\x00" * (16_000 * 2 * ms // 1000)


@pytest.fixture(autouse=True)
def _fresh_streams() -> None:
    """每个用例独立统计创建的流实例；用例对替身模块的替换经 monkeypatch 还原。"""
    FakeOutputStream.instances.clear()


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


def test_bounded_buffer_throttles_fast_producer(monkeypatch) -> None:
    """缓冲上限钳制生产节奏：慢消费下批量入队被阻塞，且不丢块。"""

    class SlowStream(FakeOutputStream):
        def write(self, samples) -> None:
            time.sleep(0.05)  # 慢消费：每次写流 50 ms
            super().write(samples)

    monkeypatch.setattr(fake_sd, "OutputStream", SlowStream)
    player = AudioPlayer(sample_rate=16_000, channels=1, buffer_chunks=2)
    player.start()
    try:
        started = time.monotonic()
        for _ in range(10):
            player.play_blocking(_chunk())
        elapsed = time.monotonic() - started
        # 缓冲上限 2 块，10 块不可能瞬间全部入队
        assert elapsed >= 0.15
        stream = _wait_stream()
        _wait_writes(stream, 10)
    finally:
        player.close()


# ---------------------------------------------------------------- stop / close


def test_stop_discards_backlog_immediately_and_rebuilds_stream(monkeypatch) -> None:
    """stop 立即丢弃积压并关闭流；下次播放惰性重建新流。"""

    class SlowStream(FakeOutputStream):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.writing = False
            self.closed_while_writing = False

        def write(self, samples) -> None:
            self.writing = True
            try:
                time.sleep(0.05)
                super().write(samples)
            finally:
                self.writing = False

        def close(self) -> None:
            self.closed_while_writing |= self.writing
            super().close()

    monkeypatch.setattr(fake_sd, "OutputStream", SlowStream)
    player = AudioPlayer(sample_rate=16_000, channels=1, buffer_chunks=2)
    player.start()
    try:
        # 缓冲上限 2 块：最后一块入队返回时，至少它还留在缓冲里没写出
        for _ in range(6):
            player.play_blocking(_chunk())
        first = _wait_stream()

        started = time.monotonic()
        player.stop()
        assert time.monotonic() - started < 0.2  # 立即返回，不等慢消费
        assert first.closed
        assert not first.closed_while_writing  # close 不与 write 并发
        written = len(first.writes)
        assert written < 6  # 积压的块被丢弃
        time.sleep(0.1)
        assert len(first.writes) == written

        # 停止后仍可播放：惰性重建新流
        player.play_blocking(_chunk())
        rebuilt = _wait_stream(1)
        _wait_writes(rebuilt, 1)
        assert len(FakeOutputStream.instances) == 2
    finally:
        player.close()


def test_output_failure_raised_to_producer_then_stream_rebuilt(monkeypatch) -> None:
    """写流失败如实抛给生产者；错误上报后下一次播放重建输出流。"""

    class BrokenStream(FakeOutputStream):
        def write(self, samples) -> None:
            raise OSError("device unplugged")

    monkeypatch.setattr(fake_sd, "OutputStream", BrokenStream)
    player = AudioPlayer(sample_rate=16_000, channels=1)
    player.start()
    try:
        player.play_blocking(_chunk())
        with pytest.raises(RuntimeError, match="device unplugged"):
            player.wait_until_idle()
        assert _wait_stream().closed

        monkeypatch.setattr(fake_sd, "OutputStream", FakeOutputStream)
        player.play_blocking(_chunk())
        rebuilt = _wait_stream(1)
        _wait_writes(rebuilt, 1)
    finally:
        player.close()


async def test_capture_callback_error_reaches_chunks_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """输入回调出错时中止输入流，chunks() 的消费者收到该异常并结束。"""
    streams: list[object] = []

    class FakeRawInputStream:
        def __init__(self, **kwargs) -> None:
            self.callback = kwargs["callback"]
            streams.append(self)

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    device = {
        "name": "Mic",
        "max_input_channels": 1,
        "hostapi": 1,
        "default_samplerate": 16_000.0,
    }
    monkeypatch.setattr(fake_sd, "RawInputStream", FakeRawInputStream, raising=False)
    monkeypatch.setattr(fake_sd, "default", types.SimpleNamespace(device=(0, 0)), raising=False)
    monkeypatch.setattr(
        fake_sd,
        "query_devices",
        lambda index=None: [device] if index is None else device,
        raising=False,
    )

    async with MicrophoneCapture() as capture:
        # 半个 int16 采样无法解码，重采样在回调里抛错
        with pytest.raises(FakeCallbackAbort):
            streams[0].callback(b"\x00", 1, None, None)
        with pytest.raises(ValueError, match="buffer size must be a multiple of element size"):
            async for _ in capture.chunks():
                pass


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


def test_input_device_candidates_put_default_first_then_wdm_ks_microphones(monkeypatch) -> None:
    """Windows MME 默认输入拒绝 16 kHz 时依次回退到 WDM-KS 麦克风与其余输入设备。"""
    devices = [
        {"name": "扬声器 (Realtek)", "max_input_channels": 0, "hostapi": 3},
        {"name": "麦克风 (Realtek)", "max_input_channels": 2, "hostapi": 3},
        {"name": "默认设备", "max_input_channels": 2, "hostapi": 0},
        {"name": "外部 Mic", "max_input_channels": 1, "hostapi": 1},
    ]
    monkeypatch.setattr(fake_sd, "default", types.SimpleNamespace(device=(2, 2)), raising=False)
    monkeypatch.setattr(fake_sd, "query_devices", lambda: devices, raising=False)

    # 没有输入通道的扬声器被跳过
    assert _input_device_candidates() == (2, 1, 3)


def test_input_device_candidates_without_default_input(monkeypatch) -> None:
    monkeypatch.setattr(
        fake_sd, "default", types.SimpleNamespace(device=(None, None)), raising=False
    )
    monkeypatch.setattr(
        fake_sd,
        "query_devices",
        lambda: [{"name": "Mic", "max_input_channels": 1, "hostapi": 1}],
        raising=False,
    )

    assert _input_device_candidates() == (0,)


def test_resample_input_downmixes_stereo_and_resamples() -> None:
    # 16 kHz 立体声 → 8 kHz 单声道
    raw = np.zeros(1600, dtype=np.int16)
    raw[::2] = 1000  # 左声道 1000、右声道 0 → 降混后每帧 500
    mono = _resample_input(raw.tobytes(), channels=2, source_rate=16000, target_rate=8000)
    samples = np.frombuffer(mono, dtype=np.int16)
    assert len(samples) == 400  # 800 帧 × 0.5 采样率
    assert np.abs(samples.astype(int) - 500).max() <= 1  # 插值保持常量

    # 同速率不重采样
    same = _resample_input(
        raw[::2].tobytes(), channels=1, source_rate=16000, target_rate=16000
    )
    assert len(np.frombuffer(same, dtype=np.int16)) == 800

    # 空帧与不足一帧（1 个 int16 采样、立体声时降混后为空）
    assert _resample_input(b"", channels=1, source_rate=16000, target_rate=8000) == b""
    assert _resample_input(b"\x01\x00", channels=2, source_rate=16000, target_rate=8000) == b""
