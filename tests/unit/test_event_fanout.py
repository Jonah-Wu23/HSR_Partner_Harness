from __future__ import annotations

import io
import json

from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.protocol import encode_message
from pair_harness.desktop_backend.router import JsonlWriter


class _RecordingStream(io.StringIO):
    """把每次 write 记录到顺序表，用于断言 stdout 先于订阅者写入。"""

    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    def write(self, s: str) -> int:
        # 仅记录协议正文一次；JsonlWriter 还会单独写一次换行符。
        if s != "\n":
            self._order.append("stdout")
        return super().write(s)


class _BrokenStream:
    """write 即抛 BrokenPipeError，模拟 stdout 传输断开。"""

    def write(self, s: str) -> int:  # type: ignore[override]
        raise BrokenPipeError("broken pipe")

    def flush(self) -> None:
        pass


def _envelope(sequence: int) -> dict:
    return {
        "kind": "event",
        "event": "test.event",
        "stream_id": "local",
        "sequence": sequence,
        "payload": {},
    }


def test_publish_stdout_first_then_subscribers_in_registration_order() -> None:
    order: list[str] = []
    stdout = _RecordingStream(order)
    fanout = EventFanout(JsonlWriter(stdout))
    seen_sub1: list[int] = []
    seen_sub2: list[int] = []

    fanout.subscribe(lambda env: (order.append("sub1"), seen_sub1.append(env["sequence"])))
    fanout.subscribe(lambda env: (order.append("sub2"), seen_sub2.append(env["sequence"])))

    env = _envelope(0)
    fanout.publish(env)

    # stdout 权威先写，再按订阅顺序写订阅者。
    assert order == ["stdout", "sub1", "sub2"]
    assert seen_sub1 == [0]
    assert seen_sub2 == [0]
    assert stdout.getvalue().splitlines() == [encode_message(env)]


def test_subscription_can_be_unsubscribed() -> None:
    out = io.StringIO()
    fanout = EventFanout(JsonlWriter(out))
    received: list[int] = []
    sub = fanout.subscribe(lambda env: received.append(env["sequence"]))

    fanout.publish(_envelope(0))
    assert received == [0]

    sub.unsubscribe()
    sub.unsubscribe()  # 幂等
    fanout.publish(_envelope(1))
    assert received == [0]


def test_stdout_broken_pipe_semantics_preserved() -> None:
    callback_called = False

    def on_broken_pipe() -> None:
        nonlocal callback_called
        callback_called = True

    writer = JsonlWriter(_BrokenStream(), on_broken_pipe=on_broken_pipe)
    fanout = EventFanout(writer)
    received: list[int] = []

    fanout.subscribe(lambda env: received.append(env["sequence"]))

    # stdout 断开时 fanout 不拦截/不改写：BrokenPipe 由 JsonlWriter 承担，publish 不向上抛。
    fanout.publish(_envelope(0))

    assert writer.closed is True
    assert callback_called is True
    assert received == [0]  # 订阅者照常收到


async def test_remote_only_event_skips_stdout_and_global_sequence(tmp_path) -> None:
    """remote-only 事件只发远程订阅者，不带 sequence，桌面事件流的序号不留缺口。"""
    stdout = io.StringIO()
    fanout = EventFanout(JsonlWriter(stdout))
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=fanout.publish,
    )
    try:
        service.attach_event_fanout(fanout)
        remote: list[dict] = []
        fanout.subscribe(remote.append)
        stdout.seek(0)
        stdout.truncate()
        before = service.emitter.next_sequence

        service._publish_remote_only("voice.mobile_tts_chunk", {"seq": 0})
        service.emitter.emit("test.event", {})

        desktop = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert [(e["event"], e["sequence"]) for e in desktop] == [("test.event", before)]
        assert remote[0] == {
            "kind": "event",
            "event": "voice.mobile_tts_chunk",
            "stream_id": service.emitter.stream_id,
            "payload": {"seq": 0},
        }
        assert (remote[1]["event"], remote[1]["sequence"]) == ("test.event", before)
    finally:
        await service.shutdown()