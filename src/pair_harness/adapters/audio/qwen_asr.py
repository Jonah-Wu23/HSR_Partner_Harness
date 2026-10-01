# Qwen 流式语音识别：dashscope Recognition 的双工 WebSocket 实时转写 16 kHz int16 PCM。SDK 回调线程只把
# 原始事件经 call_soon_threadsafe 放进 asyncio 队列，异步迭代器取出后映射为 AsrEvent。一次
# stream_transcribe 对应一次 start()/stop()；送帧与读结果并发，音频流结束后 stop() 在线程池等待 SDK 收尾。

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from pair_harness.core.audio import DASHSCOPE_CONFIG_LOCK
from pair_harness.core.contracts import AsrEvent
from pair_harness.core.ports import SpeechRecognizer
from pair_harness.voice_models import VOICE_ASR_MODEL

ASR_SAMPLE_RATE = 16_000
# 送帧结束后等待 SDK 收尾事件的超时（秒）
_TAIL_TIMEOUT_S = 5.0


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


async def _send_audio(recognition: Recognition, audio_stream: AsyncIterable[bytes]) -> None:
    """逐帧送入 SDK；音频流结束或送帧中断后调用 ``stop()`` 等 SDK 收尾。"""
    try:
        async for chunk in audio_stream:
            if chunk:
                recognition.send_audio_frame(chunk)
    finally:
        # stop() 会 join SDK 工作线程，放进线程池执行，不卡事件循环
        await asyncio.to_thread(recognition.stop)


class QwenStreamingRecognizer(SpeechRecognizer):
    """qwen-audio-3.0-asr-flash-streaming 流式识别。

    ``api_key`` / ``ws_url`` 缺省时沿用 dashscope SDK 的环境变量与官方端点。
    """

    def __init__(self, *, api_key: str | None = None, ws_url: str | None = None) -> None:
        self.api_key = api_key
        self.ws_url = ws_url

    def _make_sdk(
        self, bridge_queue: asyncio.Queue[_BridgeEvent], loop: asyncio.AbstractEventLoop
    ) -> Recognition:
        with DASHSCOPE_CONFIG_LOCK:
            if self.ws_url:
                dashscope.base_websocket_api_url = self.ws_url
            if self.api_key:
                dashscope.api_key = self.api_key

        class _Callback(RecognitionCallback):
            def on_event(self, result: RecognitionResult) -> None:
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

            def on_error(self, result: RecognitionResult) -> None:
                loop.call_soon_threadsafe(
                    bridge_queue.put_nowait,
                    _BridgeEvent(kind="error", message=str(result.message)),
                )

        return Recognition(
            model=VOICE_ASR_MODEL,
            format="pcm",
            sample_rate=ASR_SAMPLE_RATE,
            callback=_Callback(),
        )

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
