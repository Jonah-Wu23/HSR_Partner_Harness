"""B2.6 VoiceRuntime 单元测试：注入假适配器验证上行/下行协调行为。

覆盖设计文档 §5 的关键行为：
- VAD 完整流：静音期 pre-roll 累积、speech_started 补发、语音块实时转发、
  非空 final 提交为 character 输入；
- TTS 播放中暂停 VAD 喂帧，播放结束重开 VAD 会话后恢复；
- PTT 按下先停 TTS，松开后非空提交（target 可切 assistant）；
- 空 final / false_trigger 不提交，回显清空；
- on_message 按来源选 voice_id（character/assistant），user/tool/system 不入队；
- VAD 不可用时提示并退回 PTT 通路。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from pair_harness.config.pairs import load_pair_config
from pair_harness.core.audio import SpeechQueue
from pair_harness.core.contracts import (
    AsrEvent,
    AudioChunk,
    Message,
    MessageKind,
    MessageSource,
    SpeechRequest,
    VadEvent,
)
from pair_harness.core.voice_runtime import VoiceRuntime

PAIR_ID = "phainon_ancient_machine"
BLOCK = b"\x00" * 640  # 20 ms @ 16 kHz mono 16bit


async def wait_until(cond: Any, timeout: float = 3.0) -> None:
    """轮询等待条件成立（测试用同步条件）。"""

    async def _wait() -> None:
        while not cond():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait(), timeout)


# ---------------------------------------------------------------- 假适配器


class FakeCapture:
    """麦克风假实现：测试向 feed() 推块；cancel 时任务结束即可。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> "FakeCapture":
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
    """按收到块数触发事件的假 VAD：triggers 映射 块数 -> 事件类型。"""

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
    """消费完整音频流后按序产出 partials 与 final 的假 ASR。

    ``blocks``/``on_blocks``：收到第 ``blocks`` 块音频时置事件，
    供测试确定性等待“语音已进入识别器”再收尾（队列被即时消费，
    用 qsize 等待是竞态）。
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
    """产出若干非 final 块后（可选 hold 阻塞）收尾的假 TTS。"""

    def __init__(self, hold: asyncio.Event | None = None, chunks: int = 2) -> None:
        self.hold = hold
        self.chunks = chunks
        self.requests: list[SpeechRequest] = []

    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        self.requests.append(request)
        for _ in range(self.chunks):
            yield AudioChunk(pcm=BLOCK, final=False)
        if self.hold is not None:
            await self.hold.wait()
        yield AudioChunk(pcm=b"", final=True)


class FakePlayer:
    def __init__(self) -> None:
        self.played: list[bytes] = []

    def play_blocking(self, pcm: bytes) -> None:
        self.played.append(pcm)


class FakeOrchestrator:
    def __init__(self) -> None:
        self.character_inputs: list[tuple[str, str]] = []
        self.direct_inputs: list[tuple[str, str]] = []

    async def handle_character_input(self, *, conversation_id: str, text: str) -> None:
        self.character_inputs.append((conversation_id, text))

    async def handle_direct_input(self, *, conversation_id: str, text: str) -> None:
        self.direct_inputs.append((conversation_id, text))


# ---------------------------------------------------------------- 装配


def make_runtime(
    *,
    vad: FakeVad | None,
    recognizer: FakeRecognizer | None = None,
    synthesizer: FakeSynthesizer | None = None,
    queue: SpeechQueue | None = None,
) -> tuple[VoiceRuntime, SimpleNamespace]:
    recognizer = recognizer or FakeRecognizer()
    synthesizer = synthesizer or FakeSynthesizer()
    queue = queue or SpeechQueue()
    capture = FakeCapture()
    player = FakePlayer()
    orch = FakeOrchestrator()
    states: list[str] = []
    partials_seen: list[str] = []
    errors: list[str] = []
    runtime = VoiceRuntime(
        orchestrator=orch,
        recognizer=recognizer,
        synthesizer=synthesizer,
        vad=vad,
        capture_factory=lambda: capture,
        player=player,
        queue=queue,
        pair_config=load_pair_config(PAIR_ID),
        conversation_id="conv-1",
        on_vad_state=states.append,
        on_asr_partial=partials_seen.append,
        on_error=errors.append,
    )
    return runtime, SimpleNamespace(
        runtime=runtime,
        capture=capture,
        recognizer=recognizer,
        synthesizer=synthesizer,
        player=player,
        orch=orch,
        queue=queue,
        states=states,
        partials_seen=partials_seen,
        errors=errors,
    )


# ---------------------------------------------------------------- 用例


async def test_vad_full_flow_commits_character_input() -> None:
    vad = FakeVad({3: "speech_started", 5: "speech_ended"})
    runtime, ctx = make_runtime(
        vad=vad, recognizer=FakeRecognizer(partials=["你好"], final="你好，白厄。")
    )
    await runtime.start_listening()
    try:
        # 3 块静音 → speech_started：这 3 块进 pre-roll，补发给 ASR
        for _ in range(3):
            ctx.capture.feed(BLOCK)
        await wait_until(lambda: ctx.states and ctx.states[-1] == "speech_started")
        # 2 块语音 → speech_ended：实时转发给 ASR
        for _ in range(2):
            ctx.capture.feed(BLOCK)
        await wait_until(lambda: len(ctx.orch.character_inputs) == 1)
        # 收尾
        await wait_until(lambda: ctx.states and ctx.states[-1] == "speech_ended")
    finally:
        await runtime.stop_listening()

    assert ctx.recognizer.received_audio == [[BLOCK] * 5]  # 3 pre-roll + 2 语音
    assert ctx.orch.character_inputs == [("conv-1", "你好，白厄。")]
    assert ctx.partials_seen == ["你好", ""]  # partial 回显 + final 提交后清空
    assert ctx.states[:3] == ["listening", "speech_started", "speech_ended"]
    assert ctx.states[-1] == "idle"  # stop_listening


async def test_playback_pauses_vad_feeding_and_resumes() -> None:
    vad = FakeVad({})  # 不触发事件，纯验证喂帧通路
    hold = asyncio.Event()
    runtime, ctx = make_runtime(vad=vad, synthesizer=FakeSynthesizer(hold=hold))
    await runtime.start_listening()
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        # 播放前：正常喂 VAD
        for _ in range(3):
            ctx.capture.feed(BLOCK)
        await wait_until(lambda: len(vad.received) == 3)

        ctx.queue.enqueue(
            SpeechRequest(text="测试", voice_id="demo-phainon", message_id="m1")
        )
        await wait_until(lambda: ctx.queue.playing)
        assert ctx.states[-1] == "playing"

        # 播放中：采集块被丢弃，VAD 收不到
        n_before = len(vad.received)
        for _ in range(2):
            ctx.capture.feed(BLOCK)
        await asyncio.sleep(0.05)
        assert len(vad.received) == n_before

        # 播放结束：重开 VAD 会话，继续喂帧
        hold.set()
        await wait_until(lambda: not ctx.queue.playing)
        await wait_until(lambda: ctx.states[-1] == "listening")
        for _ in range(3):
            ctx.capture.feed(BLOCK)
        await wait_until(lambda: len(vad.received) == n_before + 3)
        assert ctx.player.played  # 确有 PCM 被播放
        assert vad.sessions == 2  # 播放结束后重开过一次 detect 会话
    finally:
        hold.set()
        await wait_until(lambda: ctx.states[-1] == "listening")
        playback.cancel()
        try:
            await playback
        except asyncio.CancelledError:
            pass
        await runtime.stop_listening()


async def test_push_to_talk_stops_playback_then_commits() -> None:
    hold = asyncio.Event()
    queue = SpeechQueue()
    blocks_in = asyncio.Event()
    runtime, ctx = make_runtime(
        vad=FakeVad({}),
        queue=queue,
        synthesizer=FakeSynthesizer(hold=hold),
        recognizer=FakeRecognizer(
            partials=["在"], final="在的。", blocks=2, on_blocks=blocks_in
        ),
    )
    await runtime.start_listening()
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        queue.enqueue(
            SpeechRequest(text="正在播放", voice_id="demo-phainon", message_id="m1")
        )
        await wait_until(lambda: queue.playing)
        assert len(ctx.synthesizer.requests) == 1  # 合成已开始

        # 按下说话：立即停 TTS 并清空队列
        await runtime.push_to_talk_start(target="character")
        assert queue.playing is False
        assert queue.pending == 0

        ctx.capture.feed(BLOCK)
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: blocks_in.is_set())  # 两块都已进入识别器
        await runtime.push_to_talk_stop()
        await wait_until(lambda: len(ctx.orch.character_inputs) == 1)
        assert ctx.orch.character_inputs == [("conv-1", "在的。")]
        assert ctx.recognizer.received_audio == [[BLOCK, BLOCK]]  # 无 pre-roll
    finally:
        hold.set()
        await wait_until(lambda: ctx.states[-1] == "listening")
        playback.cancel()
        try:
            await playback
        except asyncio.CancelledError:
            pass
        await runtime.stop_listening()


async def test_empty_final_not_committed() -> None:
    runtime, ctx = make_runtime(vad=FakeVad({1: "speech_started", 2: "speech_ended"}))
    await runtime.start_listening()
    try:
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: ctx.states and ctx.states[-1] == "speech_started")
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: ctx.states and ctx.states[-1] == "speech_ended")
        await wait_until(lambda: ctx.partials_seen and ctx.partials_seen[-1] == "")
        assert ctx.orch.character_inputs == []  # 空转写不提交
        assert ctx.partials_seen == [""]  # 回显被清空
    finally:
        await runtime.stop_listening()


async def test_false_trigger_not_committed() -> None:
    runtime, ctx = make_runtime(
        vad=FakeVad({1: "speech_started", 2: "false_trigger"}),
        recognizer=FakeRecognizer(partials=["嗯"], final="嗯"),
    )
    await runtime.start_listening()
    try:
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: ctx.states and ctx.states[-1] == "speech_started")
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: ctx.states and ctx.states[-1] == "false_trigger")
        await wait_until(lambda: ctx.partials_seen and ctx.partials_seen[-1] == "")
        assert ctx.orch.character_inputs == []  # 误触发即使有 final 也不提交
        assert ctx.partials_seen == ["嗯", ""]
    finally:
        await runtime.stop_listening()


def test_on_message_selects_voice_id_by_source_and_filters() -> None:
    runtime, ctx = make_runtime(vad=None)

    def msg(source: MessageSource, kind: MessageKind, text: str) -> Message:
        return Message(
            conversation_id="conv-1",
            pair_id=PAIR_ID,
            source=source,
            kind=kind,
            text=text,
        )

    runtime.on_message(
        msg(MessageSource.CHARACTER, MessageKind.CHARACTER_SPEECH, "你好，白厄。")
    )
    # 助手消息含围栏代码块：只朗读自然语言段落
    runtime.on_message(
        msg(
            MessageSource.ASSISTANT,
            MessageKind.ASSISTANT_NATURAL_LANGUAGE,
            "好的。\n```python\nx = 1\n```",
        )
    )
    # 非 TTS 消息一律不入队
    runtime.on_message(msg(MessageSource.USER, MessageKind.USER_TEXT, "在吗"))
    runtime.on_message(
        msg(MessageSource.TOOL, MessageKind.TOOL_RECORD, "已执行命令")
    )
    runtime.on_message(
        msg(MessageSource.SYSTEM, MessageKind.SYSTEM_STATUS, "任务完成")
    )

    requests = [ctx.queue.pop_next(), ctx.queue.pop_next()]
    assert ctx.queue.pop_next() is None
    assert [(r.voice_id, r.text) for r in requests] == [
        ("demo-phainon", "你好，白厄。"),
        ("demo-ancient-machine", "好的。"),
    ]


async def test_vad_unavailable_falls_back_to_ptt() -> None:
    blocks_in = asyncio.Event()
    runtime, ctx = make_runtime(
        vad=None,
        recognizer=FakeRecognizer(
            partials=["好"], final="好的。", blocks=2, on_blocks=blocks_in
        ),
    )
    await runtime.start_listening()
    try:
        assert ctx.states == ["idle"]
        assert ctx.errors == ["VAD 不可用，已切换为按键说话"]

        await runtime.push_to_talk_start(target="assistant")
        assert ctx.states[-1] == "speech_started"
        ctx.capture.feed(BLOCK)
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: blocks_in.is_set())
        await runtime.push_to_talk_stop()
        await wait_until(lambda: len(ctx.orch.direct_inputs) == 1)
        assert ctx.orch.direct_inputs == [("conv-1", "好的。")]
        assert ctx.orch.character_inputs == []
        assert ctx.recognizer.received_audio == [[BLOCK, BLOCK]]
    finally:
        await runtime.stop_listening()
