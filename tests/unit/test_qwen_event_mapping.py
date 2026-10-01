from __future__ import annotations

import asyncio
import logging

import pytest

from pair_harness.adapters.audio import qwen_asr, qwen_tts
from pair_harness.adapters.audio.qwen_asr import QwenStreamingRecognizer
from pair_harness.adapters.audio.qwen_tts import QwenSpeechSynthesizer, QwenTtsError
from pair_harness.core.contracts import SpeechRequest
from pair_harness.voice_models import VOICE_ASR_MODEL, VOICE_TTS_MODEL
from tests.fixtures.dashscope_ws import DashScopeTask
from tests.service_helpers import wait_until

FRAME = b"\x00" * 640


async def _audio(*chunks: bytes):
    for chunk in chunks:
        yield chunk


async def _transcribe(server, audio) -> list:
    recognizer = QwenStreamingRecognizer(api_key="asr-test-key", ws_url=server.url)
    return [event async for event in recognizer.stream_transcribe(audio)]


# ---------------------------------------------------------------------------
# ASR
# ---------------------------------------------------------------------------


async def test_recognizer_sends_run_task_and_non_empty_frames(dashscope_server) -> None:
    async def script(task: DashScopeTask) -> None:
        await task.expect("run-task")
        await task.started()
        await task.expect("finish-task")
        # 空文本结果不产出事件
        await task.sentence(0, "")
        await task.sentence(500, "")
        await task.finished()

    dashscope_server.serve(script)
    events = await _transcribe(
        dashscope_server, _audio(b"\x00" * 1024, b"", b"\x00" * 512)
    )

    assert events == []
    task = dashscope_server.tasks[0]
    assert task.headers["Authorization"] == "Bearer asr-test-key"
    assert task.run_task["model"] == VOICE_ASR_MODEL
    assert task.run_task["parameters"]["sample_rate"] == 16_000
    assert task.run_task["parameters"]["format"] == "pcm"
    assert task.audio == [b"\x00" * 1024, b"\x00" * 512]


async def test_sentence_updates_yield_partials_then_final(dashscope_server) -> None:
    async def script(task: DashScopeTask) -> None:
        await task.expect("run-task")
        await task.started()
        await task.next_audio()
        await task.sentence(0, "你好")
        await task.next_audio()
        await task.sentence(0, "你好")
        await task.sentence(0, "你好世界", sentence_end=True)
        await task.expect("finish-task")
        await task.finished()

    dashscope_server.serve(script)
    events = await _transcribe(dashscope_server, _audio(FRAME, FRAME))

    # 内容相同的结果不重复产出 partial
    assert [(e.type, e.text) for e in events] == [
        ("partial", "你好"),
        ("partial", "你好世界"),
        ("final", "你好世界"),
    ]


async def test_partial_arrives_while_audio_is_still_streaming(dashscope_server) -> None:
    partial_seen = asyncio.Event()

    async def script(task: DashScopeTask) -> None:
        await task.expect("run-task")
        await task.started()
        await task.next_audio()
        await task.sentence(0, "你好")
        await task.expect("finish-task")
        await task.finished()

    async def audio():
        # 像麦克风一样按 20 ms 节奏持续送帧，直到收到 partial 才结束
        while not partial_seen.is_set():
            yield FRAME
            await asyncio.sleep(0.02)

    async def collect() -> list:
        recognizer = QwenStreamingRecognizer(api_key="asr-test-key", ws_url=dashscope_server.url)
        events = []
        async for event in recognizer.stream_transcribe(audio()):
            events.append(event)
            partial_seen.set()
        return events

    dashscope_server.serve(script)
    events = await asyncio.wait_for(collect(), timeout=5)
    assert [(e.type, e.text) for e in events] == [("partial", "你好"), ("final", "你好")]


async def test_task_failed_yields_server_error(dashscope_server) -> None:
    async def script(task: DashScopeTask) -> None:
        await task.expect("run-task")
        await task.started()
        await task.next_audio()
        await task.sentence(0, "你好")
        await task.failed("InvalidParameter", "audio format is not supported")

    dashscope_server.serve(script)
    events = await _transcribe(dashscope_server, _audio(FRAME, FRAME, FRAME))
    assert [(e.type, e.text, e.error) for e in events] == [
        ("partial", "你好", None),
        ("error", "", "audio format is not supported"),
    ]


async def test_rejected_handshake_reports_original_sdk_error(dashscope_server) -> None:
    """握手被拒后 SDK 拒收后续音频帧，产出的仍是握手失败的原始错误。"""
    dashscope_server.reject_handshake(401)

    async def audio():
        await wait_until(lambda: bool(dashscope_server.handshakes))
        yield FRAME

    events = await _transcribe(dashscope_server, audio())
    assert [(e.type, e.error) for e in events] == [
        ("error", "Unauthorized, your api-key is invalid!")
    ]


async def test_missing_completion_reports_timeout(dashscope_server, monkeypatch) -> None:
    """task-finished 不带 payload 时 SDK 不回调完成，适配器限时后如实报错。"""
    monkeypatch.setattr(qwen_asr, "_TAIL_TIMEOUT_S", 0.1)

    async def script(task: DashScopeTask) -> None:
        await task.expect("run-task")
        await task.started()
        await task.expect("finish-task")
        await task.finished(with_payload=False)

    dashscope_server.serve(script)
    events = await _transcribe(dashscope_server, _audio(FRAME))
    assert [(e.type, e.error) for e in events] == [("error", "识别收尾超时")]


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------


def _synthesizer(server) -> QwenSpeechSynthesizer:
    return QwenSpeechSynthesizer(api_key="tts-test-key", ws_url=server.url)


def _speech(text: str = "你好") -> SpeechRequest:
    return SpeechRequest(text=text, voice_id="demo-voice", message_id="m1")


async def _accept_text(task: DashScopeTask) -> None:
    """run-task → task-started → continue-task；客户端随后立即发 finish-task。"""
    await task.expect("run-task")
    await task.started()
    await task.expect("continue-task")
    await task.expect("finish-task")


def _holding_script(release_cancel: asyncio.Event | None = None):
    """下发一块音频后不再收尾，收到取消指令（且 release_cancel 放行）才回 task-finished。"""

    async def script(task: DashScopeTask) -> None:
        await _accept_text(task)
        await task.audio_out(FRAME)
        cancel = await task.expect("finish-task")
        assert cancel["payload"]["input"]["directive"] == "cancel"
        if release_cancel is not None:
            await release_cancel.wait()
        await task.finished()

    return script


async def test_synthesizer_yields_pcm_then_final(dashscope_server) -> None:
    async def script(task: DashScopeTask) -> None:
        await _accept_text(task)
        await task.audio_out(b"\x00" * 640)
        await task.audio_out(b"\x11" * 320)
        await task.finished()

    dashscope_server.serve(script)
    chunks = [chunk async for chunk in _synthesizer(dashscope_server).synthesize(_speech())]

    assert [(chunk.pcm, chunk.final) for chunk in chunks] == [
        (b"\x00" * 640, False),
        (b"\x11" * 320, False),
        (b"", True),
    ]
    assert {(chunk.sample_rate, chunk.channels) for chunk in chunks} == {(24_000, 1)}
    task = dashscope_server.tasks[0]
    assert task.headers["Authorization"] == "Bearer tts-test-key"
    assert task.run_task["model"] == VOICE_TTS_MODEL
    parameters = task.run_task["parameters"]
    assert (parameters["voice"], parameters["format"], parameters["sample_rate"]) == (
        "demo-voice",
        "pcm",
        24_000,
    )
    assert task.texts == ["你好"]
    assert task.finish_directives == [None]


async def test_task_failed_raises_server_error(dashscope_server) -> None:
    async def script(task: DashScopeTask) -> None:
        await _accept_text(task)
        await task.failed(
            "Throttling.RateQuota", "Requests rate limit exceeded, please try again later."
        )

    dashscope_server.serve(script)
    with pytest.raises(QwenTtsError, match="Throttling.RateQuota"):
        [chunk async for chunk in _synthesizer(dashscope_server).synthesize(_speech())]


async def test_unreadable_text_is_rejected_before_connecting(dashscope_server) -> None:
    with pytest.raises(QwenTtsError, match="文本为空"):
        [chunk async for chunk in _synthesizer(dashscope_server).synthesize(_speech("   "))]
    assert dashscope_server.handshakes == []


async def test_closing_stream_cancels_upstream_synthesis(dashscope_server) -> None:
    dashscope_server.serve(_holding_script())
    stream = _synthesizer(dashscope_server).synthesize(_speech())

    assert (await anext(stream)).pcm == FRAME
    await stream.aclose()
    await wait_until(lambda: dashscope_server.tasks[0].finish_directives == [None, "cancel"])


async def test_adapter_aclose_cancels_inflight_synthesis(dashscope_server) -> None:
    """消费方仍在等待下一块时，适配器 aclose 中止上游合成。"""
    dashscope_server.serve(_holding_script())
    synthesizer = _synthesizer(dashscope_server)
    stream = synthesizer.synthesize(_speech())
    await anext(stream)
    waiting = asyncio.create_task(anext(stream))

    await synthesizer.aclose()
    await wait_until(lambda: dashscope_server.tasks[0].finish_directives == [None, "cancel"])

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await synthesizer.aclose()  # 没有在途合成时直接返回


async def test_unanswered_cancel_does_not_block_close_and_is_reported(
    dashscope_server, monkeypatch, caplog
) -> None:
    """服务端迟迟不回应取消时关闭及时返回，长时间未结束的合成线程记 WARNING。"""
    monkeypatch.setattr(qwen_tts, "_CLOSE_WAIT_S", 0.05)
    monkeypatch.setattr(qwen_tts, "_TTS_THREAD_REAP_WARN_S", 0.05)
    release = asyncio.Event()
    dashscope_server.serve(_holding_script(release_cancel=release))
    stream = _synthesizer(dashscope_server).synthesize(_speech())
    await anext(stream)

    with caplog.at_level(logging.WARNING, logger=qwen_tts.logger.name):
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        await stream.aclose()
        assert loop.time() - started_at < 0.5
        await wait_until(lambda: "TTS 合成线程" in caplog.text)

    # 放行取消后 SDK 收到 task-finished 并关闭连接，合成线程随之结束。
    release.set()
    await wait_until(lambda: dashscope_server.tasks[0].closed)
