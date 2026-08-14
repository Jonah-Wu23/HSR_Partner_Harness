"""VoiceRuntime：上行（麦克风→VAD→ASR→Orchestrator）与下行（消息→TTS→播放）协调器。

设计依据：``docs/plans/2026-08-11-b2-voice-detailed-design.md`` §5。

上行：VoiceRuntime 持有唯一采集流，逐块 tee——
- 喂给 VAD（``VoiceActivityDetector.detect`` 的事件流驱动语音段生命周期）；
- 维护自己的 8×640B pre-roll 环形缓冲，``speech_started`` 时补发给 ASR；
- 语音段激活期间实时转发给 ASR（``SpeechRecognizer.stream_transcribe``）。

TTS 播放期间暂停向 VAD 喂帧（采集继续、帧丢弃），播放结束重开 VAD 会话，
避免把扬声器尾音误判为说话。按键说话先 ``stop_speaking()`` 再直录，
松开后等 final，非空才提交。空 final / 误触发不产生消息。

下行（V0.2 M2-4）：播放器持有长期输出流与有界缓冲，句间/块间不断流；
``skip_playing()`` 跳过当前句继续播队列下一句（队列空则停止）；tts 状态
机经 ``on_tts_state`` 上报（idle/synthesizing/playing/skipping/failed），
vad 状态保持既有语义。V0.2 M4：合成开始置 synthesizing、首个 PCM 块写入
播放器才置 playing；合成失败置 failed 并清空待播队列（停止消费，等待重播）。
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from inspect import isawaitable
from typing import TYPE_CHECKING

from pair_harness.core.audio import SpeechQueue
from pair_harness.core.contracts import (
    AsrEvent,
    Message,
    MessageSource,
    SpeechRequest,
    VadEvent,
)
from pair_harness.core.ports import (
    SpeechRecognizer,
    SpeechSynthesizer,
    VoiceActivityDetector,
)
from pair_harness.core.voice_policy import (
    extract_speech_segments,
    is_readable_text,
    is_tts_eligible,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from pair_harness.adapters.audio.sounddevice_io import AudioPlayer, MicrophoneCapture
    from pair_harness.config.pairs import PairConfig
    from pair_harness.core.orchestrator import ConversationOrchestrator

# pre-roll 环形缓冲容量：8 块 × 640 B（20 ms @ 16 kHz）
PRE_ROLL_BLOCKS = 8
_ASR_END = object()  # ASR 输入流哨兵


class VoiceRuntime:
    """上行/下行语音协调器（B2.6）。

    全部音频组件依赖注入；``vad=None`` 表示 VAD 不可用，自动退回按键说话。
    """

    def __init__(
        self,
        *,
        orchestrator: "ConversationOrchestrator",
        recognizer: SpeechRecognizer,
        synthesizer: SpeechSynthesizer,
        vad: VoiceActivityDetector | None,
        capture_factory: Callable[[], "MicrophoneCapture"],
        player: "AudioPlayer",
        queue: SpeechQueue,
        pair_config: "PairConfig",
        conversation_id: str,
        on_vad_state: Callable[[str], None] = lambda _s: None,
        on_asr_partial: Callable[[str], None] = lambda _t: None,
        on_error: Callable[[str], None] = lambda _m: None,
        on_tts_state: Callable[[str], None] = lambda _s: None,
    ) -> None:
        self._orchestrator = orchestrator
        self._recognizer = recognizer
        self._synthesizer = synthesizer
        self._vad = vad
        self._capture_factory = capture_factory
        self._player = player
        self._queue = queue
        self._pair_config = pair_config
        self._conversation_id = conversation_id
        self._on_vad_state = on_vad_state
        self._on_asr_partial = on_asr_partial
        self._on_error = on_error
        self._on_tts_state = on_tts_state

        self._capture: "MicrophoneCapture | None" = None
        self._capture_task: asyncio.Task | None = None
        self._vad_task: asyncio.Task | None = None
        self._vad_input: asyncio.Queue[bytes] | None = None
        self._playback_task: asyncio.Task | None = None

        # ASR 会话字段（一个语音段 = 一个会话）
        self._asr_input: asyncio.Queue[bytes | object] | None = None
        self._asr_task: asyncio.Task | None = None
        self._asr_active = False
        self._asr_final_text: str = ""

        self._pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_BLOCKS)
        self._ptt_active = False
        self._ptt_target = "character"
        self._started = False
        self._vad_enabled = False
        # V0.2 M2-4：跳过当前句的标记，由播放循环消费（见 skip_playing）
        self._skip = False
        # V0.2 M4：当前句合成失败标记——失败后 tts 保持 failed，直到下次播放成功
        self._tts_failed = False
        # 古代机械语音默认关闭；由账号级语音设置显式开启。
        self._assistant_voice_enabled = False
        # 古代机械的阶段性说明会先于最终执行回执到达。记录已提前入队的
        # 文本，最终消息再次落库时只保留一份语音。
        self._preannounced_assistant_texts: set[str] = set()
        self._progress_message_index = 0

    @property
    def speech_queue_len(self) -> int:
        """待播队列条数（不含正在播放的当前条）；VoiceMiniPlayer 的 queuedCount。"""
        return self._queue.pending

    def set_assistant_voice_enabled(self, enabled: bool) -> None:
        """设置古代机械是否自动朗读消息。"""
        self._assistant_voice_enabled = bool(enabled)

    # ------------------------------------------------------------ 生命周期

    async def start_listening(self, *, vad_enabled: bool = True) -> None:
        """打开麦克风；VAD 可单独关闭，但仍保留采集供 PTT。"""
        if self._started:
            await self.set_vad_enabled(vad_enabled)
            return
        self._started = True
        self._vad_enabled = bool(vad_enabled and self._vad is not None)
        self._capture = self._capture_factory()
        try:
            await self._capture.__aenter__()
        except Exception:
            self._capture = None
            self._started = False
            raise
        self._capture_task = asyncio.create_task(self._capture_loop())
        if self._vad is None:
            self._on_vad_state("idle")
            self._on_error("VAD 不可用，已切换为按键说话")
            return
        if self._vad_enabled:
            self._start_vad_loop()
        else:
            self._on_vad_state("idle")

    async def set_vad_enabled(self, enabled: bool) -> None:
        """只切换 VAD；关闭 VAD 时不关闭麦克风，保证 PTT 仍可用。"""
        if self._vad is None:
            self._vad_enabled = False
            self._on_vad_state("unavailable")
            return
        if not self._started:
            if enabled:
                await self.start_listening(vad_enabled=True)
            return
        if enabled:
            if self._vad_enabled and self._vad_task is not None and not self._vad_task.done():
                return
            self._vad_enabled = True
            self._start_vad_loop()
            return
        self._vad_enabled = False
        await self._cancel_task(self._vad_task)
        self._vad_task = None
        self._vad_input = None
        self._on_vad_state("idle")

    def _start_vad_loop(self) -> None:
        if self._vad is None or not self._started:
            return
        self._vad_input = asyncio.Queue()
        self._vad_task = asyncio.create_task(self._vad_loop())
        self._on_vad_state("listening")

    async def stop_listening(self) -> None:
        if not self._started:
            return
        self._started = False
        self._vad_enabled = False
        for task in (self._vad_task, self._capture_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (self._vad_task, self._capture_task):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._vad_task = None
        self._capture_task = None
        if self._capture is not None:
            await self._capture.__aexit__(None, None, None)
            self._capture = None
        self._on_vad_state("idle")

    def start_playback(self) -> None:
        """启动唯一的播放消费任务与播放器线程；重复调用无效。"""
        if self._playback_task is None or self._playback_task.done():
            self._playback_task = asyncio.create_task(self.run_playback_loop())
        self._player.start()

    async def shutdown(self) -> None:
        """B2 UI 退出时关闭采集、识别与播放任务。"""
        self.stop_speaking()
        if self._asr_active:
            await self._end_asr(commit=False, target=self._ptt_target)
        await self.stop_listening()
        await self._cancel_task(self._playback_task)
        self._playback_task = None
        self._player.close()

    # ------------------------------------------------------------ 上行：采集分发

    async def _capture_loop(self) -> None:
        assert self._capture is not None
        async for chunk in self._capture.chunks():
            if self._ptt_active:
                # 按键说话：按下即开始攒帧，直接进 ASR（不经 VAD、不进 pre-roll）
                if self._asr_active:
                    assert self._asr_input is not None
                    self._asr_input.put_nowait(chunk)
                continue
            if self._queue.playing:
                # TTS 播放中：暂停向 VAD 喂帧（采集继续，帧丢弃）
                continue
            if self._vad_input is not None:
                self._vad_input.put_nowait(chunk)
            if self._asr_active:
                if self._asr_input is not None:
                    self._asr_input.put_nowait(chunk)
            else:
                # pre-roll 只在静默期累积；语音段开始后不再更新，
                # 避免把上一段语音尾部补发给下一段 ASR
                self._pre_roll.append(chunk)

    # ------------------------------------------------------------ 上行：VAD 事件

    async def _vad_loop(self) -> None:
        assert self._vad is not None and self._vad_input is not None

        async def vad_stream() -> AsyncIterator[bytes]:
            while True:
                chunk = await self._vad_input.get()
                yield chunk

        try:
            async for event in self._vad.detect(vad_stream()):
                await self._handle_vad_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - VAD 运行时异常降级为提示
            self._on_error(f"VAD 异常：{exc}")
            self._on_vad_state("idle")

    async def _handle_vad_event(self, event: VadEvent) -> None:
        self._on_vad_state(event.type)
        if event.type == "speech_started":
            await self._begin_asr(pre_roll=True)
        elif event.type in ("speech_ended", "false_trigger"):
            commit = event.type == "speech_ended"
            await self._end_asr(commit=commit, target="character")

    # ------------------------------------------------------------ 上行：ASR 会话

    async def _begin_asr(self, *, pre_roll: bool) -> None:
        if self._asr_active:
            return
        self._asr_input = asyncio.Queue()
        self._asr_active = True
        self._asr_final_text = ""
        self._asr_task = asyncio.create_task(self._asr_consume())
        if pre_roll:
            for chunk in list(self._pre_roll):
                self._asr_input.put_nowait(chunk)

    async def _asr_consume(self) -> None:
        assert self._asr_input is not None

        async def audio_stream() -> AsyncIterator[bytes]:
            while True:
                item = await self._asr_input.get()
                if item is _ASR_END:
                    return
                yield item  # type: ignore[misc]

        try:
            async for event in self._recognizer.stream_transcribe(audio_stream()):
                self._consume_asr_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 识别异常降级为提示
            self._on_error(f"语音识别异常：{exc}")

    def _consume_asr_event(self, event: AsrEvent) -> None:
        if event.type == "partial" and event.text:
            self._on_asr_partial(event.text)
        elif event.type == "final":
            self._asr_final_text = event.text
        elif event.type == "error":
            self._asr_final_text = ""
            self._on_error(f"语音识别失败：{event.error}")

    async def _end_asr(self, *, commit: bool, target: str) -> None:
        if not self._asr_active or self._asr_input is None:
            return
        self._asr_input.put_nowait(_ASR_END)
        self._asr_active = False
        if self._asr_task is not None:
            await self._asr_task
            self._asr_task = None
        text = self._asr_final_text.strip()
        if commit and text:
            await self._commit(text, target)
        else:
            self._on_asr_partial("")  # 空转写/误触发：清空回显，不提交

    async def _commit(self, text: str, target: str) -> None:
        self._on_asr_partial("")  # final 已提交，清空输入区回显
        if target == "assistant":
            await self._orchestrator.handle_direct_input(
                conversation_id=self._conversation_id, text=text
            )
        else:
            await self._orchestrator.handle_character_input(
                conversation_id=self._conversation_id, text=text
            )

    # ------------------------------------------------------------ 上行：按键说话

    async def push_to_talk_start(self, target: str = "character") -> None:
        """按下说话键：先停 TTS，再开 ASR 会话直录（无 pre-roll）。"""
        self.stop_speaking()
        self._ptt_target = target
        self._ptt_active = True
        self._on_vad_state("speech_started")
        await self._begin_asr(pre_roll=False)

    async def push_to_talk_stop(self) -> None:
        """松开说话键：收尾识别，非空提交。"""
        if not self._ptt_active:
            return
        self._ptt_active = False
        await self._end_asr(commit=True, target=self._ptt_target)

    # ------------------------------------------------------------ 下行：TTS

    def on_message(self, message: Message) -> None:
        """消息监听入口（由 Orchestrator 在持久化后调用）。

        仅 tts_eligible 的消息进入 TTS：character.speech 全文入队；
        assistant.natural_language 按 ``extract_speech_segments`` 分段落入队。
        voice_id 按来源选 pair 配置的 character/assistant 音色。
        """
        if message.conversation_id != self._conversation_id:
            return
        if not is_tts_eligible(message.source, message.kind):
            return
        if message.source == MessageSource.ASSISTANT and not self._assistant_voice_enabled:
            return
        self._enqueue_for_playback(message)

    def replay_message(self, message: Message) -> None:
        """逐条朗读（voice.tts_play）：用户主动指定重播，无视 tts_eligible。

        USER/CHARACTER 消息用角色音色全文朗读；assistant 及其余来源用
        助手音色按段落朗读。不可读文本（省略号/纯标点）仍被过滤。
        """
        if message.conversation_id != self._conversation_id:
            return
        self._enqueue_for_playback(message)

    def enqueue_text(self, text: str, *, voice_id: str | None = None) -> None:
        """直接按文本入队（voice.preview 试听）；voice_id 缺省取角色音色。"""
        text = text.strip()
        if not is_readable_text(text):
            return
        self._queue.enqueue(
            SpeechRequest(
                text=text,
                voice_id=voice_id or self._pair_config.character.voice_id,
                message_id="preview",
            )
        )

    def _enqueue_for_playback(self, message: Message) -> None:
        """按消息来源选音色/分段，过滤不可读文本后入队。"""
        if message.source == MessageSource.ASSISTANT:
            voice_id = self._pair_config.assistant.voice_id
            segments = extract_speech_segments(message.text)
        else:
            voice_id = self._pair_config.character.voice_id
            segments = [message.text]
        for segment in segments:
            text = segment.strip()
            # V0.2 问题 2：入队前再次检查有效自然语言——省略号/纯标点
            # 降级文本不创建可朗读请求（DashScope 会报 input text is invalid）
            if not is_readable_text(text):
                continue
            if message.source == MessageSource.ASSISTANT:
                key = self._speech_key(text)
                if key in self._preannounced_assistant_texts:
                    self._preannounced_assistant_texts.discard(key)
                    continue
            self._queue.enqueue(
                SpeechRequest(
                    text=text, voice_id=voice_id, message_id=message.message_id
                )
            )

    @staticmethod
    def _speech_key(text: str) -> str:
        return " ".join(str(text).split())

    def enqueue_assistant_progress(self, text: str) -> None:
        """把古代机械的阶段性说明立即送入语音队列。"""
        if not self._assistant_voice_enabled:
            return
        text = str(text or "").strip()
        if not is_readable_text(text):
            return
        key = self._speech_key(text)
        self._preannounced_assistant_texts.add(key)
        self._progress_message_index += 1
        self._queue.enqueue(
            SpeechRequest(
                text=text,
                voice_id=self._pair_config.assistant.voice_id,
                message_id=f"assistant-progress:{self._progress_message_index}",
            )
        )

    def set_context(self, conversation_id: str, pair_config: PairConfig) -> None:
        """切换语音所属聊天与搭档，并停止旧聊天的待播语音。"""
        self.stop_speaking()
        self._preannounced_assistant_texts.clear()
        self._conversation_id = conversation_id
        self._pair_config = pair_config

    def stop_speaking(self) -> None:
        """停止播放并清空待播队列（同步入口，供 UI 信号直接调用）。

        V0.2 M2-4：立即清空播放器缓冲并停止写流，当前句即刻无声；
        播放循环在下一个块检查时退出合成并重开 VAD。
        """
        self._player.stop()
        self._queue.stop()
        self._skip = False
        # 阶段性说明可能已被丢弃（未播报）：最终消息落库时不得再被
        # 去重跳过，否则助手最终回复将彻底无声。
        self._preannounced_assistant_texts.clear()

    def skip_playing(self) -> None:
        """跳过当前句：立即停声并放弃当前合成，继续播队列下一句。

        队列已空时播放循环自然停止（tts 回 idle、VAD 重开）；未在播放时
        无句可跳，待播项由播放循环自行消费。
        """
        if not self._queue.playing:
            return
        self._player.stop()
        self._skip = True
        self._on_tts_state("skipping")

    async def run_playback_loop(self) -> None:
        """消费 SpeechQueue：合成 → 写入长期输出流；stop/skip 中断当前合成。"""
        while True:
            request = self._queue.pop_next()
            if request is None:
                await asyncio.sleep(0.05)
                continue
            self._queue.begin_playback()
            self._on_vad_state("playing")
            # V0.2 M4：tts 状态机补 synthesizing 过渡态——出队开始合成置
            # synthesizing，首个 PCM 块写入播放器才置 playing（见 _play_request）
            self._on_tts_state("synthesizing")
            try:
                await self._play_request(request)
                # 合成迭代器结束时，播放器输出缓冲可能仍有音频。等实际
                # 输出排空后再回到 idle，停止按钮覆盖真实播报阶段。
                if self._queue.playing and not self._skip:
                    await self._wait_for_player_drain()
            except Exception as exc:  # noqa: BLE001 - TTS 失败降级为静音提示
                self._tts_failed = True
                self._on_tts_state("failed")
                self._on_error(f"语音合成失败：{exc}")
                # V0.2 M4：合成失败停止消费队列——清空待播项并保持 failed
                # 状态（不回落 idle），等待用户重播或下一条新消息；避免连发失败
                self._queue.stop()
            skipped = self._skip
            self._skip = False
            self._queue.end_playback()
            if skipped and self._queue.pending:
                # 跳过当前句：不重开 VAD，直接消费下一句（连续播放）
                continue
            if not self._tts_failed:
                self._on_tts_state("idle")
            await self._restart_vad()
            # _restart_vad 已发出 "listening"；仅无 VAD/未启动时置 "idle"
            if self._vad is None or not self._started or not self._vad_enabled:
                self._on_vad_state("idle")

    async def _wait_for_player_drain(self) -> None:
        waiter = getattr(self._player, "wait_until_idle", None)
        if waiter is None:
            return
        result = await asyncio.to_thread(waiter)
        if isawaitable(result):
            await result

    async def _play_request(self, request: SpeechRequest) -> None:
        """合成一条请求并把 PCM 写入播放器；stop/skip 由块循环检查。"""
        agen = self._synthesizer.synthesize(request)
        wrote_first_block = False
        try:
            async for chunk in agen:
                if chunk.final:
                    break
                if not self._queue.playing:
                    # stop_speaking 已清队列并复位 playing：中断合成
                    break
                if self._skip:
                    # skip_playing：放弃当前句，改播队列下一句
                    break
                if chunk.pcm:
                    if not wrote_first_block:
                        # V0.2 M4：首个 PCM 块写入播放器才算真正出声 → playing
                        wrote_first_block = True
                        self._tts_failed = False
                        self._on_tts_state("playing")
                    await asyncio.to_thread(self._player.play_blocking, chunk.pcm)
        finally:
            await agen.aclose()

    async def _cancel_task(self, task: asyncio.Task | None) -> None:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _restart_vad(self) -> None:
        """播放结束后重开 VAD 会话，避免把扬声器尾音误判为说话。"""
        if self._vad is None or not self._started or not self._vad_enabled:
            return
        await self._cancel_task(self._vad_task)
        self._vad_task = None
        # 丢弃播放期间可能残留的帧
        if self._vad_input is None:
            self._start_vad_loop()
            return
        while not self._vad_input.empty():
            try:
                self._vad_input.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._start_vad_loop()
