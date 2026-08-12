from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np
import sounddevice as sd


def list_devices() -> tuple[str, ...]:
    """列出可用音频设备，供界面选择。"""
    return tuple(f"{index}: {device['name']}" for index, device in enumerate(sd.query_devices()))


class MicrophoneCapture:
    """采集 16 kHz 单声道 int16 PCM 的麦克风流。

    Windows 的 MME 默认输入设备经常拒绝 16 kHz 或阻塞式输入；这里优先
    尝试默认设备，失败后改用可用的 WDM-KS 麦克风，并在回调内重采样到
    VAD/ASR 需要的 16 kHz。
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        channels: int = 1,
        block_size: int = 320,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size
        self._queue: asyncio.Queue[bytes] | None = None
        self._stream: sd.RawInputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self) -> "MicrophoneCapture":
        self._queue = asyncio.Queue()
        self._loop = asyncio.get_running_loop()

        source_rate = self.sample_rate
        source_channels = self.channels

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            if self._queue is not None and self._loop is not None:
                pcm = _resample_input(
                    bytes(indata),
                    source_channels,
                    source_rate,
                    self.sample_rate,
                )
                if pcm:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, pcm)

        candidates = _input_device_candidates()
        last_error: Exception | None = None
        for device in candidates:
            info = sd.query_devices(device)
            max_channels = int(info["max_input_channels"])
            if max_channels <= 0:
                continue
            source_rate = int(round(float(info["default_samplerate"]))) or self.sample_rate
            source_channels = min(self.channels, max_channels)
            source_block_size = (
                max(1, round(self.block_size * source_rate / self.sample_rate))
                if self.block_size
                else 0
            )
            try:
                self._stream = sd.RawInputStream(
                    device=device,
                    samplerate=source_rate,
                    channels=source_channels,
                    dtype="int16",
                    blocksize=source_block_size,
                    callback=callback,
                )
                self._stream.start()
                break
            except Exception as exc:  # noqa: BLE001 - PortAudio errors vary by host API
                last_error = exc
                self._stream = None
        else:
            raise RuntimeError(f"无法打开麦克风输入设备：{last_error}") from last_error
        return self

    async def chunks(self) -> AsyncIterator[bytes]:
        if self._queue is None:
            raise RuntimeError("capture not started")
        while True:
            yield await self._queue.get()

    async def __aexit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue = None


def _input_device_candidates() -> tuple[int | None, ...]:
    """返回默认输入及可尝试的真实麦克风设备，优先 Windows WDM-KS。"""
    try:
        default_input = sd.default.device[0]
        default_value = int(default_input) if default_input is not None else -1
        default = default_value if default_value >= 0 else None
    except (AttributeError, TypeError, ValueError):
        default = None

    preferred: list[int] = []
    remaining: list[int] = []
    for index, info in enumerate(sd.query_devices()):
        if int(info["max_input_channels"]) <= 0 or index == default:
            continue
        name = str(info["name"]).lower()
        is_microphone = any(token in name for token in ("麦克风", "microphone", "mic", "阵列"))
        if int(info["hostapi"]) == 3 and is_microphone:
            preferred.append(index)
        else:
            remaining.append(index)
    return tuple(([default] if default is not None else []) + preferred + remaining)


def _resample_input(raw: bytes, channels: int, source_rate: int, target_rate: int) -> bytes:
    """把 RawInputStream 的 int16 帧降为目标采样率的单声道 PCM。"""
    if not raw:
        return b""
    samples = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        samples = samples[: len(samples) - len(samples) % channels]
        if not len(samples):
            return b""
        samples = samples.reshape(-1, channels).mean(axis=1)
    if source_rate != target_rate and len(samples) > 1:
        target_size = max(1, round(len(samples) * target_rate / source_rate))
        samples = np.interp(
            np.linspace(0.0, 1.0, target_size),
            np.linspace(0.0, 1.0, len(samples)),
            samples,
        )
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


class AudioPlayer:
    """把 PCM 播放到默认输出设备。"""

    def __init__(self, *, sample_rate: int = 16_000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels

    def play_blocking(self, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16)
        if samples.size == 0:
            return
        with sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
        ) as stream:
            stream.write(samples)
