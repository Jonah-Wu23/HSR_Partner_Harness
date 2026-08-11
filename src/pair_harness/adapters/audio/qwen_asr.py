"""Qwen 流式语音识别适配器（B2）。

用 ``dashscope.audio.asr.Recognition`` 的 duplex WebSocket 把 16 kHz
int16 PCM 流实时转写。SDK 回调运行在 SDK 自有线程，回调内只做一件事——
``loop.call_soon_threadsafe(queue.put_nowait, ...)`` 把原始事件塞进
asyncio 队列；适配器的异步迭代器从队列取出并映射为 :class:`AsrEvent`。

增量合并：把旧项目 ``fun_asr_realtime_client._merge_result_events`` 的
语义移植为纯函数 :func:`merge_asr_segments`（stable 段拼接、后缀-前缀
重叠去重、partial 择优、全空返回空串）。

生命周期：一次 ``stream_transcribe`` 对应一次 ``Recognition.start()`` /
``stop()``；``stop()`` 阻塞等待 SDK 收尾（在 ``asyncio.to_thread`` 中
执行，不卡事件循环），随后按队列中的收尾哨兵产出 final 或 error。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Any

from pair_harness.core.contracts import AsrEvent
from pair_harness.core.ports import SpeechRecognizer

# stop() 后等待 SDK 收尾哨兵的超时（秒）
_TAIL_TIMEOUT_S = 5.0


class QwenAsrError(RuntimeError):
    """Qwen 流式 ASR 服务错误。"""


@dataclass(frozen=True)
class _RawSentence:
    """合并函数的输入：一次 SDK 结果事件的文本与断句标记。"""

    text: str
    sentence_end: bool = False


@dataclass
class _BridgeEvent:
    kind: str  # result | complete | error
    text: str = ""
    sentence_end: bool = False
    message: str = ""


# ---------------------------------------------------------------------------
# 增量合并（纯函数，可离线单测；语义移植自旧项目）
# ---------------------------------------------------------------------------


def merge_asr_segments(events: list[_RawSentence]) -> str:
    """stable 段 + 当前 partial 合并为最终转写。

    规则（与旧项目一致）：

    - ``sentence_end`` 的文本沉淀为 stable 段；
    - 新段与上一段做包含判断与最长后缀-前缀重叠去重；
    - partial 之间取信息更全者（前缀包含关系取长者，否则按重叠拼接）；
    - 全部为空时返回空串（调用方据此抑制 final）。
    """
    stable_segments: list[str] = []
    current_partial = ""
    last_non_empty = ""

    for event in events:
        text = str(event.text or "").strip()
        if not text:
            continue
        last_non_empty = text

        if event.sentence_end:
            candidate = _prefer_more_complete(current_partial, text)
            _append_stable_segment(stable_segments, candidate)
            current_partial = ""
        else:
            current_partial = _prefer_more_complete(current_partial, text)

    if current_partial:
        _append_stable_segment(stable_segments, current_partial)

    merged = "".join(stable_segments).strip()
    if not merged:
        return last_non_empty
    return merged


def merge_asr_partial(events: list[_RawSentence]) -> str:
    """stable 段 + 当前 partial 合并为“当前显示文本”（partial 事件用）。"""
    stable_segments: list[str] = []
    current_partial = ""

    for event in events:
        text = str(event.text or "").strip()
        if not text:
            continue
        if event.sentence_end:
            candidate = _prefer_more_complete(current_partial, text)
            _append_stable_segment(stable_segments, candidate)
            current_partial = ""
        else:
            current_partial = _prefer_more_complete(current_partial, text)

    merged = "".join(stable_segments).strip()
    if current_partial:
        merged = (merged + current_partial).strip()
    return merged


def _append_stable_segment(segments: list[str], candidate: str) -> None:
    text = str(candidate or "").strip()
    if not text:
        return
    if not segments:
        segments.append(text)
        return

    prev = segments[-1]
    if text == prev or text in prev:
        return
    if prev in text:
        segments[-1] = text
        return

    overlap = _longest_suffix_prefix_overlap(prev, text)
    if overlap > 0:
        segments[-1] = prev + text[overlap:]
    else:
        segments.append(text)


def _prefer_more_complete(existing: str, incoming: str) -> str:
    left = str(existing or "").strip()
    right = str(incoming or "").strip()
    if not left:
        return right
    if not right:
        return left
    if left == right:
        return left
    if right.startswith(left):
        return right
    if left.startswith(right):
        return left
    if right in left:
        return left
    if left in right:
        return right
    overlap = _longest_suffix_prefix_overlap(left, right)
    if overlap > 0:
        return left + right[overlap:]
    return right if len(right) >= len(left) else left


def _longest_suffix_prefix_overlap(left: str, right: str) -> int:
    max_len = min(len(left), len(right))
    for size in range(max_len, 0, -1):
        if left[-size:] == right[:size]:
            return size
    return 0


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
        model: str = "qwen-audio-3.0-asr-flash-streaming",
        sample_rate: int = 16_000,
    ) -> None:
        self.api_key = api_key
        self.ws_url = ws_url
        self.model = model
        self.sample_rate = sample_rate

    def _make_sdk(self, bridge_queue: asyncio.Queue[_BridgeEvent], loop: asyncio.AbstractEventLoop):
        try:
            import dashscope  # type: ignore
            from dashscope.audio.asr import Recognition, RecognitionCallback  # type: ignore
        except ImportError as exc:
            raise QwenAsrError("未安装 dashscope SDK（pip install -e \".[voice]\"）") from exc

        if self.ws_url:
            dashscope.base_websocket_api_url = self.ws_url
        if self.api_key:
            dashscope.api_key = self.api_key

        class _Callback(RecognitionCallback):
            def on_event(self, result) -> None:
                sentence = result.get_sentence() if hasattr(result, "get_sentence") else {}
                if not isinstance(sentence, dict):
                    sentence = {}
                text = str(sentence.get("text", "") or "").strip()
                sentence_end = bool(
                    getattr(result, "is_sentence_end", lambda s: False)(sentence)
                )
                loop.call_soon_threadsafe(
                    bridge_queue.put_nowait,
                    _BridgeEvent(kind="result", text=text, sentence_end=sentence_end),
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

        try:
            async for chunk in audio_stream:
                if not chunk:
                    continue
                recognition.send_audio_frame(chunk)
        finally:
            # 停止并等待 SDK 收尾（stop() join 工作线程，放线程池执行）
            await asyncio.to_thread(recognition.stop)

        # 收集事件直到 complete / error 哨兵（stop() 已 join，事件应已入队）
        raw_events: list[_RawSentence] = []
        yielded_partial: str | None = None
        buffered: list[_BridgeEvent] = []

        async def next_event() -> _BridgeEvent | None:
            # 先按序消费已入队事件；队列空才等待（带超时，超时按 error 处理）
            while not bridge.empty():
                buffered.append(bridge.get_nowait())
            if buffered:
                return buffered.pop(0)
            try:
                return await asyncio.wait_for(bridge.get(), timeout=_TAIL_TIMEOUT_S)
            except asyncio.TimeoutError:
                return _BridgeEvent(kind="error", message="识别收尾超时")

        while True:
            event = await next_event()
            if event is None:
                break
            if event.kind == "error":
                yield AsrEvent(type="error", error=event.message)
                return
            if event.kind == "complete":
                break
            # result
            raw_events.append(_RawSentence(text=event.text, sentence_end=event.sentence_end))
            if event.text:
                partial = merge_asr_partial(raw_events)
                if partial and partial != yielded_partial:
                    yielded_partial = partial
                    yield AsrEvent(type="partial", text=partial)
        # 收尾：合并结果非空才产出 final
        final_text = merge_asr_segments(raw_events)
        if final_text:
            yield AsrEvent(type="final", text=final_text)
