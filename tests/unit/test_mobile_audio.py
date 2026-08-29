"""MobileAsrSessionManager / MobileTtsSequencer 纯逻辑测试（V0.3.5 §5）。

使用注入的 FakeRecognizer（方法与真实
``QwenStreamingRecognizer.stream_transcribe`` 同签名），不发网络请求。
"""

from __future__ import annotations

import base64
import threading
from collections.abc import AsyncIterable, AsyncIterator

import pytest

from pair_harness.core.contracts import AsrEvent
from pair_harness.desktop_backend.mobile_audio import (
    MobileAsrSessionManager,
    MobileAudioError,
    MobileTtsSequencer,
)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class FakeRecognizer:
    """记录型 fake：与真实识别器接口一致（异步生成器）。

    ``partials`` 在消费每个分片后按序产出；流结束后按
    ``error``/``final_text`` 产出 error 或 final 事件（final 为空时
    不产出，与真实适配器一致）。
    """

    def __init__(
        self,
        *,
        partials: tuple[str, ...] = (),
        final_text: str = "你好世界",
        error: str | None = None,
    ) -> None:
        self.received: list[bytes] = []
        self.partials = list(partials)
        self.final_text = final_text
        self.error = error
        self.finished = threading.Event()

    async def stream_transcribe(
        self, audio_stream: AsyncIterable[bytes]
    ) -> AsyncIterator[AsrEvent]:
        async for chunk in audio_stream:
            self.received.append(chunk)
            if self.partials:
                yield AsrEvent(type="partial", text=self.partials.pop(0))
        self.finished.set()
        if self.error is not None:
            yield AsrEvent(type="error", error=self.error)
        elif self.final_text:
            yield AsrEvent(type="final", text=self.final_text)


# ---------------------------------------------------------------------------
# 会话生命周期
# ---------------------------------------------------------------------------


def test_lifecycle_start_feed_end_returns_final() -> None:
    events: list[tuple[str, str, str, bool]] = []
    fake = FakeRecognizer(final_text="你好世界")
    mgr = MobileAsrSessionManager(
        on_transcript=lambda c, s, t, f: events.append((c, s, t, f))
    )
    session_id = mgr.start_session("conv-1", "conn-1", lambda: fake)
    assert len(session_id) == 32
    pcm1, pcm2 = b"pcm-chunk-1", b"pcm-chunk-2"
    mgr.feed_chunk(session_id, 0, b64(pcm1))
    mgr.feed_chunk(session_id, 1, b64(pcm2))
    final = mgr.end_session(session_id)
    assert final == "你好世界"
    # fake recognizer 收到的字节与解码后一致（end 阻塞至收尾，无竞态）
    assert fake.received == [pcm1, pcm2]
    assert events == [("conv-1", session_id, "你好世界", True)]


def test_empty_final_returned_as_empty_string() -> None:
    events: list[tuple[str, str, str, bool]] = []
    mgr = MobileAsrSessionManager(
        on_transcript=lambda c, s, t, f: events.append((c, s, t, f))
    )
    sid = mgr.start_session("conv-1", "conn-1", lambda: FakeRecognizer(final_text=""))
    try:
        assert mgr.end_session(sid) == ""
        # 模块如实回调；是否报 voice_transcript_empty 由调用方决定
        assert events == [("conv-1", sid, "", True)]
    finally:
        mgr.cancel_session(sid)


def test_partial_callbacks_emitted() -> None:
    events: list[tuple[str, str, str, bool]] = []
    fake = FakeRecognizer(partials=("你", "你好"), final_text="你好")
    mgr = MobileAsrSessionManager(
        on_transcript=lambda c, s, t, f: events.append((c, s, t, f))
    )
    sid = mgr.start_session("conv-1", "conn-1", lambda: fake)
    try:
        mgr.feed_chunk(sid, 0, b64(b"a"))
        mgr.feed_chunk(sid, 1, b64(b"b"))
        assert mgr.end_session(sid) == "你好"
        assert [(t, f) for _, _, t, f in events if not f] == [
            ("你", False),
            ("你好", False),
        ]
        assert [(t, f) for _, _, t, f in events if f] == [("你好", True)]
    finally:
        mgr.cancel_session(sid)


def test_parallel_conversations_are_independent() -> None:
    fake_a = FakeRecognizer(final_text="A 的转写")
    fake_b = FakeRecognizer(final_text="B 的转写")
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid_a = mgr.start_session("conv-a", "conn-1", lambda: fake_a)
    sid_b = mgr.start_session("conv-b", "conn-1", lambda: fake_b)
    try:
        mgr.feed_chunk(sid_a, 0, b64(b"a1"))
        mgr.feed_chunk(sid_b, 0, b64(b"b1"))
        mgr.feed_chunk(sid_a, 1, b64(b"a2"))
        assert mgr.end_session(sid_a) == "A 的转写"
        assert fake_a.received == [b"a1", b"a2"]
        assert mgr.end_session(sid_b) == "B 的转写"
        assert fake_b.received == [b"b1"]
    finally:
        mgr.cancel_session(sid_a)
        mgr.cancel_session(sid_b)


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------


def test_seq_gap_raises_with_expected_and_actual() -> None:
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid = mgr.start_session("conv-1", "conn-1", FakeRecognizer)
    try:
        mgr.feed_chunk(sid, 0, b64(b"a"))
        with pytest.raises(MobileAudioError) as ei:
            mgr.feed_chunk(sid, 2, b64(b"b"))
        assert ei.value.code == "voice_audio_seq_gap"
        assert "1" in str(ei.value) and "2" in str(ei.value)
        # 跳号不消耗序号：补上期望的 1 后会话仍可正常结束
        mgr.feed_chunk(sid, 1, b64(b"b"))
        assert mgr.end_session(sid) == "你好世界"
    finally:
        mgr.cancel_session(sid)


def test_invalid_base64_raises() -> None:
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid = mgr.start_session("conv-1", "conn-1", FakeRecognizer)
    try:
        with pytest.raises(MobileAudioError) as ei:
            mgr.feed_chunk(sid, 0, "not-valid-base64!")
        assert ei.value.code == "voice_audio_invalid_base64"
    finally:
        mgr.cancel_session(sid)


def test_unknown_session_raises() -> None:
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    with pytest.raises(MobileAudioError) as ei:
        mgr.feed_chunk("missing-session", 0, b64(b"x"))
    assert ei.value.code == "voice_session_not_found"


def test_duplicate_start_same_conversation_rejected() -> None:
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid = mgr.start_session("conv-1", "conn-1", FakeRecognizer)
    try:
        with pytest.raises(ValueError) as ei:
            mgr.start_session("conv-1", "conn-2", FakeRecognizer)
        assert isinstance(ei.value, MobileAudioError)
        assert ei.value.code == "voice_session_exists"
        assert "该会话已有进行中的语音转写" in str(ei.value)
    finally:
        mgr.cancel_session(sid)
    # 取消后同一 conversation 可重新开始
    sid2 = mgr.start_session("conv-1", "conn-1", FakeRecognizer)
    mgr.cancel_session(sid2)


def test_cancel_then_feed_raises_not_found() -> None:
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid = mgr.start_session("conv-1", "conn-1", FakeRecognizer)
    mgr.cancel_session(sid)
    with pytest.raises(MobileAudioError) as ei:
        mgr.feed_chunk(sid, 0, b64(b"x"))
    assert ei.value.code == "voice_session_not_found"
    mgr.cancel_session(sid)  # 幂等


def test_cancel_all_for_connection_is_silent_and_scoped() -> None:
    events: list[tuple[str, str, str, bool]] = []
    fake1 = FakeRecognizer(partials=("hello",), final_text="hello")
    fake2 = FakeRecognizer(final_text="world")
    mgr = MobileAsrSessionManager(
        on_transcript=lambda c, s, t, f: events.append((c, s, t, f))
    )
    sid1 = mgr.start_session("conv-a", "conn-1", lambda: fake1)
    sid2 = mgr.start_session("conv-b", "conn-2", lambda: fake2)
    try:
        mgr.feed_chunk(sid1, 0, b64(b"x"))
        mgr.cancel_all_for_connection("conn-1")
        # 另一连接的会话不受影响
        assert mgr.end_session(sid2) == "world"
        assert fake2.received == []
        # 已取消会话：feed 报 session_not_found，且无 final 事件
        with pytest.raises(MobileAudioError) as ei:
            mgr.feed_chunk(sid1, 1, b64(b"y"))
        assert ei.value.code == "voice_session_not_found"
        # 被取消的会话静默：不发 final；另一连接的正常会话仍发 final
        assert not any(is_final for s, _, _, is_final in events if s == sid1)
        assert ("conv-b", sid2, "world", True) in events
    finally:
        mgr.cancel_session(sid1)
        mgr.cancel_session(sid2)


def test_asr_error_surfaces_as_voice_asr_failed() -> None:
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid = mgr.start_session(
        "conv-1", "conn-1", lambda: FakeRecognizer(error="识别服务失败")
    )
    try:
        with pytest.raises(MobileAudioError) as ei:
            mgr.end_session(sid)
        assert ei.value.code == "voice_asr_failed"
        assert "识别服务失败" in str(ei.value)
    finally:
        mgr.cancel_session(sid)


# ---------------------------------------------------------------------------
# 下行 TTS 分片编目
# ---------------------------------------------------------------------------


def test_sequencer_feed_monotonic_seq_and_roundtrip() -> None:
    seq = MobileTtsSequencer()
    seq.begin("m1", "conv-1")
    pcm1, pcm2 = b"tts-data-1", b"tts-data-2"
    chunk1 = seq.feed("m1", pcm1)
    chunk2 = seq.feed("m1", pcm2)
    assert chunk1 == {
        "conversation_id": "conv-1",
        "message_id": "m1",
        "seq": 0,
        "mime": "audio/pcm;rate=24000",
        "data": b64(pcm1),
    }
    assert chunk2["seq"] == 1
    assert chunk2["conversation_id"] == "conv-1"
    assert chunk2["mime"] == "audio/pcm;rate=24000"
    # base64 可解码还原 PCM
    assert base64.b64decode(chunk1["data"]) == pcm1
    assert base64.b64decode(chunk2["data"]) == pcm2
    end_payload = seq.end("m1")
    assert end_payload == {"conversation_id": "conv-1", "message_id": "m1"}
    assert seq.end("m1") == end_payload  # end 幂等


def test_sequencer_duplicate_begin_raises() -> None:
    seq = MobileTtsSequencer()
    seq.begin("m1", "conv-1")
    with pytest.raises(MobileAudioError) as ei:
        seq.begin("m1", "conv-1")
    assert ei.value.code == "voice_tts_message_exists"


def test_sequencer_feed_after_end_raises() -> None:
    seq = MobileTtsSequencer()
    seq.begin("m1", "conv-1")
    seq.feed("m1", b"x")
    seq.end("m1")
    with pytest.raises(MobileAudioError) as ei:
        seq.feed("m1", b"y")
    assert ei.value.code == "voice_tts_message_closed"


def test_sequencer_stop_then_feed_raises_and_rebegin_allowed() -> None:
    seq = MobileTtsSequencer()
    seq.begin("m1", "conv-1")
    seq.feed("m1", b"x")
    seq.stop("m1")
    with pytest.raises(MobileAudioError) as ei:
        seq.feed("m1", b"y")
    assert ei.value.code == "voice_tts_message_not_found"
    # stop 清理后可重建同一 message_id
    seq.begin("m1", "conv-1")
    assert seq.feed("m1", b"z")["seq"] == 0
    seq.stop("m1")
    seq.stop("m1")  # 幂等


def test_sequencer_unknown_message_errors() -> None:
    seq = MobileTtsSequencer()
    with pytest.raises(MobileAudioError) as ei:
        seq.feed("nope", b"x")
    assert ei.value.code == "voice_tts_message_not_found"
    with pytest.raises(MobileAudioError) as ei:
        seq.end("nope")
    assert ei.value.code == "voice_tts_message_not_found"
    seq.stop("nope")  # 未知消息 stop = 幂等 no-op
