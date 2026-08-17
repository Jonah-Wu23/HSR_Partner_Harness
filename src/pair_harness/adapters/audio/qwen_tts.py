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
import logging
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from pair_harness.core.audio import DASHSCOPE_CONFIG_LOCK
from pair_harness.core.contracts import AudioChunk, SpeechRequest
from pair_harness.core.ports import SpeechSynthesizer
from pair_harness.voice_models import VOICE_TTS_MODEL

logger = logging.getLogger(__name__)

TTS_SAMPLE_RATE = 24_000
# V0.2 问题 2：合成前兜底过滤的“不可读”字符（空白与标点）。
# 文本中若存在一个不在该集合内的字符，则视为包含可朗读内容。
_TTS_SKIP_CHAR = re.compile(
    r"[\s，。！？；：、,.!?;:'\"“”‘’…—–~··`~@#$%^&*()\[\]{}<>《》【】（）—\-_|/\\+=]"
)
# 等待 complete 哨兵的超时（秒）；超过视为异常收尾
_TAIL_TIMEOUT_S = 15.0
# streaming_call 提交文本后的“取消窗口”（秒）：窗口内 aclose 置 closed
# 可走 streaming_cancel；窗口过后立即发 finish request 等服务端 FINISHED
_CANCEL_WINDOW_S = 0.1
# streaming_complete 内部的等待上限（毫秒）：避免服务端异常时不回 FINISHED
# 导致底层线程无限阻塞（asyncio 侧 _TAIL_TIMEOUT_S 会先超时）
_COMPLETE_TIMEOUT_MS = 20_000
# aclose 不应把 VoiceRuntime 播放循环拖进 SDK 的完整收尾等待；超时后
# 保留 executor 线程自行结束，播放状态先回到可继续处理的路径。
_CLOSE_WAIT_S = 0.5


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
        model: str | None = None,
    ) -> None:
        # ``model`` remains accepted for old callers, but the production
        # adapter always uses the V0.3.2 product model.
        del model
        self.api_key = api_key
        self.ws_url = ws_url
        self.model = VOICE_TTS_MODEL

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

        with DASHSCOPE_CONFIG_LOCK:
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
        """executor 线程：提交文本 → 发 finish request → 等 FINISHED → 收尾。

        真实服务在收到 finish request（``streaming_complete``）前不会发
        FINISHED 消息，因此不能在 ``streaming_call`` 后死等 on_complete
        （会与服务端互相等待直到超时）。音频帧在合成过程中已随流式到达，
        先留一个短的取消窗口让 aclose 有机会走 ``streaming_cancel``，
        窗口过后立即 ``streaming_complete`` 等待服务端收尾。
        """
        try:
            from dashscope.audio.tts_v2 import ResultCallback  # type: ignore
        except ImportError as exc:  # pragma: no cover - 由 _make_synthesizer 兜底
            raise QwenTtsError('未安装 dashscope SDK（pip install -e ".[voice]"）') from exc

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

            def on_error(self, result) -> None:
                done.set()
                message = getattr(result, "message", None)
                if message is None:
                    message = str(result)
                _put(_TtsBridgeEvent(kind="error", message=str(message)))

        try:
            synthesizer = self._make_synthesizer(voice_id, _Callback())
            synthesizer.streaming_call(text)
            # 取消窗口：提交后短暂等待，若 aclose 已置 closed 则走 cancel
            deadline = time.monotonic() + _CANCEL_WINDOW_S
            while (
                not done.is_set()
                and not closed.is_set()
                and time.monotonic() < deadline
            ):
                done.wait(0.01)
            if closed.is_set() and not done.is_set():
                synthesizer.streaming_cancel()
                return
            # 发 finish request 并等待服务端 FINISHED；正常时音频帧已全部到达
            synthesizer.streaming_complete(complete_timeout_millis=_COMPLETE_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - 第三方 SDK 异常类型不稳定
            if not closed.is_set():
                _put(_TtsBridgeEvent(kind="error", message=f"TTS 合成失败: {exc}"))

    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        # V0.2 问题 2：空/纯标点文本一律不合成（DashScope 报 input text is
        # invalid）。voice_runtime 入队前已过滤，这里作为适配器层兜底。
        if not request.text.strip() or not any(
            not _TTS_SKIP_CHAR.match(ch) for ch in request.text
        ):
            raise QwenTtsError("TTS 文本为空或只有标点")

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
            # 中断或异常：通知底层线程尽快 cancel；正常收尾也只等待有限时间。
            # streaming_complete 可能卡在 SDK 的 websocket 收尾，不能让
            # VoiceRuntime 的播放循环跟着无限等待。
            closed.set()
            if task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=_CLOSE_WAIT_S)
                except asyncio.TimeoutError:
                    logger.warning("TTS synthesis thread did not stop within %.1fs", _CLOSE_WAIT_S)
                except asyncio.CancelledError:
                    # 保留上层取消语义；线程任务由 shield 保留，随后自行结束。
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(task), timeout=_CLOSE_WAIT_S
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "TTS synthesis thread did not stop within %.1fs after cancel",
                            _CLOSE_WAIT_S,
                        )
                    except BaseException:  # noqa: BLE001 - 取消收尾不覆盖原始取消
                        pass
                    raise
                except Exception:  # noqa: BLE001 - 底层错误已由事件回传
                    pass
