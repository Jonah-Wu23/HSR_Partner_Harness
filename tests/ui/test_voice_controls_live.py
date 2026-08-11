"""B2.6 UI 接线测试（offscreen）：VoiceRuntime 回调驱动界面控件。

设计 §6.3 验收：
- VAD 状态回调驱动 AudioControls 文案（聆听中/说话中/识别中/播放中）；
- ASR partial 出现在输入区，final 提交后清空；
- 停止按钮经 MainWindow 信号触发 stop_speaking。
信号接线与 ``ui/app.py wire_real_voice`` 相同（假适配器注入，不触网）。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace

import pytest

from pair_harness.config.pairs import load_pair_config
from pair_harness.core.audio import SpeechQueue
from pair_harness.core.contracts import SpeechRequest
from pair_harness.core.voice_runtime import VoiceRuntime
from pair_harness.ui.main_window import MainWindow
from tests.unit.test_voice_runtime import (
    BLOCK,
    FakeCapture,
    FakeOrchestrator,
    FakePlayer,
    FakeRecognizer,
    FakeSynthesizer,
    FakeVad,
    wait_until,
)

PAIR_ID = "phainon_ancient_machine"


def build_window_runtime(
    *,
    vad: FakeVad | None,
    recognizer: FakeRecognizer,
    synthesizer: FakeSynthesizer | None = None,
) -> SimpleNamespace:
    """按 app.py wire_real_voice 的方式装配 MainWindow + VoiceRuntime。"""
    window = MainWindow(theme=load_pair_config(PAIR_ID).theme)
    capture = FakeCapture()
    orch = FakeOrchestrator()
    queue = SpeechQueue()
    def apply_vad_state(state: str) -> None:
        # 与 app.py wire_real_voice 相同的包装：playing 启用停止按钮
        window.audio_controls.set_vad_state(state)
        window.audio_controls.set_playing(state == "playing")

    runtime = VoiceRuntime(
        orchestrator=orch,
        recognizer=recognizer,
        synthesizer=synthesizer or FakeSynthesizer(),
        vad=vad,
        capture_factory=lambda: capture,
        player=FakePlayer(),
        queue=queue,
        pair_config=load_pair_config(PAIR_ID),
        conversation_id="conv-1",
        on_vad_state=apply_vad_state,
        on_asr_partial=window.input_bar.set_asr_interim,
        on_error=lambda message: window.audio_controls.vad_label.setText(message),
    )

    def ptt_start() -> None:
        asyncio.ensure_future(
            runtime.push_to_talk_start(target=window.input_bar.target)
        )

    def ptt_stop() -> None:
        asyncio.ensure_future(runtime.push_to_talk_stop())

    # 与 app.py 相同的信号接线
    window.push_to_talk_pressed.connect(ptt_start)
    window.push_to_talk_released.connect(ptt_stop)
    window.stop_speech_requested.connect(runtime.stop_speaking)
    return SimpleNamespace(
        window=window, runtime=runtime, capture=capture, orch=orch, queue=queue
    )


@pytest.mark.asyncio
async def test_vad_state_drives_audio_controls(qtbot) -> None:
    ctx = build_window_runtime(
        vad=FakeVad({1: "speech_started", 2: "speech_ended"}),
        recognizer=FakeRecognizer(final="你好，白厄。"),
    )
    qtbot.addWidget(ctx.window)
    await ctx.runtime.start_listening()
    try:
        assert ctx.window.audio_controls.vad_label.text() == "聆听中"

        ctx.capture.feed(BLOCK)
        await wait_until(
            lambda: ctx.window.audio_controls.vad_label.text() == "说话中"
        )
        ctx.capture.feed(BLOCK)
        await wait_until(
            lambda: ctx.window.audio_controls.vad_label.text() == "识别中"
        )
        await wait_until(lambda: len(ctx.orch.character_inputs) == 1)
        assert ctx.orch.character_inputs == [("conv-1", "你好，白厄。")]
    finally:
        await ctx.runtime.stop_listening()


@pytest.mark.asyncio
async def test_asr_partial_shows_in_input_and_cleared_on_final(qtbot) -> None:
    hold = asyncio.Event()
    ctx = build_window_runtime(
        vad=FakeVad({1: "speech_started", 2: "speech_ended"}),
        recognizer=FakeRecognizer(
            partials=["你好，白厄"], final="你好，白厄。", partial_hold=hold
        ),
    )
    qtbot.addWidget(ctx.window)
    await ctx.runtime.start_listening()
    try:
        ctx.capture.feed(BLOCK)
        await wait_until(
            lambda: ctx.window.audio_controls.vad_label.text() == "说话中"
        )
        ctx.capture.feed(BLOCK)
        # partial 显示在输入区
        await wait_until(
            lambda: ctx.window.input_bar.text_input.text() == "你好，白厄"
        )
        hold.set()
        # final 提交后清空回显
        await wait_until(lambda: ctx.window.input_bar.text_input.text() == "")
        assert ctx.orch.character_inputs == [("conv-1", "你好，白厄。")]
    finally:
        hold.set()
        await ctx.runtime.stop_listening()


@pytest.mark.asyncio
async def test_ptt_signals_reach_runtime(qtbot) -> None:
    blocks_in = asyncio.Event()
    ctx = build_window_runtime(
        vad=FakeVad({}),
        recognizer=FakeRecognizer(
            partials=["好"], final="好的。", blocks=1, on_blocks=blocks_in
        ),
    )
    qtbot.addWidget(ctx.window)
    await ctx.runtime.start_listening()
    try:
        ctx.window.push_to_talk_pressed.emit()
        await wait_until(
            lambda: ctx.window.audio_controls.vad_label.text() == "说话中"
        )
        ctx.capture.feed(BLOCK)
        await wait_until(lambda: blocks_in.is_set())
        ctx.window.push_to_talk_released.emit()
        await wait_until(lambda: len(ctx.orch.character_inputs) == 1)
        assert ctx.orch.character_inputs == [("conv-1", "好的。")]
        # 停止监听后状态复位
        await ctx.runtime.stop_listening()
        assert ctx.window.audio_controls.vad_label.text() == "待机"
    finally:
        await ctx.runtime.stop_listening()


@pytest.mark.asyncio
async def test_stop_button_triggers_stop_speaking(qtbot) -> None:
    hold = asyncio.Event()
    ctx = build_window_runtime(
        vad=FakeVad({}),
        recognizer=FakeRecognizer(),
        synthesizer=FakeSynthesizer(hold=hold),
    )
    qtbot.addWidget(ctx.window)
    await ctx.runtime.start_listening()
    playback = asyncio.create_task(ctx.runtime.run_playback_loop())
    try:
        ctx.queue.enqueue(
            SpeechRequest(text="正在播放", voice_id="demo-phainon", message_id="m1")
        )
        await wait_until(lambda: ctx.queue.playing)
        assert ctx.window.audio_controls.vad_label.text() == "播放中"
        assert ctx.window.audio_controls.stop_button.isEnabled()

        # 停止按钮：stop_requested → window.stop_speech_requested → stop_speaking
        ctx.window.audio_controls.stop_button.click()
        assert ctx.queue.playing is False
        assert ctx.queue.pending == 0
    finally:
        hold.set()
        # 播放循环重开 VAD 后会回到等待；等状态条回到"聆听中"再取消，
        # 避免取消落在 _restart_vad 内部被吞掉导致任务悬挂
        await wait_until(
            lambda: ctx.window.audio_controls.vad_label.text() == "聆听中"
        )
        playback.cancel()
        with suppress(asyncio.CancelledError):
            await playback
        await ctx.runtime.stop_listening()
