from __future__ import annotations

import base64
import io
from typing import Any

import pytest

from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.router import JsonlWriter
from tests.fixtures.dashscope_ws import DashScopeTask
from tests.service_helpers import wait_until
from tests.voice_helpers import character_reply

FRAME = b"\x01\x02" * 320
DASHSCOPE_KEY = "test-dashscope-key"


@pytest.fixture
def phone_events(service, dashscope_server, monkeypatch) -> list[dict[str, Any]]:
    """手机端在线订阅事件扇出；开发机 Key 让作者音色可用，WS 地址指向本机回放端点。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", DASHSCOPE_KEY)
    monkeypatch.setenv("PAIR_HARNESS_DASHSCOPE_WS_URL", dashscope_server.url)
    published: list[dict[str, Any]] = []
    fanout = EventFanout(JsonlWriter(io.StringIO()))
    fanout.subscribe(published.append)
    service.attach_event_fanout(fanout)
    return published


def _tts_events(events: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [
        (event["event"], event["payload"]["message_id"])
        for event in events
        if event["event"].startswith("voice.mobile_tts_")
    ]


def _relayed_pcm(events: list[dict[str, Any]], message_id: str) -> bytes:
    """按 seq 顺序拼出下发给手机的某条回复的 PCM。"""
    chunks = sorted(
        (event["payload"]["seq"], base64.b64decode(event["payload"]["data"]))
        for event in events
        if event["event"] == "voice.mobile_tts_chunk"
        and event["payload"]["message_id"] == message_id
    )
    return b"".join(pcm for _, pcm in chunks)


async def _accept_text(task: DashScopeTask) -> None:
    await task.expect("run-task")
    await task.started()
    await task.expect("continue-task")
    await task.expect("finish-task")


async def test_completed_synthesis_relays_audio_chunks_then_end(
    service, dashscope_server, phone_events
) -> None:
    async def completed(task: DashScopeTask) -> None:
        await _accept_text(task)
        await task.audio_out(FRAME)
        await task.audio_out(FRAME)
        await task.finished()

    dashscope_server.serve(completed)
    reply_id = await character_reply(service, "first", "你好")
    await wait_until(lambda: ("voice.mobile_tts_end", reply_id) in _tts_events(phone_events))

    relayed = [
        event for event in phone_events if event["event"].startswith("voice.mobile_tts_")
    ]
    # 合成结束只发 voice.mobile_tts_end，不再补一个零长度音频块。
    assert [event["event"] for event in relayed] == [
        "voice.mobile_tts_chunk",
        "voice.mobile_tts_chunk",
        "voice.mobile_tts_end",
    ]
    assert [
        (event["payload"]["seq"], base64.b64decode(event["payload"]["data"]))
        for event in relayed[:2]
    ] == [(0, FRAME), (1, FRAME)]


async def test_new_reply_preempts_relay_without_reporting_failure(
    service, dashscope_server, phone_events
) -> None:
    async def held_until_cancelled(task: DashScopeTask) -> None:
        await _accept_text(task)
        await task.audio_out(FRAME)
        cancel = await task.expect("finish-task")
        assert cancel["payload"]["input"]["directive"] == "cancel"
        await task.finished()

    async def completed(task: DashScopeTask) -> None:
        await _accept_text(task)
        await task.audio_out(FRAME)
        await task.audio_out(FRAME)
        await task.finished()

    dashscope_server.serve(held_until_cancelled)
    dashscope_server.serve(completed)

    first = await character_reply(service, "first", "你好")
    await wait_until(lambda: ("voice.mobile_tts_chunk", first) in _tts_events(phone_events))
    second = await character_reply(service, "second", "再说一句")
    await wait_until(lambda: ("voice.mobile_tts_end", second) in _tts_events(phone_events))
    # 旧合成收到取消指令后结束连接
    await wait_until(lambda: dashscope_server.tasks[0].closed)

    assert dashscope_server.tasks[0].finish_directives == [None, "cancel"]
    # 抢占不算失败，已下发的旧分片不撤回，新回复照常完整下发
    assert [
        item for item in _tts_events(phone_events) if item[0] != "voice.mobile_tts_chunk"
    ] == [("voice.mobile_tts_end", second)]
    assert _relayed_pcm(phone_events, first) == FRAME
    assert _relayed_pcm(phone_events, second) == FRAME * 2


async def test_supplier_failure_is_reported_to_phone(
    service, dashscope_server, phone_events
) -> None:
    async def throttled(task: DashScopeTask) -> None:
        await _accept_text(task)
        await task.failed(
            "Throttling.RateQuota", "Requests rate limit exceeded, please try again later."
        )

    dashscope_server.serve(throttled)
    reply_id = await character_reply(service, "first", "你好")
    await wait_until(lambda: ("voice.mobile_tts_failed", reply_id) in _tts_events(phone_events))
    await wait_until(lambda: dashscope_server.tasks[0].closed)

    failures = [
        event["payload"] for event in phone_events if event["event"] == "voice.mobile_tts_failed"
    ]
    assert len(failures) == 1
    assert "Throttling.RateQuota" in failures[0]["error"]
    assert DASHSCOPE_KEY not in failures[0]["error"]
