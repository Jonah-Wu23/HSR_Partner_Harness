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
import threading
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
        partial_hold: asyncio.Event | None = None,
    ) -> None:
        self.partials = partials or []
        self.final = final
        self.received_audio: list[list[bytes]] = []
        self._blocks = blocks
        self._on_blocks = on_blocks
        self._partial_hold = partial_hold

    async def stream_transcribe(self, audio_stream: AsyncIterator[bytes]) -> AsyncIterator[AsrEvent]:
        audio: list[bytes] = []
        async for chunk in audio_stream:
            audio.append(chunk)
            if self._on_blocks is not None and len(audio) >= self._blocks:
                self._on_blocks.set()
        self.received_audio.append(audio)
        for text in self.partials:
            yield AsrEvent(type="partial", text=text)
        if self._partial_hold is not None:
            await self._partial_hold.wait()
        if self.final:
            yield AsrEvent(type="final", text=self.final)


class FakeSynthesizer:
    """产出若干非 final 块后（可选 hold 阻塞）收尾的假 TTS。

    ``holds_by_message`` 按 message_id 指定阻塞点，供 skip 测试在
    第二句播放中途做确定性断言；缺省回退到共用的 ``hold``。
    """

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
    """V0.2 M2-4：记录写入块与 stop 次数，start/close 为空操作。"""

    def __init__(self) -> None:
        self.played: list[bytes] = []
        self.stopped = 0

    def play_blocking(self, pcm: bytes) -> None:
        self.played.append(pcm)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        pass


class DrainPlayer(FakePlayer):
    """等待真实输出设备排空后再允许播放状态收尾。"""

    def __init__(self, drain: threading.Event) -> None:
        super().__init__()
        self._drain = drain

    def wait_until_idle(self) -> None:
        self._drain.wait(timeout=2.0)


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
    player: FakePlayer | None = None,
    on_text_input: Any = None,
) -> tuple[VoiceRuntime, SimpleNamespace]:
    recognizer = recognizer or FakeRecognizer()
    synthesizer = synthesizer or FakeSynthesizer()
    queue = queue or SpeechQueue()
    capture = FakeCapture()
    player = player or FakePlayer()
    orch = FakeOrchestrator()
    states: list[str] = []
    partials_seen: list[str] = []
    errors: list[str] = []
    tts_states: list[str] = []
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
        on_tts_state=tts_states.append,
        on_text_input=on_text_input,
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
        vad=vad,
        tts_states=tts_states,
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


async def test_shutdown_closes_capture_and_playback_task() -> None:
    runtime, ctx = make_runtime(vad=FakeVad({}))
    await runtime.start_listening()
    runtime.start_playback()

    await runtime.shutdown()

    assert ctx.capture.entered == 1
    assert ctx.capture.exited == 1
    assert runtime._capture_task is None
    assert runtime._vad_task is None
    assert runtime._playback_task is None
    assert ctx.states[-1] == "idle"


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


async def test_push_to_talk_works_when_vad_is_disabled() -> None:
    blocks_in = asyncio.Event()
    runtime, ctx = make_runtime(
        vad=FakeVad({}),
        recognizer=FakeRecognizer(
            final="关闭 VAD 也能识别。", blocks=1, on_blocks=blocks_in
        ),
    )
    await runtime.start_listening(vad_enabled=False)
    try:
        await runtime.push_to_talk_start(target="character")
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: blocks_in.is_set())
        await runtime.push_to_talk_stop()
        await wait_until(lambda: len(ctx.orch.character_inputs) == 1)
        assert ctx.orch.character_inputs == [("conv-1", "关闭 VAD 也能识别。")]
        assert ctx.vad.received == []
    finally:
        await runtime.stop_listening()


async def test_push_to_talk_stop_does_not_wait_for_model_turn() -> None:
    blocks_in = asyncio.Event()
    commit_started = asyncio.Event()
    commit_finished = asyncio.Event()
    release_commit = asyncio.Event()

    async def on_text_input(text: str, target: str) -> None:
        assert (text, target) == ("后台提交也不阻塞停止聆听。", "character")
        commit_started.set()
        await release_commit.wait()
        commit_finished.set()

    runtime, ctx = make_runtime(
        vad=FakeVad({}),
        recognizer=FakeRecognizer(
            final="后台提交也不阻塞停止聆听。", blocks=1, on_blocks=blocks_in
        ),
        on_text_input=on_text_input,
    )
    await runtime.start_listening(vad_enabled=False)
    try:
        await runtime.push_to_talk_start(target="character")
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: blocks_in.is_set())
        await asyncio.wait_for(runtime.push_to_talk_stop(), timeout=0.5)
        await wait_until(lambda: commit_started.is_set())
        assert not commit_finished.is_set()
        release_commit.set()
        await wait_until(lambda: commit_finished.is_set())
    finally:
        release_commit.set()
        await runtime.shutdown()


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
    runtime.set_assistant_voice_enabled(True)
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
    pair = load_pair_config(PAIR_ID)
    assert [(r.voice_id, r.text) for r in requests] == [
        (pair.character.voice_id, "你好，白厄。"),
        (pair.assistant.voice_id, "好的。"),
    ]


def test_assistant_voice_is_disabled_by_default_until_enabled() -> None:
    runtime, ctx = make_runtime(vad=None)
    assistant = Message(
        conversation_id="conv-1",
        pair_id=PAIR_ID,
        source=MessageSource.ASSISTANT,
        kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
        text="我来处理这件事。",
    )

    runtime.on_message(assistant)
    assert ctx.queue.pop_next() is None

    runtime.set_assistant_voice_enabled(True)
    runtime.on_message(assistant)
    request = ctx.queue.pop_next()
    assert request is not None
    assert request.voice_id == load_pair_config(PAIR_ID).assistant.voice_id
    assert request.text == assistant.text


def test_on_message_filters_ellipsis_and_punctuation_only_text() -> None:
    """V0.2 问题 2：省略号/纯标点降级文本不创建可朗读请求。"""
    runtime, ctx = make_runtime(vad=None)

    def msg(text: str) -> Message:
        return Message(
            conversation_id="conv-1",
            pair_id=PAIR_ID,
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text=text,
        )

    runtime.on_message(msg("……"))
    runtime.on_message(msg("。。。"))
    runtime.on_message(msg("---"))
    runtime.on_message(msg(""))
    assert ctx.queue.pop_next() is None

    runtime.on_message(msg("系统就绪。"))
    assert ctx.queue.pop_next() is not None
    assert ctx.queue.pop_next() is None


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


# ---------------------------------------------------------------- V0.2 M2-4：连续播放与语音状态机


async def test_tts_state_follows_playback_lifecycle() -> None:
    """M2-4：tts 状态机——synthesizing → playing、结束回 idle。"""
    runtime, ctx = make_runtime(vad=None, synthesizer=FakeSynthesizer(chunks=1))
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        ctx.queue.enqueue(SpeechRequest(text="你好", voice_id="demo", message_id="m1"))
        await wait_until(lambda: ctx.tts_states and ctx.tts_states[-1] == "playing")
        await wait_until(lambda: ctx.tts_states and ctx.tts_states[-1] == "idle")
        # V0.2 M4：出队合成先置 synthesizing，首个 PCM 块写入播放器才置 playing
        assert ctx.tts_states == ["synthesizing", "playing", "idle"]
        assert ctx.queue.pending == 0
    finally:
        playback.cancel()
        try:
            await playback
        except asyncio.CancelledError:
            pass


async def test_tts_playing_waits_for_audio_output_to_drain() -> None:
    """合成完成时仍有设备缓冲，tts 保持 playing 直到实际输出排空。"""
    drain = threading.Event()
    runtime, ctx = make_runtime(
        vad=None,
        synthesizer=FakeSynthesizer(chunks=1),
        player=DrainPlayer(drain),
    )
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        ctx.queue.enqueue(SpeechRequest(text="你好", voice_id="demo", message_id="m1"))
        await wait_until(lambda: ctx.tts_states and ctx.tts_states[-1] == "playing")
        await asyncio.sleep(0.05)
        assert ctx.tts_states[-1] == "playing"
        drain.set()
        await wait_until(lambda: ctx.tts_states and ctx.tts_states[-1] == "idle")
    finally:
        drain.set()
        playback.cancel()
        try:
            await playback
        except asyncio.CancelledError:
            pass


async def test_tts_failure_reports_failed_then_recovers() -> None:
    """V0.2 M4：合成失败 → tts 置 failed、待播队列清空并保持失败态；
    下一条新消息入队后 synthesizing → playing 恢复。"""
    class FlakySynthesizer:
        def __init__(self) -> None:
            self.fail_next = True

        async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("合成服务无响应")
            yield AudioChunk(pcm=BLOCK, final=False)
            yield AudioChunk(pcm=b"", final=True)

    runtime, ctx = make_runtime(vad=None, synthesizer=FlakySynthesizer())
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        ctx.queue.enqueue(SpeechRequest(text="第一句", voice_id="demo", message_id="m1"))
        # 失败：tts 置 failed、错误上报；待播队列被清空，不再自动消费下一句
        await wait_until(lambda: ctx.tts_states and ctx.tts_states[-1] == "failed")
        assert ctx.errors and "合成失败" in ctx.errors[0]
        await asyncio.sleep(0.05)
        assert ctx.tts_states[-1] == "failed"  # 失败态保持可观测（不回落 idle）
        assert ctx.queue.pending == 0

        # 新消息入队：synthesizing → playing → idle 恢复。
        # playing 是瞬态（播放即结束），以终态 idle 为准、列表留痕断言。
        ctx.queue.enqueue(SpeechRequest(text="第二句", voice_id="demo", message_id="m2"))
        await wait_until(lambda: ctx.tts_states and ctx.tts_states[-1] == "idle")
        assert ctx.tts_states[-3:] == ["synthesizing", "playing", "idle"]
        assert not ctx.queue.playing
    finally:
        playback.cancel()
        try:
            await playback
        except asyncio.CancelledError:
            pass


async def test_skip_playing_aborts_current_and_continues_next() -> None:
    """M2-4：skip 立即停声并放弃当前句，队列下一句接着播（VAD 不重开）。"""
    hold_m1 = asyncio.Event()
    hold_m2 = asyncio.Event()
    runtime, ctx = make_runtime(
        vad=FakeVad({}),
        synthesizer=FakeSynthesizer(
            chunks=1, holds_by_message={"m1": hold_m1, "m2": hold_m2}
        ),
    )
    await runtime.start_listening()
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        ctx.queue.enqueue(
            SpeechRequest(text="第一句", voice_id="demo", message_id="m1")
        )
        await wait_until(lambda: ctx.queue.playing)
        assert len(ctx.synthesizer.requests) == 1
        played_before = len(ctx.player.played)
        assert played_before >= 1

        ctx.queue.enqueue(
            SpeechRequest(text="第二句", voice_id="demo", message_id="m2")
        )
        runtime.skip_playing()
        assert ctx.tts_states[-1] == "skipping"  # 状态机进入 skipping
        assert ctx.player.stopped == 1  # 立即停声
        assert ctx.queue.pending == 1  # 下一句仍留在队列
        hold_m1.set()  # 释放当前合成，让跳过检查截断本句
        await wait_until(lambda: len(ctx.synthesizer.requests) == 2)  # 接着播第二句
        await wait_until(lambda: len(ctx.player.played) > played_before)
        assert ctx.vad.sessions == 1  # skip 连续播放：不重开 VAD 会话
        assert ctx.tts_states[-1] == "playing"
        assert ctx.queue.pending == 0
        hold_m2.set()
        await wait_until(lambda: ctx.states[-1] == "listening")
    finally:
        hold_m1.set()
        hold_m2.set()
        playback.cancel()
        try:
            await playback
        except asyncio.CancelledError:
            pass
        await runtime.stop_listening()


async def test_skip_playing_with_empty_queue_stops() -> None:
    """M2-4：skip 后队列已空 → 停止播放，tts 回 idle、VAD 重开。"""
    hold_m1 = asyncio.Event()
    runtime, ctx = make_runtime(
        vad=FakeVad({}),
        synthesizer=FakeSynthesizer(chunks=1, holds_by_message={"m1": hold_m1}),
    )
    await runtime.start_listening()
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        ctx.queue.enqueue(
            SpeechRequest(text="唯一一句", voice_id="demo", message_id="m1")
        )
        await wait_until(lambda: ctx.queue.playing)
        runtime.skip_playing()
        assert ctx.tts_states[-1] == "skipping"
        hold_m1.set()
        await wait_until(lambda: not ctx.queue.playing)
        await wait_until(lambda: ctx.states[-1] == "listening")  # VAD 重开
        assert ctx.tts_states[-1] == "idle"
    finally:
        hold_m1.set()
        playback.cancel()
        try:
            await playback
        except asyncio.CancelledError:
            pass
        await runtime.stop_listening()


async def test_skip_playing_when_idle_is_noop() -> None:
    """M2-4：未在播放时 skip 无句可跳，不产生 skipping 事件。"""
    runtime, ctx = make_runtime(vad=FakeVad({}))
    await runtime.start_listening()
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        runtime.skip_playing()
        assert not ctx.queue.playing
        assert ctx.queue.pending == 0
        assert ctx.tts_states == []
    finally:
        playback.cancel()
        try:
            await playback
        except asyncio.CancelledError:
            pass
        await runtime.stop_listening()


def test_stop_speaking_stops_player_and_clears_queue() -> None:
    """M2-4：stop 立即停声（清播放器缓冲）并清空待播队列。"""
    runtime, ctx = make_runtime(vad=None)
    ctx.queue.enqueue(SpeechRequest(text="一", voice_id="demo", message_id="m1"))
    ctx.queue.begin_playback()
    runtime.stop_speaking()
    assert ctx.player.stopped == 1
    assert not ctx.queue.playing
    assert ctx.queue.pending == 0


def test_replay_message_ignores_tts_eligibility() -> None:
    """M2-4：voice.tts_play 重播无视 tts_eligible——用户消息也可朗读。"""
    runtime, ctx = make_runtime(vad=None)
    user = Message(
        conversation_id="conv-1",
        pair_id=PAIR_ID,
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="在吗，白厄。",
    )
    runtime.replay_message(user)
    pair = load_pair_config(PAIR_ID)
    request = ctx.queue.pop_next()
    assert request is not None
    assert request.voice_id == pair.character.voice_id  # 用户消息用角色音色
    assert request.text == "在吗，白厄。"
    # 其他会话的消息不入队
    runtime.replay_message(
        user.model_copy(update={"conversation_id": "conv-other"})
    )
    assert ctx.queue.pop_next() is None


def test_assistant_progress_is_spoken_once_when_final_message_arrives() -> None:
    """工具前的助手阶段性说明先播报，最终消息落库时不重复入队。"""
    runtime, ctx = make_runtime(vad=None)
    runtime.set_assistant_voice_enabled(True)
    runtime.enqueue_assistant_progress("我来读取项目目录。")
    progress = ctx.queue.pop_next()
    assert progress is not None
    assert progress.voice_id == load_pair_config(PAIR_ID).assistant.voice_id

    runtime.on_message(
        Message(
            conversation_id="conv-1",
            pair_id=PAIR_ID,
            source=MessageSource.ASSISTANT,
            kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
            text="我来读取项目目录。",
            message_id="assistant:conv-1:task-1",
        )
    )
    assert ctx.queue.pop_next() is None


def test_replay_message_filters_unreadable_text() -> None:
    """M2-4：重播同样过滤省略号/纯标点降级文本。"""
    runtime, ctx = make_runtime(vad=None)
    for text in ("……", "。。。", ""):
        runtime.replay_message(
            Message(
                conversation_id="conv-1",
                pair_id=PAIR_ID,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=text,
            )
        )
    assert ctx.queue.pop_next() is None


def test_enqueue_text_preview_defaults_to_character_voice() -> None:
    """M2-4：voice.preview 试听文本入队，音色缺省取角色音色。"""
    runtime, ctx = make_runtime(vad=None)
    runtime.enqueue_text("这是一句试听。")
    pair = load_pair_config(PAIR_ID)
    request = ctx.queue.pop_next()
    assert request is not None
    assert request.voice_id == pair.character.voice_id
    assert request.message_id == "preview"
    runtime.enqueue_text("……")  # 不可读文本不入队
    assert ctx.queue.pop_next() is None
