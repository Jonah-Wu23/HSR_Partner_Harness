from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import numpy as np
import sounddevice as sd


def list_devices() -> tuple[str, ...]:
    """列出可用音频设备，供界面选择。"""
    return tuple(f"{index}: {device['name']}" for index, device in enumerate(sd.query_devices()))


class MicrophoneCapture:
    """采集 16 kHz 单声道 int16 PCM 的麦克风流。"""

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
        self._stream: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self) -> "MicrophoneCapture":
        self._queue = asyncio.Queue()
        self._loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status) -> None:
            if self._queue is not None and self._loop is not None:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, indata.tobytes())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.block_size,
            callback=callback,
        )
        self._stream.start()
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
