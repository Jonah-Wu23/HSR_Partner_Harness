"""Qwen 流式 ASR/TTS SDK 事件映射测试（B2.3 ASR 部分，B2.4 追加 TTS 部分）。

用 FakeRecognition 替换 dashscope 的 Recognition，直接驱动 SDK 回调
（on_event / on_complete / on_error），验证适配器产出的 AsrEvent 流
与生命周期（start → 喂帧 → stop → complete/error → final）。
"""

from __future__ import annotations

import asyncio
import types
from collections.abc import Callable

import dashscope
import pytest

from pair_harness.adapters.audio import qwen_asr
from pair_harness.adapters.audio.qwen_asr import QwenAsrError, QwenStreamingRecognizer
from pair_harness.adapters.audio.qwen_tts import QwenSpeechSynthesizer, QwenTtsError
from pair_harness.core.contracts import SpeechRequest


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


# ---------------------------------------------------------------------------
# TTS：事件映射（dashscope.audio.tts_v2）
# ---------------------------------------------------------------------------


class FakeTtsSynthesizer:
    """模拟 dashscope.audio.tts_v2.SpeechSynthesizer 的 streaming_call 模式。"""

    instances: list["FakeTtsSynthesizer"] = []
    auto_complete: bool = True  # streaming_call 时立即回调音频 + complete
    error_on_call: str | None = None  # 非 None 时 streaming_call 触发 on_error

    def __init__(self, model, voice, format, callback, **kwargs):
        self.model = model
        self.voice = voice
        self.format = format
        self.callback = callback
        self.texts: list[str] = []
        self.completed = False
        self.cancelled = False
        FakeTtsSynthesizer.instances.append(self)

    def streaming_call(self, text: str) -> None:
        self.texts.append(text)
        if type(self).error_on_call is not None:
            self.callback.on_error(types.SimpleNamespace(message=type(self).error_on_call))
            return
        if type(self).auto_complete:
            self.callback.on_data(b"\x00" * 640)
            self.callback.on_data(b"\x11" * 320)
            self.callback.on_complete()

    def streaming_complete(self, complete_timeout_millis=600000) -> None:
        self.completed = True

    def streaming_cancel(self) -> None:
        self.cancelled = True


@pytest.fixture
def fake_tts_sdk(monkeypatch: pytest.MonkeyPatch) -> type[FakeTtsSynthesizer]:
    import dashscope.audio.tts_v2  # noqa: F401 - 确保模块已加载

    FakeTtsSynthesizer.instances.clear()
    FakeTtsSynthesizer.auto_complete = True
    FakeTtsSynthesizer.error_on_call = None
    monkeypatch.setattr(dashscope.audio.tts_v2, "SpeechSynthesizer", FakeTtsSynthesizer)
    monkeypatch.setattr(
        dashscope.audio.tts_v2,
        "AudioFormat",
        types.SimpleNamespace(PCM_24000HZ_MONO_16BIT="pcm_24000"),
    )
    monkeypatch.setattr(dashscope.audio.tts_v2, "ResultCallback", object)
    return FakeTtsSynthesizer


def _tts_request(text: str = "你好") -> SpeechRequest:
    return SpeechRequest(text=text, voice_id="demo-voice", message_id="m1")


async def test_tts_yields_chunks_then_final(fake_tts_sdk) -> None:
    synthesizer = QwenSpeechSynthesizer()
    chunks = [c async for c in synthesizer.synthesize(_tts_request())]
    assert len(chunks) == 3
    assert chunks[0].pcm == b"\x00" * 640
    assert chunks[1].pcm == b"\x11" * 320
    assert chunks[0].sample_rate == 24_000
    assert chunks[0].channels == 1
    assert chunks[0].final is False
    assert chunks[2].final is True
    assert chunks[2].pcm == b""


async def test_tts_voice_model_format_passed(fake_tts_sdk) -> None:
    synthesizer = QwenSpeechSynthesizer(model="qwen-tts-test")
    chunks = [c async for c in synthesizer.synthesize(_tts_request())]
    assert chunks  # 正常合成完成
    fake = FakeTtsSynthesizer.instances[0]
    assert fake.voice == "demo-voice"
    assert fake.model == "qwen-tts-test"
    assert fake.format == "pcm_24000"
    assert fake.texts == ["你好"]
    assert fake.completed is True
    assert fake.cancelled is False


async def test_tts_error_raises(fake_tts_sdk) -> None:
    FakeTtsSynthesizer.error_on_call = "合成失败"
    synthesizer = QwenSpeechSynthesizer()
    with pytest.raises(QwenTtsError, match="合成失败"):
        [c async for c in synthesizer.synthesize(_tts_request())]


async def test_tts_empty_text_raises(fake_tts_sdk) -> None:
    synthesizer = QwenSpeechSynthesizer()
    with pytest.raises(QwenTtsError, match="文本为空"):
        [c async for c in synthesizer.synthesize(_tts_request("   "))]


async def test_tts_aclose_cancels_synthesis(fake_tts_sdk) -> None:
    FakeTtsSynthesizer.auto_complete = False  # 服务端不回包，卡在等待
    synthesizer = QwenSpeechSynthesizer()
    agen = synthesizer.synthesize(_tts_request())
    # 启动迭代（async generator 惰性），让底层线程进入 streaming_call
    anext_task = asyncio.create_task(agen.__anext__())
    for _ in range(200):
        if FakeTtsSynthesizer.instances and FakeTtsSynthesizer.instances[0].texts:
            break
        await asyncio.sleep(0.01)
    assert FakeTtsSynthesizer.instances[0].texts == ["你好"]
    # 取消迭代：generator 的 finally 会置 closed 并等待底层线程取消
    anext_task.cancel()
    try:
        await anext_task
    except (asyncio.CancelledError, StopAsyncIteration):
        pass
    fake = FakeTtsSynthesizer.instances[0]
    assert fake.cancelled is True
    assert fake.completed is False


async def test_tts_api_key_applied(fake_tts_sdk, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashscope, "api_key", "original-key")
    synthesizer = QwenSpeechSynthesizer(api_key="tts-key")
    [c async for c in synthesizer.synthesize(_tts_request())]
    assert dashscope.api_key == "tts-key"
