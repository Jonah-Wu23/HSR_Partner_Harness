# 语音协调器：上行把麦克风经 VAD 与 ASR 转成文本交给桌面 Turn 链，下行把
# 角色消息经 TTS 播放。DashScope 接口参考见 docs/design/dashscope/。

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
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
    is_readable_text,
    is_tts_eligible,
)

if TYPE_CHECKING:
    # 音频适配器依赖可选的 voice 依赖组，这里只用于类型标注。
    from pair_harness.adapters.audio.sounddevice_io import AudioPlayer, MicrophoneCapture
    from pair_harness.config.pairs import PairConfig

# pre-roll 环形缓冲容量：8 块 × 640 B（20 ms @ 16 kHz）
PRE_ROLL_BLOCKS = 8
_ASR_END = object()  # ASR 输入流哨兵
logger = logging.getLogger(__name__)


class VoiceRuntime:
    """上行与下行语音协调器。

    上行：持有唯一采集流，逐块分发给 VAD（事件流驱动语音段生命周期）；
    维护 8×640B pre-roll 环形缓冲，``speech_started`` 时补发给 ASR；语音段
    激活期间实时转发给 ASR。TTS 播放期间暂停向 VAD 喂帧，播放结束重开
    VAD 会话，避免把扬声器尾音误判为说话。按键说话先停止朗读再直录，
    松开后等 final，非空才经 ``on_text_input`` 提交；空 final 与误触发
    不产生消息。

    下行：播放器持有长期输出流与有界缓冲，句间与块间不断流。SpeechQueue
    使用单调 epoch：用户发送、新角色完整消息、显式停止、跳过、切换与远程
    认领都先递增 epoch 再停播放器，旧 epoch 的迟到 PCM 永不写入。tts 状态
    经 ``on_tts_state`` 上报（idle/synthesizing/playing/skipping/failed）：
    合成开始置 synthesizing，首个 PCM 块写入播放器才置 playing，合成失败
    置 failed 并清空待播队列。

    全部音频组件依赖注入；``vad=None`` 表示 VAD 不可用，只能按键说话。
    """

    def __init__(
        self,
        *,
        recognizer: SpeechRecognizer,
        synthesizer: SpeechSynthesizer,
        vad: VoiceActivityDetector | None,
        capture_factory: Callable[[], "MicrophoneCapture"],
        player: "AudioPlayer",
        queue: SpeechQueue,
        pair_config: "PairConfig",
        conversation_id: str,
        on_text_input: Callable[[str, str], Awaitable[None]],
        on_vad_state: Callable[[str], None] = lambda _s: None,
        on_asr_partial: Callable[[str], None] = lambda _t: None,
        on_error: Callable[[str], None] = lambda _m: None,
        on_tts_state: Callable[[str], None] = lambda _s: None,
        on_interrupted: Callable[[str, str | None, str], None] = (
            lambda _conversation_id, _message_id, _reason: None
        ),
    ) -> None:
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
        # 抢占反馈回调（conversation_id, message_id, reason）。
        self._on_interrupted = on_interrupted
        # 语音文本交给桌面后台 Turn 链（text, target）。
        self._on_text_input = on_text_input

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
        self._commit_tasks: set[asyncio.Task[None]] = set()
        self._started = False
        self._vad_enabled = False
        # 跳过当前句的标记，由播放循环消费（见 skip_playing_async）
        self._skip = False
        # 正在播放的 message_id，供 voice.playback_interrupted。
        self._current_message_id: str | None = None
        # 当前句合成失败标记：失败后 tts 保持 failed，直到下次播放成功
        self._tts_failed = False

    @property
    def speech_queue_len(self) -> int:
        """待播队列条数（不含正在播放的当前条）；VoiceMiniPlayer 的 queuedCount。"""
        return self._queue.pending

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
        """关闭采集、识别与播放任务。"""
        await self.stop_speaking_async()
        if self._asr_active:
            await self._end_asr(commit=False, target=self._ptt_target)
        commit_tasks = tuple(self._commit_tasks)
        for task in commit_tasks:
            task.cancel()
        if commit_tasks:
            await asyncio.gather(*commit_tasks, return_exceptions=True)
        await self.stop_listening()
        await self._cancel_task(self._playback_task)
        self._playback_task = None
        # AudioPlayer.close 需要等待正在进行的原生写入完成；不要阻塞
        # Sidecar 事件循环，避免 shutdown 与 JSONL 请求互相卡住。
        await asyncio.to_thread(self._player.close)

    # ------------------------------------------------------------ 上行：采集分发

    async def _capture_loop(self) -> None:
        assert self._capture is not None
        try:
            async for chunk in self._capture.chunks():
                self._dispatch_chunk(chunk)
        except Exception as exc:  # noqa: BLE001 - 采集中断如实提示，重新开启聆听后恢复
            logger.exception("麦克风采集中断")
            self._on_error(f"麦克风采集异常：{exc}")
            self._on_vad_state("idle")

    def _dispatch_chunk(self, chunk: bytes) -> None:
        if self._ptt_active:
            # 按键说话：按下即开始攒帧，直接进 ASR（不经 VAD、不进 pre-roll）
            if self._asr_active:
                assert self._asr_input is not None
                self._asr_input.put_nowait(chunk)
            return
        if self._queue.playing:
            # TTS 播放中：暂停向 VAD 喂帧（采集继续，帧丢弃）
            return
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

    async def _end_asr(self, *, commit: bool, target: str) -> str:
        if not self._asr_active or self._asr_input is None:
            return ""
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
        return text

    async def _commit(self, text: str, target: str) -> None:
        self._on_asr_partial("")  # final 已提交，清空输入区回显
        await self._on_text_input(text, target)

    def _schedule_commit(self, text: str, target: str) -> None:
        """后台提交 PTT 文本；停止聆听不能等待模型或工具回合。"""
        task = asyncio.create_task(self._commit(text, target), name="voice:commit")
        self._commit_tasks.add(task)

        def on_done(completed: asyncio.Task[None]) -> None:
            self._commit_tasks.discard(completed)
            if completed.cancelled():
                return
            try:
                completed.result()
            except Exception as exc:  # noqa: BLE001 - 真实提交失败必须可见
                logger.exception("语音提交失败")
                self._on_error(f"语音提交失败：{exc}")

        task.add_done_callback(on_done)

    # ------------------------------------------------------------ 上行：按键说话

    async def push_to_talk_start(self, target: str = "character") -> None:
        """按下说话键：先停 TTS，再开 ASR 会话直录（无 pre-roll）。"""
        await self.stop_speaking_async()
        self._ptt_target = target
        self._ptt_active = True
        self._on_vad_state("speech_started")
        await self._begin_asr(pre_roll=False)

    async def push_to_talk_stop(self) -> None:
        """结束聆听：收尾识别，文本提交交给后台，不等待模型回合。"""
        if not self._ptt_active:
            return
        self._ptt_active = False
        text = await self._end_asr(commit=False, target=self._ptt_target)
        if text:
            self._schedule_commit(text, self._ptt_target)

    # ------------------------------------------------------------ 下行：TTS

    def on_message(self, message: Message) -> None:
        """消息监听入口（由 Orchestrator 在持久化后调用）。

        只有 ``tts_eligible`` 的 character.speech 全文入队；助手及其余来源
        一律静音。新角色完整消息抢占旧朗读。
        """
        if message.conversation_id != self._conversation_id:
            return
        if message.pair_id != self._pair_config.pair_id:
            return
        if not is_tts_eligible(message.source, message.kind):
            return
        self._enqueue_for_playback(message, preempt=True)

    def replay_message(self, message: Message) -> None:
        """逐条朗读（voice.tts_play）：用户主动指定重播，无视 tts_eligible。

        用户与角色消息用角色音色全文朗读；不可读文本（省略号、纯标点）
        仍被过滤。助手消息不朗读。
        """
        if message.conversation_id != self._conversation_id:
            return
        if message.pair_id != self._pair_config.pair_id:
            return
        if message.source == MessageSource.ASSISTANT:
            return
        # 用户主动重播：排队播放，不抢占正在朗读的当前句。
        self._enqueue_for_playback(message, preempt=False)

    def enqueue_text(self, text: str, *, voice_id: str | None = None) -> None:
        """直接按文本入队（voice.preview 试听）；voice_id 缺省取角色音色。

        有效音色为空（说话方未生成音色）时不入队，显式试听由命令层返回
        voice_not_provisioned。
        """
        text = text.strip()
        if not is_readable_text(text):
            return
        effective_voice = voice_id or self._pair_config.character.voice_id
        if not effective_voice:
            return
        self._queue.enqueue(
            SpeechRequest(text=text, voice_id=effective_voice, message_id="preview")
        )

    def _enqueue_for_playback(self, message: Message, *, preempt: bool) -> bool:
        """角色或用户消息全文入队。

        说话方有效音色为空时跳过该消息。preempt=True 时先递增 epoch 抢占
        旧朗读再入队；返回是否真的入队，未入队时不触发抢占，避免无音频却
        打断当前播放。
        """
        voice_id = self._pair_config.character.voice_id
        if not voice_id:
            return False
        text = message.text.strip()
        if not is_readable_text(text):
            return False
        if preempt:
            self.interrupt("new_message")
        self._queue.enqueue(
            SpeechRequest(text=text, voice_id=voice_id, message_id=message.message_id)
        )
        return True

    async def set_context_async(self, conversation_id: str, pair_config: PairConfig) -> None:
        """切换语音所属聊天与搭档，并抢占旧聊天的待播语音。

        PortAudio 停流在线程中完成，不阻塞 Sidecar 事件循环。
        """
        if (
            self._conversation_id == conversation_id
            and self._pair_config == pair_config
        ):
            return
        await self.interrupt_async("context_switch")
        self._conversation_id = conversation_id
        self._pair_config = pair_config

    async def stop_speaking_async(self, reason: str = "manual_stop") -> None:
        """停止播放并清空待播队列；PortAudio 停流在线程中完成。

        停止即一次中断：epoch 递增，旧 epoch 的迟到 PCM 永不写入；播放循环
        在下一个块检查时退出合成并重开 VAD。
        """
        await self.interrupt_async(reason)

    def interrupt(self, reason: str) -> str | None:
        """抢占桌面朗读：epoch 递增 → 清队列 → 停播放器。

        供新角色消息到达时的同步消息监听入口使用。返回被中断的
        message_id：优先正在播放的条目，否则队首待播条目，都没有时为
        None。只有确实存在播放或待播条目时才停播放器并发出
        voice.playback_interrupted，避免无音频时的假抢占反馈。
        """
        interrupted = self._interrupted_message_id()
        had_activity = self._queue.playing or self._queue.pending > 0
        self._queue.stop()
        self._skip = False
        self._current_message_id = None
        if not had_activity:
            return interrupted
        self._player.stop()
        self._on_interrupted(self._conversation_id, interrupted, reason)
        return interrupted

    async def interrupt_async(self, reason: str) -> str | None:
        """异步抢占：epoch 与队列立即生效，PortAudio 停流移出事件循环。"""
        interrupted = self._interrupted_message_id()
        had_activity = self._queue.playing or self._queue.pending > 0
        self._queue.stop()
        self._skip = False
        self._current_message_id = None
        if not had_activity:
            return interrupted
        await asyncio.to_thread(self._player.stop)
        self._on_interrupted(self._conversation_id, interrupted, reason)
        return interrupted

    def _interrupted_message_id(self) -> str | None:
        """被中断条目的 message_id：正在播放的优先，否则队首待播项。"""
        if self._queue.playing and self._current_message_id is not None:
            return self._current_message_id
        return self._queue.pending_message_id

    async def skip_playing_async(self) -> None:
        """跳过当前句：epoch 递增放弃当前合成，继续播队列下一句。

        当前句的迟到 PCM 不得写入，待播项改挂新 epoch，不清空队列。队列
        已空时播放循环自然停止（tts 回 idle、VAD 重开）；未在播放时无句
        可跳。PortAudio 停流在线程中完成。
        """
        if not self._queue.playing:
            return
        self._queue.skip_current()
        self._current_message_id = None
        self._skip = True
        await asyncio.to_thread(self._player.stop)
        self._on_tts_state("skipping")

    async def run_playback_loop(self) -> None:
        """消费 SpeechQueue：合成 → 写入长期输出流；stop/skip 中断当前合成。"""
        while True:
            request = self._queue.pop_next()
            if request is None:
                await asyncio.sleep(0.05)
                continue
            # 出队瞬间的 epoch：本次播放只写该 epoch 的 PCM。
            epoch = self._queue.epoch
            self._current_message_id = request.message_id
            self._queue.begin_playback()
            self._on_vad_state("playing")
            # 出队开始合成置 synthesizing，首个 PCM 块写入播放器才置 playing
            self._on_tts_state("synthesizing")
            try:
                await self._play_request(request, epoch)
                # 合成迭代器结束时，播放器输出缓冲可能仍有音频。等实际
                # 输出排空后再回到 idle，停止按钮覆盖真实播报阶段。
                if self._queue.playing and not self._skip:
                    await self._wait_for_player_drain()
            except Exception as exc:  # noqa: BLE001 - TTS 失败降级为静音提示
                self._tts_failed = True
                self._on_tts_state("failed")
                self._on_error(f"语音合成失败：{exc}")
                # 合成失败停止消费队列：清空待播项并保持 failed 状态，等待
                # 用户重播或下一条新消息，避免连发失败。
                self._queue.stop()
            skipped = self._skip
            self._skip = False
            self._queue.end_playback()
            self._current_message_id = None
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
        await asyncio.to_thread(self._player.wait_until_idle)

    async def _play_request(self, request: SpeechRequest, epoch: int) -> None:
        """合成一条请求并把 PCM 写入播放器；epoch/stop/skip 由块循环检查。"""
        agen = self._synthesizer.synthesize(request)
        wrote_first_block = False
        try:
            async for chunk in agen:
                if chunk.final:
                    break
                if epoch != self._queue.epoch:
                    # 抢占或跳过之后旧 epoch 的迟到分片一律丢弃
                    break
                if not self._queue.playing:
                    # 停止已清队列并复位 playing：中断合成
                    break
                if self._skip:
                    # 跳过：放弃当前句，改播队列下一句
                    break
                if chunk.pcm:
                    if not wrote_first_block:
                        # 首个 PCM 块写入播放器才算真正出声
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
