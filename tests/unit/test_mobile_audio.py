from __future__ import annotations

import asyncio
import base64
import io
import threading
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

import pytest

from pair_harness.core.contracts import AsrEvent
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.mobile_audio import (
    MobileAsrSessionManager,
    MobileAudioError,
    MobileTtsSequencer,
)
from pair_harness.desktop_backend.router import JsonlWriter
from tests.fixtures.dashscope_ws import DashScopeTask
from tests.service_helpers import call, expect_service_error, wait_until


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class FakeRecognizer:
    """识别器端口替身，经 recognizer_factory 注入会话管理器。

    ``partials`` 在消费每个分片后按序产出；流结束后按 ``error``/``final_text``
    产出 error 或 final 事件，final 为空时不产出，与真实适配器一致。
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


async def test_lifecycle_start_feed_end_returns_final() -> None:
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
    conversation_id, final = await mgr.end_session(session_id)
    assert conversation_id == "conv-1"
    assert final == "你好世界"
    # end_session 等识别收尾后才返回，识别器已收到解码后的全部分片
    assert fake.received == [pcm1, pcm2]
    assert events == [("conv-1", session_id, "你好世界", True)]


async def test_empty_final_returned_as_empty_string() -> None:
    events: list[tuple[str, str, str, bool]] = []
    mgr = MobileAsrSessionManager(
        on_transcript=lambda c, s, t, f: events.append((c, s, t, f))
    )
    sid = mgr.start_session("conv-1", "conn-1", lambda: FakeRecognizer(final_text=""))
    try:
        assert await mgr.end_session(sid) == ("conv-1", "")
        # 空转写照样回调，是否报 voice_transcript_empty 由调用方决定
        assert events == [("conv-1", sid, "", True)]
    finally:
        mgr.cancel_session(sid)


async def test_partial_callbacks_emitted() -> None:
    events: list[tuple[str, str, str, bool]] = []
    fake = FakeRecognizer(partials=("你", "你好"), final_text="你好")
    mgr = MobileAsrSessionManager(
        on_transcript=lambda c, s, t, f: events.append((c, s, t, f))
    )
    sid = mgr.start_session("conv-1", "conn-1", lambda: fake)
    try:
        mgr.feed_chunk(sid, 0, b64(b"a"))
        mgr.feed_chunk(sid, 1, b64(b"b"))
        assert await mgr.end_session(sid) == ("conv-1", "你好")
        assert [(t, f) for _, _, t, f in events if not f] == [
            ("你", False),
            ("你好", False),
        ]
        assert [(t, f) for _, _, t, f in events if f] == [("你好", True)]
    finally:
        mgr.cancel_session(sid)


async def test_parallel_conversations_are_independent() -> None:
    fake_a = FakeRecognizer(final_text="A 的转写")
    fake_b = FakeRecognizer(final_text="B 的转写")
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid_a = mgr.start_session("conv-a", "conn-1", lambda: fake_a)
    sid_b = mgr.start_session("conv-b", "conn-1", lambda: fake_b)
    try:
        mgr.feed_chunk(sid_a, 0, b64(b"a1"))
        mgr.feed_chunk(sid_b, 0, b64(b"b1"))
        mgr.feed_chunk(sid_a, 1, b64(b"a2"))
        assert await mgr.end_session(sid_a) == ("conv-a", "A 的转写")
        assert fake_a.received == [b"a1", b"a2"]
        assert await mgr.end_session(sid_b) == ("conv-b", "B 的转写")
        assert fake_b.received == [b"b1"]
    finally:
        mgr.cancel_session(sid_a)
        mgr.cancel_session(sid_b)


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------


async def test_seq_gap_raises_with_expected_and_actual() -> None:
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
        assert await mgr.end_session(sid) == ("conv-1", "你好世界")
    finally:
        mgr.cancel_session(sid)


async def test_invalid_base64_raises() -> None:
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


async def test_duplicate_start_same_conversation_rejected() -> None:
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


async def test_cancel_then_feed_raises_not_found() -> None:
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid = mgr.start_session("conv-1", "conn-1", FakeRecognizer)
    assert mgr.cancel_session(sid) == "conv-1"
    with pytest.raises(MobileAudioError) as ei:
        mgr.feed_chunk(sid, 0, b64(b"x"))
    assert ei.value.code == "voice_session_not_found"
    assert mgr.cancel_session(sid) is None  # 幂等


async def test_cancel_all_for_connection_is_silent_and_scoped() -> None:
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
        assert mgr.cancel_all_for_connection("conn-1") == [sid1]
        # 另一连接的会话不受影响
        assert await mgr.end_session(sid2) == ("conv-b", "world")
        assert fake2.received == []
        # 已取消会话：feed 报 session_not_found，且无 final 事件
        with pytest.raises(MobileAudioError) as ei:
            mgr.feed_chunk(sid1, 1, b64(b"y"))
        assert ei.value.code == "voice_session_not_found"
        # 被取消的会话静默，不发 final；另一连接的正常会话仍发 final
        assert not any(session == sid1 and is_final for _, session, _, is_final in events)
        assert ("conv-b", sid2, "world", True) in events
    finally:
        mgr.cancel_session(sid1)
        mgr.cancel_session(sid2)


async def test_asr_error_surfaces_as_voice_asr_failed() -> None:
    mgr = MobileAsrSessionManager(on_transcript=lambda *_: None)
    sid = mgr.start_session(
        "conv-1", "conn-1", lambda: FakeRecognizer(error="识别服务失败")
    )
    try:
        with pytest.raises(MobileAudioError) as ei:
            await mgr.end_session(sid)
        assert ei.value.code == "voice_asr_failed"
        assert "识别服务失败" in str(ei.value)
    finally:
        mgr.cancel_session(sid)


# ---------------------------------------------------------------------------
# 下行 TTS 分片编目
# ---------------------------------------------------------------------------


def test_sequencer_feed_monotonic_seq_and_roundtrip() -> None:
    seq = MobileTtsSequencer()
    stream = seq.begin("m1", "conv-1")
    pcm1, pcm2 = b"tts-data-1", b"tts-data-2"
    chunk1 = stream.chunk(pcm1)
    chunk2 = stream.chunk(pcm2)
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
    assert stream.end_payload() == {"conversation_id": "conv-1", "message_id": "m1"}


def test_sequencer_duplicate_begin_raises() -> None:
    seq = MobileTtsSequencer()
    seq.begin("m1", "conv-1")
    with pytest.raises(MobileAudioError) as ei:
        seq.begin("m1", "conv-1")
    assert ei.value.code == "voice_tts_message_exists"


def test_sequencer_stop_marks_handle_and_frees_message_id() -> None:
    """stop 把生产者持有的句柄置为 stopped；同一 id 之后可以重新登记，旧句柄不受影响。"""
    seq = MobileTtsSequencer()
    stream = seq.begin("m1", "conv-1")
    stream.chunk(b"x")
    seq.stop("m1")
    assert stream.stopped is True
    fresh = seq.begin("m1", "conv-1")
    assert fresh is not stream and fresh.stopped is False
    assert fresh.chunk(b"y")["seq"] == 0
    seq.stop("m1")
    seq.stop("m1")  # 幂等


def test_sequencer_finish_releases_only_its_own_handle() -> None:
    seq = MobileTtsSequencer()
    old = seq.begin("m1", "conv-1")
    seq.stop("m1")
    new = seq.begin("m1", "conv-1")
    seq.finish(old)  # 被中断的旧生产者收尾，不得注销新句柄
    seq.stop("m1")
    assert new.stopped is True
    seq.finish(new)
    seq.begin("m1", "conv-1")


# ---------------------------------------------------------------------------
# 手机语音命令：真实识别器经 PAIR_HARNESS_DASHSCOPE_WS_URL 连到本机回放端点
# ---------------------------------------------------------------------------

FRAME = b"\x01\x00" * 320


def phone(method: str, request_id: str, **params: Any) -> DesktopCommand:
    return DesktopCommand(
        request_id=request_id,
        method=method,
        params=params,
        origin="remote",
        connection_key="conn-phone",
        remote_device_key="device-phone",
        remote_device_name="测试手机",
    )


@pytest.fixture
def remote_events(service) -> list[dict[str, Any]]:
    """接上真实事件扇出，收集只发给远程连接的事件。"""
    published: list[dict[str, Any]] = []
    fanout = EventFanout(JsonlWriter(io.StringIO()))
    fanout.subscribe(published.append)
    service.attach_event_fanout(fanout)
    return published


@pytest.fixture
def dashscope_env(dashscope_server, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-dashscope-key")
    monkeypatch.setenv("PAIR_HARNESS_DASHSCOPE_WS_URL", dashscope_server.url)
    return dashscope_server


async def _silent_session(task: DashScopeTask) -> None:
    await task.expect("run-task")
    await task.started()
    await task.expect("finish-task")
    await task.finished()


def _remote_payloads(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [event["payload"] for event in events if event["event"] == name]


async def test_mobile_ptt_start_requires_dashscope_key(service, monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    await expect_service_error(
        lambda: service.handle_command(
            phone("voice.mobile_ptt_start", "start", conversation_id=service.current_conversation_id)
        ),
        "voice_not_configured",
    )


@pytest.mark.parametrize("bad_seq", ["0", 0.5, True, None])
async def test_mobile_audio_chunk_rejects_non_integer_seq(service, bad_seq) -> None:
    await expect_service_error(
        lambda: call(
            service, "chunk", "voice.mobile_audio_chunk", session_id="sess-x", seq=bad_seq, data="AAE="
        ),
        "invalid_params",
    )


async def test_mobile_ptt_round_trip_submits_transcript_as_remote_turn(
    service, dashscope_env
) -> None:
    async def script(task: DashScopeTask) -> None:
        await task.expect("run-task")
        await task.started()
        await task.expect("finish-task")
        await task.sentence(0, "手机语音文本", sentence_end=True)
        await task.finished()

    dashscope_env.serve(script)
    conversation_id = service.current_conversation_id
    started = await service.handle_command(
        phone("voice.mobile_ptt_start", "start", conversation_id=conversation_id)
    )
    session_id = started["session_id"]

    accepted = await service.handle_command(
        phone("voice.mobile_audio_chunk", "c0", session_id=session_id, seq=0, data=b64(FRAME))
    )
    assert accepted == {"accepted": True}
    # 会话管理器的跳号错误码原样返回，序号不被消耗
    await expect_service_error(
        lambda: service.handle_command(
            phone("voice.mobile_audio_chunk", "c2", session_id=session_id, seq=2, data=b64(FRAME))
        ),
        "voice_audio_seq_gap",
    )
    await service.handle_command(
        phone("voice.mobile_audio_chunk", "c1", session_id=session_id, seq=1, data=b64(FRAME))
    )
    result = await service.handle_command(phone("voice.mobile_ptt_stop", "stop", session_id=session_id))

    assert result == {
        "session_id": session_id,
        "conversation_id": conversation_id,
        "transcript": "手机语音文本",
    }
    assert dashscope_env.tasks[0].audio == [FRAME, FRAME]
    # 转写以手机身份进入聊天提交路径
    await wait_until(
        lambda: any(
            payload["turn"]["status"] == "completed"
            for payload in service.event_log.payloads("turn.status_changed")
        )
    )
    turn = service.event_log.payloads("turn.started")[-1]["turn"]
    assert (turn["origin"], turn["remote_device_key"], turn["remote_device_name"]) == (
        "remote",
        "device-phone",
        "测试手机",
    )
    submitted = service.event_log.payloads("message.created")
    assert any(
        payload["message"]["source"] == "user" and payload["message"]["text"] == "手机语音文本"
        for payload in submitted
    )


async def test_mobile_asr_timeout_cancels_session_and_reports_failure(
    service, dashscope_env, remote_events
) -> None:
    dashscope_env.serve(_silent_session)
    service._mobile_asr_timeout_s = 0.05
    conversation_id = service.current_conversation_id
    started = await service.handle_command(
        phone("voice.mobile_ptt_start", "start", conversation_id=conversation_id)
    )
    session_id = started["session_id"]

    await wait_until(lambda: bool(_remote_payloads(remote_events, "voice.mobile_asr_failed")))
    failure = _remote_payloads(remote_events, "voice.mobile_asr_failed")
    assert len(failure) == 1
    assert (failure[0]["conversation_id"], failure[0]["session_id"], failure[0]["code"]) == (
        conversation_id,
        session_id,
        "voice_session_timeout",
    )
    await expect_service_error(
        lambda: service.handle_command(phone("voice.mobile_ptt_stop", "stop", session_id=session_id)),
        "voice_session_not_found",
    )
    # 被取消的会话随后结束识别连接
    await wait_until(lambda: bool(dashscope_env.tasks) and dashscope_env.tasks[0].closed)


async def test_mobile_disconnect_cancels_session_silently(
    service, dashscope_env, remote_events
) -> None:
    dashscope_env.serve(_silent_session)
    service._mobile_asr_timeout_s = 0.05
    started = await service.handle_command(
        phone("voice.mobile_ptt_start", "start", conversation_id=service.current_conversation_id)
    )

    service.handle_remote_disconnect("conn-phone")

    await wait_until(lambda: bool(dashscope_env.tasks) and dashscope_env.tasks[0].closed)
    await asyncio.sleep(0.1)  # 超过超时时长，超时任务已随断连撤销
    assert _remote_payloads(remote_events, "voice.mobile_asr_failed") == []
    await expect_service_error(
        lambda: service.handle_command(
            phone("voice.mobile_ptt_stop", "stop", session_id=started["session_id"])
        ),
        "voice_session_not_found",
    )
