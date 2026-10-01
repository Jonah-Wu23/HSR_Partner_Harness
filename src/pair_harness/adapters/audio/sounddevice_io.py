from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncIterator

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

# PortAudio 维护的是进程级设备/流状态。输入流由事件循环线程管理，输出流
# 由播放器线程管理，所有原生 stream 调用共用这把锁，避免开关两个设备时
# 同时进入 PortAudio。
_PORTAUDIO_LOCK = threading.RLock()


def list_devices() -> tuple[str, ...]:
    """列出可用音频设备，供界面选择。"""
    with _PORTAUDIO_LOCK:
        devices = sd.query_devices()
    return tuple(f"{index}: {device['name']}" for index, device in enumerate(devices))


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
        # 队列里是 PCM 块；回调出错时放入异常，由 chunks() 上抛
        self._queue: asyncio.Queue[bytes | Exception] | None = None
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
                try:
                    pcm = _resample_input(
                        bytes(indata),
                        source_channels,
                        source_rate,
                        self.sample_rate,
                    )
                    if pcm:
                        self._loop.call_soon_threadsafe(self._queue.put_nowait, pcm)
                except Exception as exc:
                    # 回调异常会让 PortAudio 中止输入流；把异常交给 chunks()
                    # 的消费者，再显式中止流
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, exc)
                    raise sd.CallbackAbort from exc

        candidates = _input_device_candidates()
        last_error: Exception | None = None
        for device in candidates:
            with _PORTAUDIO_LOCK:
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
            stream = None
            try:
                with _PORTAUDIO_LOCK:
                    stream = sd.RawInputStream(
                        device=device,
                        samplerate=source_rate,
                        channels=source_channels,
                        dtype="int16",
                        blocksize=source_block_size,
                        callback=callback,
                    )
                    stream.start()
                self._stream = stream
                break
            except Exception as exc:  # noqa: BLE001 - PortAudio errors vary by host API
                last_error = exc
                if stream is not None:
                    with _PORTAUDIO_LOCK:
                        try:
                            stream.close()
                        except Exception:  # noqa: BLE001 - 清理失败不掩盖原始建流错误
                            logger.debug("failed to close input stream after startup error", exc_info=True)
                self._stream = None
        else:
            raise RuntimeError(f"无法打开麦克风输入设备：{last_error}") from last_error
        return self

    async def chunks(self) -> AsyncIterator[bytes]:
        if self._queue is None:
            raise RuntimeError("capture not started")
        queue = self._queue
        while True:
            item = await queue.get()
            if isinstance(item, Exception):
                raise item
            yield item

    async def __aexit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            with _PORTAUDIO_LOCK:
                try:
                    stream.stop()
                except Exception:  # noqa: BLE001 - 关闭阶段保留真实错误到日志
                    logger.debug("failed to stop input stream", exc_info=True)
                try:
                    stream.close()
                except Exception:  # noqa: BLE001 - 关闭阶段保留真实错误到日志
                    logger.debug("failed to close input stream", exc_info=True)
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
    with _PORTAUDIO_LOCK:
        devices = tuple(sd.query_devices())
    for index, info in enumerate(devices):
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
    """长生命周期输出流播放器。

    持有单一 sounddevice.OutputStream，惰性创建，被 stop 或输出失败后关闭，
    下次播放时重建；PCM 块写入有界缓冲（``buffer_chunks``，防止 TTS 超速），
    后台播放线程从缓冲取块连续写流，并以块时长近似节奏播放（写流后 sleep
    剩余时间）。缓冲无数据时短暂等待而非退出，块间间隙、句与句之间都不关闭流。

    ``play_blocking`` 保留原名：缓冲满时阻塞等待播放线程消费（即生产节奏
    被消费节奏钳制），调用方经 ``asyncio.to_thread`` 调用，不占用事件循环。
    建流或写流失败时清空缓冲，下一次 ``play_blocking`` 或 ``wait_until_idle``
    抛出该错误。``stop()`` 立即清空缓冲并关闭流（丢弃设备端积压和未上报的
    输出错误），下次播放惰性重建。
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        channels: int = 1,
        buffer_chunks: int = 16,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer_chunks = buffer_chunks
        self._buffer: deque[bytes] = deque()
        self._cond = threading.Condition()
        self._stream_lock = threading.Lock()
        self._stream: sd.OutputStream | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._closed = False
        self._stopped = False
        self._active_playback = False
        self._generation = 0
        self._stop_event = threading.Event()
        # 播放线程建流或写流失败的错误，等生产者下一次调用时抛出
        self._error: Exception | None = None

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        """启动播放线程（幂等）；输出流仍惰性创建。"""
        with self._cond:
            if self._closed:
                return
            self._stopped = False
            self._stop_event.clear()
            if self._running and self._thread is not None and self._thread.is_alive():
                return
            self._running = True
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, name="audio-player", daemon=True
            )
            self._thread.start()

    def close(self) -> None:
        """停止播放线程并关闭输出流（shutdown 时调用）。"""
        with self._cond:
            self._running = False
            self._closed = True
            self._stopped = True
            self._generation += 1
            self._buffer.clear()
            self._error = None
            self._stop_event.set()
            self._cond.notify_all()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._close_stream()

    def stop(self) -> None:
        """立即停止播放：清空缓冲、丢弃在途块并关闭流（流下次重建）。"""
        with self._cond:
            self._buffer.clear()
            self._stopped = True
            self._generation += 1
            self._error = None
            self._stop_event.set()
            self._cond.notify_all()
        # _play 持有同一把 _stream_lock 覆盖 stream.write；这里最多等当前
        # 原生写入自然返回，再由本线程安全地 abort/close，不会跨线程关流。
        self._close_stream()

    def wait_until_idle(self) -> None:
        """等待输出缓冲与当前声块都排空；播放线程输出失败时抛出该错误。"""
        with self._cond:
            while (
                self._running
                and not self._stopped
                and not self._closed
                and self._error is None
                and (self._buffer or self._active_playback)
            ):
                self._cond.wait(timeout=0.05)
            self._raise_error_locked()

    # ------------------------------------------------------------ 生产者

    def play_blocking(self, pcm: bytes) -> None:
        """把一块 PCM 写入缓冲；缓冲满时阻塞等待（防止 TTS 超速）。

        播放线程此前建流或写流失败时抛出该错误，本块不入队。
        """
        if not pcm:
            return
        self.start()  # 幂等：未启动时惰性启动播放线程
        with self._cond:
            while (
                len(self._buffer) >= self.buffer_chunks
                and not self._closed
                and not self._stopped
                and self._error is None
            ):
                self._cond.wait(timeout=0.05)
            self._raise_error_locked()
            if self._closed or self._stopped:
                return  # stop/close 后到达的块：丢弃
            self._buffer.append(pcm)
            self._cond.notify_all()

    def _raise_error_locked(self) -> None:
        error, self._error = self._error, None
        if error is not None:
            raise RuntimeError(f"音频输出失败：{error}") from error

    # ------------------------------------------------------------ 播放线程

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._running and not self._buffer:
                    self._cond.wait(timeout=0.05)  # 无数据：短暂等待而非退出
                if not self._running:
                    return
                pcm = self._buffer.popleft()
                generation = self._generation
                self._active_playback = True
                # 腾出空间：唤醒等待入队的生产者（防止满缓冲死锁）
                self._cond.notify_all()
            try:
                self._play(pcm, generation)
            except Exception as exc:  # noqa: BLE001 - PortAudio 错误类型不稳定，交给生产者上抛
                logger.warning("音频输出失败：%s", exc, exc_info=True)
                with self._cond:
                    # stop 之后的失败属于已丢弃的播放，不转给下一次播放
                    if generation == self._generation:
                        self._buffer.clear()
                        self._error = exc
            finally:
                with self._cond:
                    self._active_playback = False
                    self._cond.notify_all()

    def _play(self, pcm: bytes, generation: int) -> None:
        """写流并按块时长近似节奏播放；建流或写流失败时关闭流并抛出。"""
        duration = len(pcm) / (self.sample_rate * self.channels * 2)
        start = time.monotonic()
        # 同一把锁覆盖取流、Pa_WriteStream 和 Pa_CloseStream。停止请求若
        # 正好落在 write 中，会等待该次写入返回，再安全地关闭流。
        with self._stream_lock:
            if self._closed or self._stopped or generation != self._generation:
                return
            stream = self._ensure_stream_locked()
            with _PORTAUDIO_LOCK:
                try:
                    stream.write(np.frombuffer(pcm, dtype=np.int16))
                except Exception:
                    # 设备被拔出等写流失败：关闭流，下次播放重建
                    self._close_stream_locked()
                    raise
        if self._closed or self._stopped or generation != self._generation:
            return
        elapsed = time.monotonic() - start
        remain = duration - elapsed
        if remain > 0:
            self._stop_event.wait(remain)

    def _ensure_stream_locked(self) -> sd.OutputStream:
        """惰性创建输出流；创建失败时关闭半开的流并抛出建流错误。"""
        if self._stream is None:
            stream = None
            try:
                with _PORTAUDIO_LOCK:
                    stream = sd.OutputStream(
                        samplerate=self.sample_rate,
                        channels=self.channels,
                        dtype="int16",
                    )
                    stream.start()
            except Exception:
                if stream is not None:
                    with _PORTAUDIO_LOCK:
                        try:
                            stream.close()
                        except Exception:  # noqa: BLE001 - 保留建流错误
                            logger.debug("failed to close output stream after startup error", exc_info=True)
                raise
            self._stream = stream
        return self._stream

    def _close_stream(self) -> None:
        with self._stream_lock:
            self._close_stream_locked()

    def _close_stream_locked(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        with _PORTAUDIO_LOCK:
            abort = getattr(stream, "abort", None)
            if abort is not None:
                try:
                    abort()
                except Exception:  # noqa: BLE001 - 关闭阶段保留真实错误到日志
                    logger.debug("failed to abort output stream", exc_info=True)
            try:
                stream.close()
            except Exception:  # noqa: BLE001 - 关闭阶段保留真实错误到日志
                logger.debug("failed to close output stream", exc_info=True)
