"""Qwen 流式 ASR/TTS SDK 事件映射测试（B2.3 ASR 部分，B2.4 追加 TTS 部分）。

用 FakeRecognition 替换 dashscope 的 Recognition，直接驱动 SDK 回调
（on_event / on_complete / on_error），验证适配器产出的 AsrEvent 流
与生命周期（start → 喂帧 → stop → complete/error → final）。
"""

from __future__ import annotations

from collections.abc import Callable

import dashscope
import pytest

from pair_harness.adapters.audio import qwen_asr
from pair_harness.adapters.audio.qwen_asr import QwenAsrError, QwenStreamingRecognizer


class FakeResult:
    """模拟 Recognition 回调的 result 对象。"""

    def __init__(self, text: str = "", sentence_end: bool = False, message: str | None = None):
        self._sentence = {"text": text}
        self._sentence_end = sentence_end
        self.message = message

    def get_sentence(self):
        return self._sentence

    def is_sentence_end(self, sentence) -> bool:
        return self._sentence_end


class FakeRecognition:
    """模拟 dashscope.audio.asr.Recognition：记录调用并在 stop() 时收尾。"""

    instances: list["FakeRecognition"] = []
    complete_on_stop: bool = True  # 类级默认；测试可提前改写

    def __init__(self, model, format, sample_rate, callback, **kwargs):
        self.model = model
        self.format = format
        self.sample_rate = sample_rate
        self.callback = callback
        self.frames: list[bytes] = []
        self.started = False
        self.stopped = False
        self.complete_on_stop = type(self).complete_on_stop
        FakeRecognition.instances.append(self)

    def start(self) -> None:
        self.started = True

    def send_audio_frame(self, frame: bytes) -> None:
        self.frames.append(frame)

    def stop(self) -> None:
        self.stopped = True
        if self.complete_on_stop:
            self.callback.on_complete()


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> type[FakeRecognition]:
    FakeRecognition.instances.clear()
    monkeypatch.setattr(dashscope.audio.asr, "Recognition", FakeRecognition)
    monkeypatch.setattr(dashscope.audio.asr, "RecognitionCallback", object)
    return FakeRecognition


def _stream(chunks: list[bytes], emitter: Callable[[], None] | None = None):
    async def gen():
        for chunk in chunks:
            if emitter is not None:
                emitter()
            yield chunk

    return gen()


async def _events(recognizer, chunks, emitter=None):
    return [e async for e in recognizer.stream_transcribe(_stream(chunks, emitter))]


# ---------------------------------------------------------------------------
# ASR：事件映射
# ---------------------------------------------------------------------------


async def test_partial_events_then_final(fake_sdk) -> None:
    recognizer = QwenStreamingRecognizer()
    calls = {"n": 0}

    def emit():
        fake = FakeRecognition.instances[0]
        if calls["n"] == 0:
            fake.callback.on_event(FakeResult(text="你好"))
        else:
            fake.callback.on_event(FakeResult(text="你好世界"))
        calls["n"] += 1

    events = await _events(recognizer, [b"\x00" * 1024] * 2, emit)
    assert [(e.type, e.text) for e in events] == [
        ("partial", "你好"),
        ("partial", "你好世界"),
        ("final", "你好世界"),
    ]


async def test_sentence_end_settles_stable(fake_sdk) -> None:
    recognizer = QwenStreamingRecognizer()

    def emit():
        fake = FakeRecognition.instances[0]
        fake.callback.on_event(FakeResult(text="你好。", sentence_end=True))
        fake.callback.on_event(FakeResult(text="请问？", sentence_end=True))

    events = await _events(recognizer, [b"\x00" * 512], emit)
    assert [(e.type, e.text) for e in events] == [
        ("partial", "你好。"),
        ("partial", "你好。请问？"),
        ("final", "你好。请问？"),
    ]


async def test_empty_text_produces_no_events(fake_sdk) -> None:
    recognizer = QwenStreamingRecognizer()

    def emit():
        fake = FakeRecognition.instances[0]
        fake.callback.on_event(FakeResult(text=""))
        fake.callback.on_event(FakeResult(text="", sentence_end=True))

    events = await _events(recognizer, [b"\x00" * 512], emit)
    assert events == []


async def test_error_yields_error_and_stops(fake_sdk) -> None:
    recognizer = QwenStreamingRecognizer()

    def emit():
        fake = FakeRecognition.instances[0]
        fake.callback.on_event(FakeResult(text="你好"))
        fake.callback.on_error(FakeResult(message="服务不可用"))

    events = await _events(recognizer, [b"\x00" * 512], emit)
    assert [(e.type, e.text, e.error) for e in events] == [
        ("partial", "你好", None),
        ("error", "", "服务不可用"),
    ]


async def test_duplicate_partial_not_repeated(fake_sdk) -> None:
    recognizer = QwenStreamingRecognizer()

    def emit():
        fake = FakeRecognition.instances[0]
        fake.callback.on_event(FakeResult(text="你好"))
        fake.callback.on_event(FakeResult(text="你好"))

    events = await _events(recognizer, [b"\x00" * 512], emit)
    assert [(e.type, e.text) for e in events] == [("partial", "你好"), ("final", "你好")]


async def test_frames_forwarded_to_sdk(fake_sdk) -> None:
    recognizer = QwenStreamingRecognizer()
    chunks = [b"\x00" * 1024, b"", b"\x00" * 512]
    events = await _events(recognizer, chunks)
    assert events == []
    fake = FakeRecognition.instances[0]
    assert fake.started is True
    assert fake.stopped is True
    assert fake.frames == [b"\x00" * 1024, b"\x00" * 512]  # 空块被跳过


async def test_stop_timeout_yields_error(fake_sdk, monkeypatch: pytest.MonkeyPatch) -> None:
    recognizer = QwenStreamingRecognizer()
    FakeRecognition.complete_on_stop = False  # SDK 不回调 complete
    monkeypatch.setattr(qwen_asr, "_TAIL_TIMEOUT_S", 0.1)
    events = await _events(recognizer, [b"\x00" * 512])
    assert [(e.type, e.error) for e in events] == [("error", "识别收尾超时")]


async def test_configured_model_and_sample_rate(fake_sdk) -> None:
    recognizer = QwenStreamingRecognizer(model="qwen-test-model", sample_rate=8000)
    await _events(recognizer, [b"\x00" * 256])
    fake = FakeRecognition.instances[0]
    assert fake.model == "qwen-test-model"
    assert fake.sample_rate == 8000
    assert fake.format == "pcm"


async def test_api_key_and_ws_url_applied(fake_sdk, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashscope, "api_key", "original-key")
    monkeypatch.setattr(dashscope, "base_websocket_api_url", "wss://original")
    recognizer = QwenStreamingRecognizer(api_key="test-key", ws_url="wss://custom")
    await _events(recognizer, [b"\x00" * 256])
    assert dashscope.api_key == "test-key"
    assert dashscope.base_websocket_api_url == "wss://custom"


async def test_defaults_do_not_mutate_globals(fake_sdk, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashscope, "api_key", "keep-me")
    monkeypatch.setattr(dashscope, "base_websocket_api_url", "wss://keep")
    recognizer = QwenStreamingRecognizer()
    await _events(recognizer, [b"\x00" * 256])
    assert dashscope.api_key == "keep-me"
    assert dashscope.base_websocket_api_url == "wss://keep"
