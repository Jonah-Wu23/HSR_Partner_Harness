from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from pair_harness.core.audio import SpeechQueue
from pair_harness.core.contracts import AsrEvent, AudioChunk, SpeechRequest, VadEvent
from pair_harness.core.voice_runtime import VoiceRuntime
from tests.service_helpers import call, wait_until

BLOCK = b"\x00" * 640  # 20 ms @ 16 kHz 单声道 int16


class FakeCapture:
    """麦克风替身：用例经 feed() 推入音频块，close_stream() 结束采集。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> FakeCapture:
        self.entered += 1
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.exited += 1

    def feed(self, block: bytes) -> None:
        self._queue.put_nowait(block)

    def close_stream(self) -> None:
        self._queue.put_nowait(None)

    async def chunks(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item


class FakeVad:
    """按累计收到的块数触发事件：triggers 映射 块数 -> 事件类型。"""

    def __init__(self, triggers: dict[int, str]) -> None:
        self.triggers = triggers
        self.received: list[bytes] = []
        self.sessions = 0

    async def detect(self, pcm_stream: AsyncIterator[bytes]) -> AsyncIterator[VadEvent]:
        self.sessions += 1
        count = 0
        async for chunk in pcm_stream:
            self.received.append(chunk)
            count += 1
            event_type = self.triggers.get(count)
            if event_type is not None:
                yield VadEvent(type=event_type)


class FakeRecognizer:
    """消费完整段音频后按序产出 partials 与 final。

    收到第 ``blocks`` 块时置 ``on_blocks``，供用例确认语音已进入识别器再收尾。
    """

    def __init__(
        self,
        partials: list[str] | None = None,
        final: str = "",
        *,
        blocks: int = 0,
        on_blocks: asyncio.Event | None = None,
    ) -> None:
        self.partials = partials or []
        self.final = final
        self.received_audio: list[list[bytes]] = []
        self._blocks = blocks
        self._on_blocks = on_blocks

    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[AsrEvent]:
        audio: list[bytes] = []
        async for chunk in audio_stream:
            audio.append(chunk)
            if self._on_blocks is not None and len(audio) >= self._blocks:
                self._on_blocks.set()
        self.received_audio.append(audio)
        for text in self.partials:
            yield AsrEvent(type="partial", text=text)
        if self.final:
            yield AsrEvent(type="final", text=self.final)


class FakeSynthesizer:
    """产出若干 PCM 块后收尾；``holds_by_message`` 或 ``hold`` 让收尾前停住。"""

    def __init__(
        self,
        hold: asyncio.Event | None = None,
        chunks: int = 2,
        holds_by_message: dict[str, asyncio.Event] | None = None,
    ) -> None:
        self.hold = hold
        self.chunks = chunks
        self.holds_by_message = holds_by_message or {}
        self.requests: list[SpeechRequest] = []

    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        self.requests.append(request)
        for _ in range(self.chunks):
            yield AudioChunk(pcm=BLOCK, final=False)
        gate = self.holds_by_message.get(request.message_id, self.hold)
        if gate is not None:
            await gate.wait()
        yield AudioChunk(pcm=b"", final=True)


class FakePlayer:
    """扬声器替身：记录写入块、stop 与 close 次数。"""

    def __init__(self) -> None:
        self.played: list[bytes] = []
        self.stopped = 0
        self.closed = 0

    def play_blocking(self, pcm: bytes) -> None:
        self.played.append(pcm)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped += 1

    def wait_until_idle(self) -> None:
        pass

    def close(self) -> None:
        self.closed += 1


async def unexpected_text_input(text: str, target: str) -> None:
    raise AssertionError(f"本用例不应提交语音文本：{text}（{target}）")


def attach_desktop_runtime(
    service,
    *,
    queue: SpeechQueue | None = None,
    player: FakePlayer | None = None,
    interrupted: list[tuple[str, str | None, str]] | None = None,
) -> VoiceRuntime:
    """给桌面服务挂上真实 VoiceRuntime，音频设备与 DashScope 由替身承担。

    语音归属当前聊天与搭档；不启动播放循环，角色回复停在待播队列里。
    """
    events = interrupted if interrupted is not None else []
    runtime = VoiceRuntime(
        on_text_input=unexpected_text_input,
        recognizer=FakeRecognizer(),
        synthesizer=FakeSynthesizer(),
        vad=None,
        capture_factory=FakeCapture,
        player=player or FakePlayer(),
        queue=queue or SpeechQueue(),
        pair_config=service.pair_config,
        conversation_id=service.current_conversation_id,
        on_interrupted=lambda *event: events.append(event),
    )
    service.attach_voice_runtime(runtime)
    return runtime


async def character_reply(service, request_id: str, text: str) -> str:
    """经 chat.submit 发给角色，等回合完成，返回演示角色回复的 message_id。"""
    submitted = await call(service, request_id, "chat.submit", text=text, target="character")
    turn_id = submitted["turn_id"]
    await wait_until(
        lambda: any(
            payload["turn"]["turn_id"] == turn_id and payload["turn"]["status"] == "completed"
            for payload in service.event_log.payloads("turn.status_changed")
        ),
        message=f"回合 {turn_id} 没有完成",
    )
    replies = [
        payload["message"]["message_id"]
        for payload in service.event_log.payloads("message.created")
        if payload["message"]["source"] == "character"
    ]
    return replies[-1]
