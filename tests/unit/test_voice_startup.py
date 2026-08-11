from __future__ import annotations

import asyncio

from pair_harness.ui.app import _schedule_voice_runtime_start


class StubVoiceRuntime:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.calls: list[str] = []

    async def start_listening(self) -> None:
        assert asyncio.get_running_loop() is self.loop
        self.calls.append("listening")

    def start_playback(self) -> None:
        assert asyncio.get_running_loop() is self.loop
        self.calls.append("playback")


def test_voice_start_can_be_scheduled_before_event_loop_runs() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runtime = StubVoiceRuntime(loop)
    try:
        task = _schedule_voice_runtime_start(runtime)  # type: ignore[arg-type]
        assert runtime.calls == []
        loop.run_until_complete(task)
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    assert runtime.calls == ["listening", "playback"]
