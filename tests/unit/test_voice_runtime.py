from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from pair_harness.config.pairs import load_pair_config
from pair_harness.core.audio import SpeechQueue
from pair_harness.core.contracts import (
    AudioChunk,
    Message,
    MessageKind,
    MessageSource,
    SpeechRequest,
)
from pair_harness.core.voice_runtime import VoiceRuntime
from tests.service_helpers import wait_until
from tests.voice_helpers import (
    BLOCK,
    FakeCapture,
    FakePlayer,
    FakeRecognizer,
    FakeSynthesizer,
    FakeVad,
)

PAIR_ID = "phainon_ancient_machine"


class DrainPlayer(FakePlayer):
    """等待真实输出设备排空后再允许播放状态收尾。"""

    def __init__(self, drain: threading.Event) -> None:
        super().__init__()
        self._drain = drain

    def wait_until_idle(self) -> None:
        self._drain.wait(timeout=2.0)


class TextInputRecorder:
    """记录 VoiceRuntime 经 on_text_input 提交给桌面 Turn 链的文本。"""

    def __init__(self) -> None:
        self.character_inputs: list[str] = []
        self.direct_inputs: list[str] = []

    async def on_text_input(self, text: str, target: str) -> None:
        if target == "assistant":
            self.direct_inputs.append(text)
        else:
            self.character_inputs.append(text)


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
    orch = TextInputRecorder()
    states: list[str] = []
    partials_seen: list[str] = []
    errors: list[str] = []
    tts_states: list[str] = []
    interrupted: list[tuple[str, str | None, str]] = []
    runtime = VoiceRuntime(
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
        on_interrupted=lambda *event: interrupted.append(event),
        on_text_input=on_text_input or orch.on_text_input,
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
        interrupted=interrupted,
    )


async def _stop_playback(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------- 上行


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
    assert ctx.orch.character_inputs == ["你好，白厄。"]
    assert ctx.partials_seen == ["你好", ""]  # partial 回显 + final 提交后清空
    assert ctx.states[:3] == ["listening", "speech_started", "speech_ended"]
    assert ctx.states[-1] == "idle"  # stop_listening


async def test_shutdown_closes_capture_player_and_background_tasks() -> None:
    runtime, ctx = make_runtime(vad=FakeVad({}))
    await runtime.start_listening()
    runtime.start_playback()

    await runtime.shutdown()

    assert (ctx.capture.entered, ctx.capture.exited) == (1, 1)
    assert ctx.player.closed == 1
    assert ctx.states[-1] == "idle"
    # 采集、VAD 与播放循环都已结束，事件循环里只剩当前用例
    assert asyncio.all_tasks() == {asyncio.current_task()}


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
        await _stop_playback(playback)
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
        assert ctx.orch.character_inputs == ["在的。"]
        assert ctx.recognizer.received_audio == [[BLOCK, BLOCK]]  # 无 pre-roll
    finally:
        hold.set()
        # 被打断的播放循环放行合成后重开 VAD 会话。speech_started 可能覆盖
        # 恢复后的 listening，因此以单调递增的 detect 会话数为准。
        await wait_until(lambda: ctx.vad.sessions == 2)
        await _stop_playback(playback)
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
        assert ctx.orch.character_inputs == ["关闭 VAD 也能识别。"]
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


async def test_vad_unavailable_falls_back_to_push_to_talk() -> None:
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
        assert ctx.orch.direct_inputs == ["好的。"]
        assert ctx.orch.character_inputs == []
        assert ctx.recognizer.received_audio == [[BLOCK, BLOCK]]
    finally:
        await runtime.stop_listening()


# ---------------------------------------------------------------- 下行


def test_on_message_plays_character_only_and_filters_assistant_and_others() -> None:
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
    runtime.on_message(
        msg(
            MessageSource.ASSISTANT,
            MessageKind.ASSISTANT_NATURAL_LANGUAGE,
            "好的。\n```python\nx = 1\n```",
        )
    )
    runtime.on_message(msg(MessageSource.USER, MessageKind.USER_TEXT, "在吗"))
    runtime.on_message(
        msg(MessageSource.TOOL, MessageKind.TOOL_RECORD, "已执行命令")
    )
    runtime.on_message(
        msg(MessageSource.SYSTEM, MessageKind.SYSTEM_STATUS, "任务完成")
    )

    request = ctx.queue.pop_next()
    assert request is not None
    pair = load_pair_config(PAIR_ID)
    assert (request.voice_id, request.text) == (pair.character.voice_id, "你好，白厄。")
    assert ctx.queue.pop_next() is None


def test_on_message_skips_punctuation_only_text() -> None:
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
        await _stop_playback(playback)


async def test_tts_failure_reports_failed_then_recovers() -> None:
    """合成失败时 tts 置 failed 并清空待播队列，下一条消息按 synthesizing → playing → idle 恢复。"""

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
        assert ctx.tts_states[-1] == "failed"  # 失败态保持，不回落 idle
        assert ctx.queue.pending == 0

        # 首个 PCM 块写入播放器才置 playing，播完回 idle
        ctx.queue.enqueue(SpeechRequest(text="第二句", voice_id="demo", message_id="m2"))
        await wait_until(lambda: ctx.tts_states and ctx.tts_states[-1] == "idle")
        assert ctx.tts_states[-3:] == ["synthesizing", "playing", "idle"]
        assert not ctx.queue.playing
    finally:
        await _stop_playback(playback)


async def test_skip_playing_aborts_current_and_continues_next() -> None:
    """跳过立即停声并放弃当前句，队列下一句接着播，不重开 VAD，也不算抢占。"""
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
        epoch_before = ctx.queue.epoch
        await runtime.skip_playing_async()
        assert ctx.tts_states[-1] == "skipping"
        assert ctx.player.stopped == 1  # 立即停声
        assert ctx.queue.epoch == epoch_before + 1  # 当前句的迟到 PCM 作废
        assert ctx.queue.pending == 1  # 下一句仍留在队列
        assert ctx.interrupted == []  # 跳过是显式动作，不发抢占事件
        hold_m1.set()  # 释放当前合成，让跳过检查截断本句
        await wait_until(lambda: len(ctx.synthesizer.requests) == 2)  # 接着播第二句
        await wait_until(lambda: len(ctx.player.played) > played_before)
        assert ctx.vad.sessions == 1  # 连续播放，不重开 VAD 会话
        assert ctx.tts_states[-1] == "playing"
        assert ctx.queue.pending == 0
        hold_m2.set()
        await wait_until(lambda: ctx.states[-1] == "listening")
    finally:
        hold_m1.set()
        hold_m2.set()
        await _stop_playback(playback)
        await runtime.stop_listening()


async def test_skip_playing_with_empty_queue_stops() -> None:
    """跳过后队列已空则停止播放，tts 回 idle、VAD 重开。"""
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
        await runtime.skip_playing_async()
        assert ctx.tts_states[-1] == "skipping"
        hold_m1.set()
        await wait_until(lambda: not ctx.queue.playing)
        await wait_until(lambda: ctx.states[-1] == "listening")  # VAD 重开
        assert ctx.tts_states[-1] == "idle"
    finally:
        hold_m1.set()
        await _stop_playback(playback)
        await runtime.stop_listening()


async def test_skip_playing_when_idle_is_noop() -> None:
    runtime, ctx = make_runtime(vad=FakeVad({}))
    await runtime.start_listening()
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        await runtime.skip_playing_async()
        assert not ctx.queue.playing
        assert ctx.queue.pending == 0
        assert ctx.tts_states == []
    finally:
        await _stop_playback(playback)
        await runtime.stop_listening()


async def test_stop_speaking_stops_player_and_clears_queue() -> None:
    runtime, ctx = make_runtime(vad=None)
    ctx.queue.enqueue(SpeechRequest(text="一", voice_id="demo", message_id="m1"))
    ctx.queue.begin_playback()
    await runtime.stop_speaking_async()
    assert ctx.player.stopped == 1
    assert not ctx.queue.playing
    assert ctx.queue.pending == 0


def test_replay_message_reads_user_text_with_character_voice() -> None:
    """voice.tts_play 重播不看 tts_eligible，但只读本聊天、本搭档的非助手消息。"""
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
    assert request.voice_id == pair.character.voice_id
    assert request.text == "在吗，白厄。"
    runtime.replay_message(
        user.model_copy(update={"conversation_id": "conv-other"})
    )
    assert ctx.queue.pop_next() is None
    runtime.replay_message(user.model_copy(update={"pair_id": "firefly_sam"}))
    assert ctx.queue.pop_next() is None
    runtime.replay_message(
        Message(
            conversation_id="conv-1",
            pair_id=PAIR_ID,
            source=MessageSource.ASSISTANT,
            kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
            text="好的，我马上处理。",
        )
    )
    assert ctx.queue.pop_next() is None


def test_enqueue_text_preview_defaults_to_character_voice() -> None:
    runtime, ctx = make_runtime(vad=None)
    runtime.enqueue_text("这是一句试听。")
    pair = load_pair_config(PAIR_ID)
    request = ctx.queue.pop_next()
    assert request is not None
    assert request.voice_id == pair.character.voice_id
    assert request.message_id == "preview"
    runtime.enqueue_text("……")  # 不可读文本不入队
    assert ctx.queue.pop_next() is None
