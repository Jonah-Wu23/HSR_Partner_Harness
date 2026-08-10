from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator

from pair_harness.core.contracts import AsrEvent, AudioChunk, SpeechRequest, VadEvent
from pair_harness.core.ports import SpeechRecognizer, SpeechSynthesizer, VoiceActivityDetector


class DemoSpeechRecognizer(SpeechRecognizer):
    """接收注入文本，不依赖真实麦克风。"""

    def __init__(self, *, partial: str = "", final: str = "") -> None:
        self.partial = partial
        self.final = final

    async def stream_transcribe(self, audio_stream: AsyncIterable[bytes]) -> AsyncIterator[AsrEvent]:
        async for _chunk in audio_stream:
            pass
        if self.partial:
            yield AsrEvent(type="partial", text=self.partial)
        yield AsrEvent(type="final", text=self.final)


class DemoSpeechSynthesizer(SpeechSynthesizer):
    """生成固定长度的测试音频，不访问输出设备。"""

    def __init__(self, *, chunks: int = 1, bytes_per_chunk: int = 640) -> None:
        self.chunks = chunks
        self.bytes_per_chunk = bytes_per_chunk

    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        del request
        for _ in range(self.chunks):
            yield AudioChunk(
                pcm=b"\x00" * self.bytes_per_chunk,
                sample_rate=16_000,
                channels=1,
            )


class DemoVoiceActivityDetector(VoiceActivityDetector):
    """按注入的状态序列输出 VAD 事件，用于验证状态机。"""

    def __init__(self, *, events: tuple[VadEvent, ...] = ()) -> None:
        self.events = events

    async def detect(self, pcm_stream: AsyncIterable[bytes]) -> AsyncIterator[VadEvent]:
        async for _chunk in pcm_stream:
            pass
        for event in self.events:
            yield event
