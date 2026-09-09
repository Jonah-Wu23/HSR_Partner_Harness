"""V0.3.9 L08：桌面语音抢占与单调 epoch（契约归档正文 .archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md §6）。

覆盖：
1. SpeechQueue 单调 epoch：中断清队列、跳过保留待播项、旧 epoch 条目被丢弃；
2. 用户发送（chat.submit）抢占桌面朗读，reason=user_send；
3. 新角色完整消息抢占旧朗读（reason=new_message），且先抢占后入队；
4. 中断后旧合成迭代器的迟到 PCM 不再写入播放器；
5. 没有播放也没有待播项时不发假的 voice.playback_interrupted。

离线夹具只证明协议与状态逻辑，不构成真机或真实供应商链路证据。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

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
from test_v035_wiring import call, service  # noqa: F401 - fixture 复用
from test_voice_runtime import BLOCK, FakePlayer, FakeRecognizer, wait_until

PAIR_ID = "phainon_ancient_machine"


def _pair_config():
    """带可用角色音色的搭档配置：入队路径只在有效音色存在时才朗读。"""
    pair = load_pair_config(PAIR_ID)
    return pair.model_copy(
        update={
            "character": pair.character.model_copy(update={"voice_id": "test-voice"})
        }
    )


class GatedSynthesizer:
    """按 message_id 逐块等待事件的合成器，供播放中途做确定性抢占。

    抢占只在分片边界生效：旧句的生成器停在 gate.wait() 时，必须再放行
    一次才会走到 epoch 校验并退出（真实 TTS 的下一个分片约百毫秒内到达）。
    """

    def __init__(
        self, gates: dict[str, asyncio.Event], *, chunks: int = 5
    ) -> None:
        self.gates = gates
        self.chunks = chunks
        self.requests: list[SpeechRequest] = []
        self.closed = 0

    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        self.requests.append(request)
        gate = self.gates.get(request.message_id)
        try:
            for _ in range(self.chunks):
                if gate is not None:
                    await gate.wait()
                    gate.clear()
                yield AudioChunk(pcm=BLOCK, final=False)
            yield AudioChunk(pcm=b"", final=True)
        finally:
            self.closed += 1


def _runtime(
    synthesizer,
    player,
    queue,
    interrupted: list[tuple[str, str | None, str]],
) -> VoiceRuntime:
    return VoiceRuntime(
        orchestrator=object(),  # 下行播放不经过编排器
        recognizer=FakeRecognizer(),
        synthesizer=synthesizer,
        vad=None,
        capture_factory=lambda: None,
        player=player,
        queue=queue,
        pair_config=_pair_config(),
        conversation_id="conv-1",
        on_interrupted=lambda conversation_id, message_id, reason: interrupted.append(
            (conversation_id, message_id, reason)
        ),
    )


def _character_message(message_id: str, text: str) -> Message:
    return Message(
        message_id=message_id,
        conversation_id="conv-1",
        pair_id=_pair_config().pair_id,
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text=text,
    )


async def _stop_playback(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------- SpeechQueue


def test_speech_queue_interrupt_clears_and_drops_stale_items() -> None:
    queue = SpeechQueue()
    queue.enqueue(SpeechRequest(text="一", voice_id="v", message_id="m1"))
    queue.enqueue(SpeechRequest(text="二", voice_id="v", message_id="m2"))
    assert queue.epoch == 0
    assert queue.pending == 2

    assert queue.interrupt() == 1
    assert queue.epoch == 1
    assert queue.pending == 0
    assert queue.pop_next() is None
    assert not queue.playing


def test_speech_queue_skip_current_keeps_pending_on_new_epoch() -> None:
    queue = SpeechQueue()
    queue.enqueue(SpeechRequest(text="一", voice_id="v", message_id="m1"))
    queue.enqueue(SpeechRequest(text="二", voice_id="v", message_id="m2"))
    queue.begin_playback()

    assert queue.skip_current() == 1
    assert queue.pending == 2
    assert queue.pending_message_id == "m1"
    assert queue.pop_next().message_id == "m1"
    assert queue.pop_next().message_id == "m2"
    assert queue.pop_next() is None


def test_speech_queue_stop_is_an_interrupt() -> None:
    queue = SpeechQueue()
    queue.enqueue(SpeechRequest(text="一", voice_id="v", message_id="m1"))
    queue.stop()
    assert queue.epoch == 1
    assert queue.pending == 0


# ---------------------------------------------------------------- VoiceRuntime


@pytest.mark.asyncio
async def test_interrupt_drops_inflight_pcm_and_reports_event() -> None:
    """抢占后旧 epoch 的迟到分片不再写入播放器，并如实上报抢占。"""
    gate = asyncio.Event()
    synthesizer = GatedSynthesizer({"m-1": gate}, chunks=5)
    player = FakePlayer()
    queue = SpeechQueue()
    interrupted: list[tuple[str, str | None, str]] = []
    runtime = _runtime(synthesizer, player, queue, interrupted)
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        queue.enqueue(SpeechRequest(text="第一句", voice_id="v", message_id="m-1"))
        gate.set()
        await wait_until(lambda: player.played)
        written = len(player.played)
        assert queue.playing

        epoch_before = queue.epoch
        assert runtime.interrupt("user_send") == "m-1"
        assert queue.epoch == epoch_before + 1
        assert not queue.playing
        assert player.stopped >= 1
        assert interrupted == [("conv-1", "m-1", "user_send")]

        # 抢占后合成器继续产出：迟到 PCM 一律不写入。
        gate.set()
        await asyncio.sleep(0.05)
        assert len(player.played) == written
        assert synthesizer.closed >= 1
    finally:
        await _stop_playback(playback)


@pytest.mark.asyncio
async def test_new_character_message_preempts_previous_speech() -> None:
    """新角色完整消息先抢占旧朗读再入队，只保留最新一条待播。"""
    gates = {"m-1": asyncio.Event(), "m-2": asyncio.Event()}
    synthesizer = GatedSynthesizer(gates, chunks=5)
    player = FakePlayer()
    queue = SpeechQueue()
    interrupted: list[tuple[str, str | None, str]] = []
    runtime = _runtime(synthesizer, player, queue, interrupted)
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        runtime.on_message(_character_message("m-1", "第一句"))
        gates["m-1"].set()
        await wait_until(lambda: player.played)
        written = len(player.played)

        runtime.on_message(_character_message("m-2", "第二句"))
        assert interrupted == [("conv-1", "m-1", "new_message")]
        assert queue.pending == 1
        assert queue.pending_message_id == "m-2"

        # 旧句在下一个分片边界退出（迟到 PCM 不写入），随后播新句。
        gates["m-1"].set()
        await wait_until(lambda: len(synthesizer.requests) == 2)
        gates["m-2"].set()
        await wait_until(lambda: len(player.played) > written)
        assert queue.pending == 0
        assert synthesizer.requests[-1].message_id == "m-2"
    finally:
        await _stop_playback(playback)


@pytest.mark.asyncio
async def test_assistant_and_tool_messages_never_preempt() -> None:
    """助手/工具消息不进入 TTS，也不得打断正在朗读的角色语音。"""
    gate = asyncio.Event()
    synthesizer = GatedSynthesizer({"m-1": gate}, chunks=5)
    player = FakePlayer()
    queue = SpeechQueue()
    interrupted: list[tuple[str, str | None, str]] = []
    runtime = _runtime(synthesizer, player, queue, interrupted)
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        runtime.on_message(_character_message("m-1", "第一句"))
        gate.set()
        await wait_until(lambda: player.played)
        written = len(player.played)
        runtime.on_message(
            Message(
                message_id="m-assistant",
                conversation_id="conv-1",
                pair_id=_pair_config().pair_id,
                source=MessageSource.ASSISTANT,
                kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
                text="助手回复",
            )
        )
        assert interrupted == []
        assert queue.pending == 0
        await asyncio.sleep(0.02)
        assert len(player.played) == written
    finally:
        await _stop_playback(playback)


@pytest.mark.asyncio
async def test_interrupt_without_activity_emits_nothing() -> None:
    """没有播放也没有待播项时不得发假抢占事件，但 epoch 仍递增。"""
    synthesizer = GatedSynthesizer({}, chunks=1)
    player = FakePlayer()
    queue = SpeechQueue()
    interrupted: list[tuple[str, str | None, str]] = []
    runtime = _runtime(synthesizer, player, queue, interrupted)

    assert runtime.interrupt("user_send") is None
    assert queue.epoch == 1
    assert interrupted == []
    assert player.stopped == 0


@pytest.mark.asyncio
async def test_skip_playing_abandons_current_and_keeps_queue() -> None:
    """跳过：当前句 epoch 作废，待播项改挂新 epoch 继续播。"""
    gates = {"m-1": asyncio.Event(), "m-2": asyncio.Event()}
    synthesizer = GatedSynthesizer(gates, chunks=5)
    player = FakePlayer()
    queue = SpeechQueue()
    interrupted: list[tuple[str, str | None, str]] = []
    runtime = _runtime(synthesizer, player, queue, interrupted)
    playback = asyncio.create_task(runtime.run_playback_loop())
    try:
        queue.enqueue(SpeechRequest(text="一", voice_id="v", message_id="m-1"))
        queue.enqueue(SpeechRequest(text="二", voice_id="v", message_id="m-2"))
        gates["m-1"].set()
        await wait_until(lambda: player.played)
        written = len(player.played)
        epoch_before = queue.epoch

        runtime.skip_playing()
        assert queue.epoch == epoch_before + 1
        assert queue.pending == 1
        assert interrupted == []  # 跳过是显式动作，不是抢占事件

        gates["m-1"].set()  # 旧句在分片边界退出
        await wait_until(lambda: len(synthesizer.requests) == 2)
        gates["m-2"].set()
        await wait_until(lambda: len(player.played) > written)
        assert synthesizer.requests[-1].message_id == "m-2"
    finally:
        await _stop_playback(playback)


# ---------------------------------------------------------------- 服务接线


class PreemptRecordingRuntime:
    """记录抢占原因的服务级语音替身（真实 VoiceRuntime 的 interrupt_async）。"""

    def __init__(self) -> None:
        self.reasons: list[str] = []

    async def interrupt_async(self, reason: str = "manual_stop") -> None:
        self.reasons.append(reason)

    def on_message(self, message: Message) -> None:
        del message

    async def stop_speaking_async(self, reason: str = "manual_stop") -> None:
        self.reasons.append(reason)

    async def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_chat_submit_interrupts_desktop_speech(service) -> None:
    """用户发送立即停声：chat.submit 受理时抢占桌面朗读（reason=user_send）。"""
    runtime = PreemptRecordingRuntime()
    service.attach_voice_runtime(runtime)
    await call(service, "submit", "chat.submit", text="你好", target="character")
    assert runtime.reasons == ["user_send"]


@pytest.mark.asyncio
async def test_remote_claim_interrupts_with_remote_reason(service) -> None:
    """远程认领控制权同样先抢占桌面朗读（reason=remote_claim）。"""
    from pair_harness.desktop_backend.commands import DesktopCommand

    runtime = PreemptRecordingRuntime()
    service.attach_voice_runtime(runtime)
    await service.handle_command(
        DesktopCommand(
            request_id="claim",
            method="remote.claim_control",
            params={},
            origin="remote",
            connection_key="phone",
            remote_device_key="device-1",
        )
    )
    assert runtime.reasons == ["remote_claim"]
