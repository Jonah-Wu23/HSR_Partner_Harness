"""Qwen TTS 流式合成适配器（B2.4）。

用 ``dashscope.audio.tts_v2.SpeechSynthesizer`` 的 streaming_call 模式：
SDK 回调线程把 ``on_data``（PCM 帧）/ ``on_complete`` / ``on_error``
桥接进 asyncio 队列，合成流程在 executor 线程执行，迭代器从队列
逐块产出 :class:`AudioChunk`（24 kHz 单声道 int16，与
``AudioFormat.PCM_24000HZ_MONO_16BIT`` 一致），末尾以 ``final=True``
空块标记流结束。

中断语义：迭代器 ``aclose()`` 或提前返回时置 closed 标志，底层线程
改走 ``streaming_cancel()``，让 SDK 尽快断开连接而不等完整合成；适配器
自身也提供 :meth:`QwenSpeechSynthesizer.aclose`，供停止/抢占时中止在途
合成（V039-S4-018 的收尾路径）。

节流（V039-S4-012）：相邻两次上行合成的起始保持进程级最小间隔，失败后
按倍数退避、一次成功即复位，避免高频回合下稳定触发上游限流。
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
# 被放弃等待的合成线程：超过该时间仍未结束才记 WARNING。0.5s 的关闭等待
# 在正常收尾时几乎必然超时（SDK 在 streaming_complete 里还要走完 FINISHED
# 与关连接），逐次告警只会淹没真实泄漏。
_TTS_THREAD_REAP_WARN_S = 30.0
# V0.3.9（V039-S4-012）：上行合成的起始节流。中继路径每条角色消息都会新建
# 一个适配器实例，实例级节流对高频回合无效，因此节流状态按进程共享。
# 该下限是保守工程取值，不是实测到的供应商限额；真实额度仍需真机复验。
_TTS_MIN_START_INTERVAL_S = 1.0
# 一次合成失败后，下一次起始额外等待的基础退避（连续失败逐次翻倍，上限
# _TTS_MAX_START_INTERVAL_S，一次成功即复位）。用于避免限流期间逐条重试
# 稳定触发上游限流，同时不改变失败本身的上报。
_TTS_FAILURE_BACKOFF_BASE_S = 4.0
_TTS_MAX_START_INTERVAL_S = 30.0


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


class _SynthesisPacer:
    """相邻两次上行合成起始的最小间隔（进程共享、线程安全）。

    ``wait_s()`` 只读不占位，``mark_started()`` 在真正起始时占用时隙，
    因此在等待期间被取消不会白占一个时隙。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_start = 0.0
        self._failure_streak = 0
        # 尝试序号：只有“比最近一次失败更新”的成功才清退避，避免并发下
        # 旧尝试的迟到成功压掉较新失败的退避。
        self._attempts = 0
        self._last_failure_attempt = 0

    @property
    def failure_streak(self) -> int:
        with self._lock:
            return self._failure_streak

    def _interval_s(self) -> float:
        floor = max(0.0, _TTS_MIN_START_INTERVAL_S)
        if self._failure_streak <= 0:
            return floor
        backoff = _TTS_FAILURE_BACKOFF_BASE_S * (2 ** (self._failure_streak - 1))
        return min(max(backoff, floor), _TTS_MAX_START_INTERVAL_S)

    @property
    def interval_s(self) -> float:
        """当前生效的最小起始间隔（含失败退避）。"""
        with self._lock:
            return self._interval_s()

    def wait_s(self) -> float:
        """距离下一次可起始还需等待的秒数（<=0 表示现在即可起始）。"""
        with self._lock:
            return self._next_start - time.monotonic()

    def mark_started(self) -> int:
        """占用一个起始时隙，返回本次尝试的序号（用于成功/失败归账）。"""
        with self._lock:
            self._next_start = max(self._next_start, time.monotonic()) + self._interval_s()
            self._attempts += 1
            return self._attempts

    def note_failure(self, attempt: int) -> None:
        """记一次失败：下一次起始至少等一个（更长的）退避间隔。"""
        with self._lock:
            self._failure_streak += 1
            self._last_failure_attempt = max(self._last_failure_attempt, attempt)
            self._next_start = max(
                self._next_start, time.monotonic() + self._interval_s()
            )

    def note_success(self, attempt: int) -> None:
        """记一次完整成功（上游 complete 终态）并清除失败退避。

        只有比最近一次失败更新的尝试才算数：更早尝试的迟到成功不清除较新
        失败的退避。只出了部分 PCM 就失败或被取消的尝试不算成功，因此本方法
        只在终态成功时调用。
        """
        with self._lock:
            if attempt < self._last_failure_attempt:
                return
            self._failure_streak = 0
            self._next_start = min(
                self._next_start,
                time.monotonic() + max(0.0, _TTS_MIN_START_INTERVAL_S),
            )

    def reset(self) -> None:
        """清空节流状态（诊断与测试用）。"""
        with self._lock:
            self._next_start = 0.0
            self._failure_streak = 0
            self._attempts = 0
            self._last_failure_attempt = 0


_PACER = _SynthesisPacer()
_reaper_tasks: set[asyncio.Task[None]] = set()


def _reap_synthesis_thread(task: asyncio.Task[None]) -> None:
    """后台等待一个被放弃等待的合成线程任务；确实卡死才如实告警。"""

    async def _wait() -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), _TTS_THREAD_REAP_WARN_S)
        except asyncio.TimeoutError:
            logger.warning(
                "TTS 合成线程 %.0fs 未结束，已放弃等待（上游连接可能未释放）",
                _TTS_THREAD_REAP_WARN_S,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 线程错误已由桥接事件回传
            pass

    reaper = asyncio.create_task(_wait(), name="tts:reap")
    _reaper_tasks.add(reaper)
    reaper.add_done_callback(_reaper_tasks.discard)


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
        # 在途合成记录：aclose() 需要据此中止尚未收尾的合成（停止/抢占收尾）。
        self._active: set[_ActiveSynthesis] = set()

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

    async def _wait_for_start_slot(self) -> int:
        """向上游发起合成前遵守进程级起始节流（V039-S4-012）。

        等待期间被取消不占用时隙（``mark_started`` 只在真正起始时调用），
        因此抢占/停止不会白白推迟下一条真正要播的合成。返回本次尝试序号，
        供成功/失败按尝试时序归账。
        """
        wait_s = _PACER.wait_s()
        if wait_s > 0:
            logger.info(
                "TTS 合成起始节流：等待 %.2fs（连续失败 %d 次）",
                wait_s,
                _PACER.failure_streak,
            )
        while wait_s > 0:
            await asyncio.sleep(min(wait_s, 0.25))
            wait_s = _PACER.wait_s()
        return _PACER.mark_started()

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
        except Exception:  # noqa: BLE001 - 线程错误已由桥接事件回传
            pass

    async def aclose(self) -> None:
        """中止本实例上所有在途合成（停止/抢占收尾用）。

        置 ``closed`` 后底层线程改走 ``streaming_cancel()``，其后到达的音频帧
        不再入队；随后有限等待线程结束，超出等待的交给后台收尾。没有在途
        合成时是 no-op。应用层中继任务的收尾路径已经按此语义调用本方法——
        此前适配器没有该方法，调用处的 AttributeError 被吞掉，导致被抢占的
        合成既不中止也不停止入队。
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
        # V0.2 问题 2：空/纯标点文本一律不合成（DashScope 报 input text is
        # invalid）。voice_runtime 入队前已过滤，这里作为适配器层兜底。
        if not request.text.strip() or not any(
            not _TTS_SKIP_CHAR.match(ch) for ch in request.text
        ):
            raise QwenTtsError("TTS 文本为空或只有标点")

        attempt = await self._wait_for_start_slot()

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
                    # 只有收到上游 complete 终态才算成功；部分 PCM 不算
                    _PACER.note_success(attempt)
                    yield AudioChunk(
                        pcm=b"", sample_rate=TTS_SAMPLE_RATE, channels=1, final=True
                    )
                    return
                yield AudioChunk(pcm=event.pcm, sample_rate=TTS_SAMPLE_RATE, channels=1)
        except QwenTtsError:
            _PACER.note_failure(attempt)
            raise
        finally:
            self._active.discard(record)
            # 中断或异常：通知底层线程尽快 cancel；正常收尾也只等待有限时间。
            # streaming_complete 可能卡在 SDK 的 websocket 收尾，不能让
            # VoiceRuntime 的播放循环跟着无限等待。超过等待的线程交给后台
            # 收尾：正常完成只在真正卡死时才告警。
            closed.set()
            await self._settle_thread_task(task)
