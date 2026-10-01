"""Qwen 流式语音识别适配器。

用 ``dashscope.audio.asr.Recognition`` 的 duplex WebSocket 把 16 kHz
int16 PCM 流实时转写。SDK 回调运行在 SDK 自有线程，回调内只做一件事——
``loop.call_soon_threadsafe(queue.put_nowait, ...)`` 把原始事件塞进
asyncio 队列；适配器的异步迭代器从队列取出并映射为 :class:`AsrEvent`。

句子合并：每个结果事件携带一个 sentence，按 ``begin_time`` 归并，见
:func:`merge_asr_sentences`。

生命周期：一次 ``stream_transcribe`` 对应一次 ``Recognition.start()`` /
``stop()``。送音频与读识别结果并发进行，partial 随识别实时产出；音频流
结束后 ``stop()`` 在线程池中等待 SDK 收尾，随后产出 final 或 error。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pair_harness.core.audio import DASHSCOPE_CONFIG_LOCK
from pair_harness.core.contracts import AsrEvent
from pair_harness.core.ports import SpeechRecognizer
from pair_harness.voice_models import VOICE_ASR_MODEL

# 送帧结束后等待 SDK 收尾事件的超时（秒）
_TAIL_TIMEOUT_S = 5.0


class QwenAsrError(RuntimeError):
    """Qwen 流式 ASR 服务错误。"""


@dataclass
class _BridgeEvent:
    kind: str  # result | complete | error | sent（送帧任务结束）
    sentence: Mapping[str, Any] | None = None
    message: str = ""


def merge_asr_sentences(sentences: Iterable[Mapping[str, Any]]) -> str:
    """把 SDK 结果事件里的 sentence 按 ``begin_time`` 归并为当前转写。

    同一 ``begin_time`` 是同一句的逐次结果，后到的覆盖先到的；不同
    ``begin_time`` 是不同的句子，按 ``begin_time`` 先后拼接。文本相同的
    两句只要起始时刻不同就各自保留。
    """
    latest: dict[int, str] = {}
    for sentence in sentences:
        latest[sentence["begin_time"]] = sentence["text"]
    return "".join(latest[begin] for begin in sorted(latest)).strip()


async def _send_audio(recognition: Any, audio_stream: AsyncIterable[bytes]) -> None:
    """逐帧送入 SDK；音频流结束或送帧中断后调用 ``stop()`` 等 SDK 收尾。"""
    try:
        async for chunk in audio_stream:
            if chunk:
                recognition.send_audio_frame(chunk)
    finally:
        # stop() 会 join SDK 工作线程，放进线程池执行，不卡事件循环
        await asyncio.to_thread(recognition.stop)


# ---------------------------------------------------------------------------
# 适配器
# ---------------------------------------------------------------------------


class QwenStreamingRecognizer(SpeechRecognizer):
    """qwen-audio-3.0-asr-flash-streaming 流式识别。

    ``api_key`` / ``ws_url`` 可在构造时显式传入；缺省时按
    ``DASHSCOPE_API_KEY`` 环境变量与官方北京端点推导。SDK 的回调
    事件经 ``call_soon_threadsafe`` 入 asyncio 队列。
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        ws_url: str | None = None,
        model: str | None = None,
        sample_rate: int = 16_000,
    ) -> None:
        # ``model`` remains accepted for source compatibility with the old
        # live-test helper, but it is intentionally ignored.  M6 has one ASR
        # model and no caller may redirect this adapter to another model.
        del model
        self.api_key = api_key
        self.ws_url = ws_url
        self.model = VOICE_ASR_MODEL
        self.sample_rate = sample_rate

    def _make_sdk(self, bridge_queue: asyncio.Queue[_BridgeEvent], loop: asyncio.AbstractEventLoop):
        try:
            import dashscope  # type: ignore
            from dashscope.audio.asr import Recognition, RecognitionCallback  # type: ignore
        except ImportError as exc:
            raise QwenAsrError("未安装 dashscope SDK（pip install -e \".[voice]\"）") from exc

        with DASHSCOPE_CONFIG_LOCK:
            if self.ws_url:
                dashscope.base_websocket_api_url = self.ws_url
            if self.api_key:
                dashscope.api_key = self.api_key

        class _Callback(RecognitionCallback):
            def on_event(self, result) -> None:
                # 不含 sentence 的事件没有转写内容。字段在事件循环一侧解析，
                # 结构不符时异常沿 stream_transcribe 上抛
                sentence = result.get_sentence()
                if sentence is None:
                    return
                loop.call_soon_threadsafe(
                    bridge_queue.put_nowait,
                    _BridgeEvent(kind="result", sentence=sentence),
                )

            def on_complete(self) -> None:
                loop.call_soon_threadsafe(
                    bridge_queue.put_nowait, _BridgeEvent(kind="complete")
                )

            def on_error(self, result) -> None:
                message = getattr(result, "message", None)
                if message is None:
                    message = str(result)
                loop.call_soon_threadsafe(
                    bridge_queue.put_nowait,
                    _BridgeEvent(kind="error", message=str(message)),
                )

        recognition = Recognition(
            model=self.model,
            format="pcm",
            sample_rate=self.sample_rate,
            callback=_Callback(),
        )
        return recognition

    async def stream_transcribe(self, audio_stream: AsyncIterable[bytes]) -> AsyncIterator[AsrEvent]:
        bridge: asyncio.Queue[_BridgeEvent] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        recognition = self._make_sdk(bridge, loop)

        recognition.start()
        sender = asyncio.create_task(_send_audio(recognition, audio_stream))
        sender.add_done_callback(
            lambda _task: bridge.put_nowait(_BridgeEvent(kind="sent"))
        )

        sentences: list[Mapping[str, Any]] = []
        shown = ""
        completed = sent = False
        try:
            # 正常收尾时 stop() 已 join SDK 工作线程，回调事件都排在 sent 之前；
            # 送帧被 SDK 拒绝时 on_error 可能晚于 sent 到达，因此 sent 之后仍限时
            # 等待收尾事件。
            while not (completed and sent):
                try:
                    event = await asyncio.wait_for(
                        bridge.get(), timeout=_TAIL_TIMEOUT_S if sent else None
                    )
                except asyncio.TimeoutError:
                    break
                if event.kind == "error":
                    # SDK 出错后送帧和 stop() 都会报 has stopped，以 SDK 回调
                    # 报的原始错误为准
                    yield AsrEvent(type="error", error=event.message)
                    return
                if event.kind == "complete":
                    completed = True
                elif event.kind == "sent":
                    sent = True
                else:
                    sentences.append(event.sentence)
                    text = merge_asr_sentences(sentences)
                    if text and text != shown:
                        shown = text
                        yield AsrEvent(type="partial", text=text)
            send_error = sender.exception()
            if send_error is not None:
                raise send_error
            if not completed:
                yield AsrEvent(type="error", error="识别收尾超时")
                return
        finally:
            if not sender.done():
                sender.cancel()
            await asyncio.wait({sender})
            if not sender.cancelled():
                # 已产出 SDK 原始错误时，送帧任务的 has stopped 是它的后果
                sender.exception()
        final_text = merge_asr_sentences(sentences)
        if final_text:
            yield AsrEvent(type="final", text=final_text)
