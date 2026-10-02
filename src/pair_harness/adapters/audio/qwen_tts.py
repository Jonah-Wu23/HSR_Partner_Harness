# Qwen TTS 流式合成：dashscope tts_v2 的 streaming_call 在 executor 线程运行，SDK 回调经 asyncio 队列
# 桥接为 24 kHz 单声道 int16 的 AudioChunk，末尾以 final=True 空块结束。迭代器关闭或调用 aclose()
# 时置 closed 标志，底层线程改走 streaming_cancel()。上游错误（含限流）原样作为 QwenTtsError 抛出。

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass

import dashscope
from dashscope.audio.tts_v2 import AudioFormat, ResultCallback
from dashscope.audio.tts_v2 import SpeechSynthesizer as DashScopeSynthesizer

from pair_harness.core.audio import DASHSCOPE_CONFIG_LOCK
from pair_harness.core.contracts import AudioChunk, SpeechRequest
from pair_harness.core.ports import SpeechSynthesizer
from pair_harness.core.voice_policy import is_readable_text
from pair_harness.voice_models import VOICE_TTS_MODEL

logger = logging.getLogger(__name__)

TTS_SAMPLE_RATE = 24_000
# 等待 complete 哨兵的超时（秒）；超过视为异常收尾
_TAIL_TIMEOUT_S = 15.0
# 合成线程检查取消标志的间隔（秒）：发出 finish request 后到服务端 FINISHED
# 之前，aclose 置 closed 都会改走 streaming_cancel
_CANCEL_POLL_S = 0.02
# SDK 后台等待服务端 FINISHED 的上限（毫秒）；asyncio 侧 _TAIL_TIMEOUT_S 会先超时
_COMPLETE_TIMEOUT_MS = 20_000
# aclose 不应把 VoiceRuntime 播放循环拖进 SDK 的完整收尾等待；超时后
# 保留 executor 线程自行结束，播放状态先回到可继续处理的路径。
_CLOSE_WAIT_S = 0.5
# 被放弃等待的合成线程超过该时间仍未结束才记 WARNING（建连或取消收尾
# 可能超过 _CLOSE_WAIT_S，只有长时间未结束才算泄漏）。
_TTS_THREAD_REAP_WARN_S = 30.0


class QwenTtsError(RuntimeError):
    """Qwen TTS 服务错误。"""


@dataclass
class _TtsBridgeEvent:
    kind: str  # data | complete | error
    pcm: bytes = b""
    message: str = ""


@dataclass(eq=False)
class _ActiveSynthesis:
    """一次在途合成：中断标志与底层线程任务（按身份比较）。"""

    closed: threading.Event
    task: asyncio.Task[None] | None = None


_reaper_tasks: set[asyncio.Task[None]] = set()


def _reap_synthesis_thread(task: asyncio.Task[None]) -> None:
    """后台等待一个被放弃等待的合成线程任务；确实卡死才告警。"""

    async def _wait() -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), _TTS_THREAD_REAP_WARN_S)
        except asyncio.TimeoutError:
            logger.warning(
                "TTS 合成线程 %.0fs 未结束，已放弃等待（上游连接可能未释放）",
                _TTS_THREAD_REAP_WARN_S,
            )

    reaper = asyncio.create_task(_wait(), name="tts:reap")
    _reaper_tasks.add(reaper)
    reaper.add_done_callback(_reaper_tasks.discard)


class QwenSpeechSynthesizer(SpeechSynthesizer):
    """qwen-audio-3.0-tts-flash 流式合成。

    ``api_key`` / ``ws_url`` 缺省时沿用 dashscope SDK 的环境变量与官方端点。
    构造不联网，SDK 连接在底层线程建立。
    """

    def __init__(self, *, api_key: str | None = None, ws_url: str | None = None) -> None:
        self.api_key = api_key
        self.ws_url = ws_url
        # 在途合成记录：aclose() 据此中止尚未收尾的合成。
        self._active: set[_ActiveSynthesis] = set()

    def _make_synthesizer(self, voice_id: str, callback: ResultCallback) -> DashScopeSynthesizer:
        with DASHSCOPE_CONFIG_LOCK:
            if self.ws_url:
                dashscope.base_websocket_api_url = self.ws_url
            if self.api_key:
                dashscope.api_key = self.api_key
        return DashScopeSynthesizer(
            model=VOICE_TTS_MODEL,
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
        """executor 线程：提交文本 → 发 finish request → 等 FINISHED 或取消。

        服务端收到 finish request 后才会发 FINISHED，因此提交文本后立即用
        ``async_streaming_complete`` 发出 finish request，由 SDK 后台线程等待
        服务端收尾。本线程在拿到 complete/error 之前持续检查 ``closed``，
        整个合成期间置 closed 都会调用 ``streaming_cancel`` 中止上游合成。
        """
        done = threading.Event()

        def _put(event: _TtsBridgeEvent) -> None:
            if closed.is_set():
                return
            try:
                loop.call_soon_threadsafe(bridge.put_nowait, event)
            except RuntimeError:
                # 事件循环已经关闭时，SDK 回调线程只能结束自己的清理。
                logger.debug("TTS callback arrived after event loop shutdown")

        class _Callback(ResultCallback):
            def on_data(self, data) -> None:
                _put(_TtsBridgeEvent(kind="data", pcm=bytes(data)))

            def on_complete(self) -> None:
                done.set()
                _put(_TtsBridgeEvent(kind="complete"))

            def on_error(self, message: str) -> None:
                # SDK 传入服务端 task-failed 原始消息文本。
                done.set()
                _put(_TtsBridgeEvent(kind="error", message=message))

        try:
            synthesizer = self._make_synthesizer(voice_id, _Callback())
            synthesizer.streaming_call(text)
            if not done.is_set() and not closed.is_set():
                synthesizer.async_streaming_complete(
                    complete_timeout_millis=_COMPLETE_TIMEOUT_MS
                )
            while not done.wait(_CANCEL_POLL_S):
                if closed.is_set():
                    synthesizer.streaming_cancel()
                    return
        except Exception as exc:  # noqa: BLE001 - SDK 异常经桥接队列交给 synthesize 抛出
            if not closed.is_set():
                _put(_TtsBridgeEvent(kind="error", message=f"TTS 合成失败: {exc}"))

    async def _settle_thread_task(self, task: asyncio.Task[None]) -> None:
        """有限等待合成线程收尾；超出等待或上层取消时交给后台收尾。"""
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_CLOSE_WAIT_S)
        except asyncio.TimeoutError:
            _reap_synthesis_thread(task)
        except asyncio.CancelledError:
            # 保留上层取消语义；线程任务由 shield 保留，后台收尾。
            _reap_synthesis_thread(task)
            raise

    async def aclose(self) -> None:
        """中止本实例上所有在途合成（停止或抢占时调用）。

        置 ``closed`` 后底层线程改走 ``streaming_cancel()``，其后到达的音频帧
        不再入队；随后有限等待线程结束，超出等待的交给后台收尾。没有在途
        合成时直接返回。
        """
        records = tuple(self._active)
        if not records:
            return
        for record in records:
            record.closed.set()
        for record in records:
            task = record.task
            if task is not None and not task.done():
                await self._settle_thread_task(task)

    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        # DashScope 对空文本或纯标点文本返回 input text is invalid，提交前拒绝。
        if not is_readable_text(request.text):
            raise QwenTtsError("TTS 文本为空或只有标点")

        bridge: asyncio.Queue[_TtsBridgeEvent] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        closed = threading.Event()
        record = _ActiveSynthesis(closed=closed)
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
        record.task = task
        self._active.add(record)
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
            self._active.discard(record)
            # 中断或异常：通知底层线程尽快 cancel；正常收尾也只等待有限时间。
            # 建连和 streaming_cancel 都可能卡在 SDK 的 websocket 收尾，不能让
            # VoiceRuntime 的播放循环跟着无限等待。超过等待的线程交给后台
            # 收尾：只在真正卡死时才告警。
            closed.set()
            await self._settle_thread_task(task)
