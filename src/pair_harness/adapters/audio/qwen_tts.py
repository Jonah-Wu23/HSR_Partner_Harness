"""Qwen TTS 流式合成适配器（B2.4）。

用 ``dashscope.audio.tts_v2.SpeechSynthesizer`` 的 streaming_call 模式：
SDK 回调线程把 ``on_data``（PCM 帧）/ ``on_complete`` / ``on_error``
桥接进 asyncio 队列，合成流程在 executor 线程执行，迭代器从队列
逐块产出 :class:`AudioChunk`（24 kHz 单声道 int16，与
``AudioFormat.PCM_24000HZ_MONO_16BIT`` 一致），末尾以 ``final=True``
空块标记流结束。

中断语义：迭代器 ``aclose()`` 或提前返回时置 closed 标志，底层线程
改走 ``streaming_cancel()``，让 SDK 尽快断开连接而不等完整合成。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass

from pair_harness.core.contracts import AudioChunk, SpeechRequest
from pair_harness.core.ports import SpeechSynthesizer

TTS_SAMPLE_RATE = 24_000
# 等待 complete 哨兵的超时（秒）；超过视为异常收尾
_TAIL_TIMEOUT_S = 15.0


class QwenTtsError(RuntimeError):
    """Qwen TTS 服务错误。"""


@dataclass
class _TtsBridgeEvent:
    kind: str  # data | complete | error
    pcm: bytes = b""
    message: str = ""


class QwenSpeechSynthesizer(SpeechSynthesizer):
    """qwen-audio-3.0-tts-flash 流式合成。

    ``api_key`` / ``ws_url`` 可显式传入；缺省按 ``DASHSCOPE_API_KEY``
    环境变量与官方端点推导。构造不联网，SDK 连接在底层线程建立。
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        ws_url: str | None = None,
        model: str = "qwen-audio-3.0-tts-flash",
    ) -> None:
        self.api_key = api_key
        self.ws_url = ws_url
        self.model = model

    def _make_synthesizer(self, voice_id: str, callback):
        try:
            import dashscope  # type: ignore
            from dashscope.audio.tts_v2 import (  # type: ignore
                AudioFormat,
                ResultCallback,
                SpeechSynthesizer as SynthCls,
            )
        except ImportError as exc:
            raise QwenTtsError('未安装 dashscope SDK（pip install -e ".[voice]"）') from exc

        if self.ws_url:
            dashscope.base_websocket_api_url = self.ws_url
        if self.api_key:
            dashscope.api_key = self.api_key
        return SynthCls(
            model=self.model,
            voice=voice_id,
            format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            callback=callback,
        )

    def _run_synthesis(
        self,
        voice_id: str,
        text: str,
        bridge: asyncio.Queue[_TtsBridgeEvent],
        loop: asyncio.AbstractEventLoop,
        closed: threading.Event,
    ) -> None:
        """executor 线程：提交文本 → 等 FINISHED → 收尾（或取消）。"""
        try:
            from dashscope.audio.tts_v2 import ResultCallback  # type: ignore
        except ImportError as exc:  # pragma: no cover - 由 _make_synthesizer 兜底
            raise QwenTtsError('未安装 dashscope SDK（pip install -e ".[voice]"）') from exc

        done = threading.Event()

        def _put(event: _TtsBridgeEvent) -> None:
            loop.call_soon_threadsafe(bridge.put_nowait, event)

        class _Callback(ResultCallback):
            def on_data(self, data) -> None:
                _put(_TtsBridgeEvent(kind="data", pcm=bytes(data)))

            def on_complete(self) -> None:
                done.set()
                _put(_TtsBridgeEvent(kind="complete"))

            def on_error(self, result) -> None:
                done.set()
                message = getattr(result, "message", None)
                if message is None:
                    message = str(result)
                _put(_TtsBridgeEvent(kind="error", message=str(message)))

        try:
            synthesizer = self._make_synthesizer(voice_id, _Callback())
            synthesizer.streaming_call(text)
            while not done.is_set() and not closed.is_set():
                done.wait(0.1)
            if closed.is_set():
                synthesizer.streaming_cancel()
            else:
                synthesizer.streaming_complete()
        except Exception as exc:  # noqa: BLE001 - 第三方 SDK 异常类型不稳定
            if not closed.is_set():
                _put(_TtsBridgeEvent(kind="error", message=f"TTS 合成失败: {exc}"))

    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        if not request.text.strip():
            raise QwenTtsError("TTS 文本为空")

        bridge: asyncio.Queue[_TtsBridgeEvent] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        closed = threading.Event()
        task = asyncio.create_task(
            asyncio.to_thread(
                self._run_synthesis,
                request.voice_id,
                request.text,
                bridge,
                loop,
                closed,
            )
        )
        try:
            while True:
                try:
                    event = await asyncio.wait_for(bridge.get(), timeout=_TAIL_TIMEOUT_S)
                except asyncio.TimeoutError:
                    raise QwenTtsError("TTS 合成收尾超时") from None
                if event.kind == "error":
                    raise QwenTtsError(event.message)
                if event.kind == "complete":
                    yield AudioChunk(
                        pcm=b"", sample_rate=TTS_SAMPLE_RATE, channels=1, final=True
                    )
                    return
                yield AudioChunk(pcm=event.pcm, sample_rate=TTS_SAMPLE_RATE, channels=1)
        finally:
            # 中断或异常：通知底层线程尽快 cancel；正常收尾时仅等待线程退出
            closed.set()
            if task is not None:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
