from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

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
from pair_harness.desktop_backend.commands import DesktopCommand
from tests.service_helpers import call, wait_until
from tests.voice_helpers import (
    BLOCK,
    FakeCapture,
    FakePlayer,
    FakeRecognizer,
    attach_desktop_runtime,
    character_reply,
    unexpected_text_input,
)

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
        on_text_input=unexpected_text_input,
        recognizer=FakeRecognizer(),
        synthesizer=synthesizer,
        vad=None,
        capture_factory=FakeCapture,
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


# ---------------------------------------------------------------- VoiceRuntime


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

        # 抢占后合成器继续产出，迟到 PCM 一律不写入
        gate.set()
        await wait_until(lambda: synthesizer.closed >= 1)
        assert len(player.played) == written
    finally:
        await _stop_playback(playback)


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

        # 旧句在下一个分片边界退出，迟到 PCM 不写入，随后播新句
        gates["m-1"].set()
        await wait_until(lambda: len(synthesizer.requests) == 2)
        gates["m-2"].set()
        await wait_until(lambda: len(player.played) > written)
        assert queue.pending == 0
        assert synthesizer.requests[-1].message_id == "m-2"
    finally:
        await _stop_playback(playback)


async def test_assistant_messages_never_preempt() -> None:
    """助手消息不进入 TTS，也不打断正在朗读的角色语音。"""
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
        gate.set()
        await wait_until(lambda: len(player.played) > written)  # 角色语音继续播放
    finally:
        await _stop_playback(playback)


def test_interrupt_without_activity_emits_nothing() -> None:
    """没有播放也没有待播项时不发抢占事件、不停播放器，epoch 仍递增。"""
    synthesizer = GatedSynthesizer({}, chunks=1)
    player = FakePlayer()
    queue = SpeechQueue()
    interrupted: list[tuple[str, str | None, str]] = []
    runtime = _runtime(synthesizer, player, queue, interrupted)

    assert runtime.interrupt("user_send") is None
    assert queue.epoch == 1
    assert interrupted == []
    assert player.stopped == 0


# ---------------------------------------------------------------- 服务接线


async def _attach_runtime_with_pending_reply(service) -> tuple[list, str]:
    """挂上桌面语音运行时，让一条演示角色回复进入待播队列。"""
    interrupted: list[tuple[str, str | None, str]] = []
    runtime = attach_desktop_runtime(service, interrupted=interrupted)
    reply_id = await character_reply(service, "first", "你好")
    assert runtime.speech_queue_len == 1
    return interrupted, reply_id


async def test_chat_submit_interrupts_desktop_speech(service) -> None:
    interrupted, reply_id = await _attach_runtime_with_pending_reply(service)

    await call(service, "second", "chat.submit", text="再说一句", target="character")

    assert interrupted == [(service.current_conversation_id, reply_id, "user_send")]


async def test_remote_claim_interrupts_desktop_speech(service) -> None:
    interrupted, reply_id = await _attach_runtime_with_pending_reply(service)

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

    assert interrupted == [(service.current_conversation_id, reply_id, "remote_claim")]
    assert service.voice_runtime.speech_queue_len == 0
