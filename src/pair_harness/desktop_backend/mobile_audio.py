"""手机远程语音的服务端纯逻辑模块（V0.3.5）。

契约：``docs/plans/V0.3.5-契约冻结.md`` §5（手机语音）。

本模块只做纯逻辑：不 import aiohttp、不碰网络、不碰
``pair_harness.desktop_backend.application_service``。Qwen 识别器经
``recognizer_factory`` 注入（:class:`RecognizerPort` 与
``adapters/audio/qwen_asr.py`` 的 ``QwenStreamingRecognizer`` 真实接口
对齐，见 :meth:`RecognizerPort.stream_transcribe`），单测使用注入的 fake
recognizer，不发网络请求。

上行（§5.1）：:class:`MobileAsrSessionManager` 管理
``voice.mobile_ptt_start`` / ``voice.mobile_audio_chunk`` /
``voice.mobile_ptt_stop`` 对应的转写会话；``on_transcript`` 对应
``voice.mobile_transcript`` 事件（partial 与 final 都发，is_final 区分）。
说话结束判定在手机端（§5.1），本模块不实现 VAD。

下行（§5.2）：:class:`MobileTtsSequencer` 为
``voice.mobile_tts_chunk`` / ``voice.mobile_tts_end`` 事件编目分片序号、
MIME 与 base64；``stop`` 对应 ``voice.mobile_tts_stop`` 的中断语义。

实现说明：真实识别器接口是异步生成器（``stream_transcribe``），而本模块
对外 API 是同步方法（``feed_chunk`` / ``end_session`` 按 §5.1 命令处理
路径设计）。每个会话由专用后台线程上的独立事件循环（``asyncio.run``）
驱动识别器，同步 API 因此可在任意线程调用而不会与识别器互相死锁；识别器
事件在泵线程内被消费并回调。注意：``on_transcript`` 回调运行在会话泵线程，
集成方如需回到主事件循环须自行切换（如 ``loop.call_soon_threadsafe``）；
``end_session`` 会阻塞到识别器收尾（真实适配器尾部超时约 5s），集成方应
避免在无独立线程的路径上长期等待。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import threading
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pair_harness.core.contracts import AsrEvent

#: 下行 PCM 的 MIME 类型（契约 §5.2，与桌面 AudioPlayer 同规格）
TTS_MIME = "audio/pcm;rate=24000"

#: 转写输入流结束/取消哨兵
_ASR_END: object = object()


class MobileAudioError(ValueError):
    """手机音频域错误；``code`` 为错误码（契约 §5.3 的语义）。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message if message else code)
        self.code = code


class MobileTtsInterrupted(asyncio.CancelledError):
    """正在下发的 TTS 消息被 ``stop()`` 回收（抢占或手机端停止）。

    这不是失败：抢占与停止是正常控制流，生产者应停止下发。继承
    ``asyncio.CancelledError`` 是为了复用调用方既有的取消语义——中继任务在
    ``except asyncio.CancelledError: raise`` 路径静默收尾，不广播
    ``voice.mobile_tts_failed``（V039-S4-018）。未知 ``message_id`` 仍按
    协议错误抛 ``MobileAudioError("voice_tts_message_not_found")``。
    """

    def __init__(self, message_id: str) -> None:
        super().__init__(f"TTS 消息已中断：{message_id}")
        self.message_id = message_id


class RecognizerPort(Protocol):
    """与 ``qwen_asr.QwenStreamingRecognizer`` 真实接口对齐的端口。

    真实签名（``src/pair_harness/adapters/audio/qwen_asr.py``，
    ``QwenStreamingRecognizer.stream_transcribe``）：:

        async def stream_transcribe(
            self, audio_stream: AsyncIterable[bytes]
        ) -> AsyncIterator[AsrEvent]:

    语义（以真实实现为准）：消费完 ``audio_stream``（本模块以结束哨兵
    代表流终止，对应真实适配器 ``stop()`` 收尾）后，按
    ``AsrEvent(type="partial"|"final"|"error")`` 序列产出；
    final 仅在文本非空时产出；出错时产出 ``type="error"``。
    """

    async def stream_transcribe(
        self, audio_stream: AsyncIterable[bytes]
    ) -> AsyncIterator[AsrEvent]:
        ...


@dataclass
class _AsrSession:
    session_id: str
    conversation_id: str
    connection_key: str
    recognizer: RecognizerPort
    expected_seq: int = 0
    stopped: bool = False  # end/cancel 已发起，不再接收分片
    cancelled: bool = False  # cancel：静默清理，不发事件
    final_text: str = ""
    error: str | None = None
    loop: asyncio.AbstractEventLoop | None = None  # 泵线程事件循环
    queue: asyncio.Queue[bytes | object] | None = None  # 泵线程绑定
    ready: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class MobileAsrSessionManager:
    """上行转写会话管理（契约 §5.1）。

    - 同一 ``conversation_id`` 同时只允许一个活动会话（重复
      ``start_session`` 抛 ``MobileAudioError("voice_session_exists")``）。
    - 同一 ``connection_key`` 允许多个会话并行。
    - 会话绑定发起连接；``cancel_all_for_connection`` 在连接断开时静默
      取消该连接的全部会话（§5.3）。
    - 本类的方法不保证并发调用同一会话的线程安全（单事件循环/单线程
      调用即可）；泵线程只读取会话字段并回调 ``on_transcript``。
    """

    def __init__(
        self,
        *,
        on_transcript: Callable[[str, str, str, bool], None],
    ) -> None:
        # on_transcript(conversation_id, session_id, text, is_final)
        self._on_transcript = on_transcript
        self._sessions: dict[str, _AsrSession] = {}
        self._conversation_ids: dict[str, str] = {}

    # ------------------------------------------------------------------ 生命周期

    def start_session(
        self,
        conversation_id: str,
        connection_key: str,
        recognizer_factory: Callable[[], RecognizerPort],
    ) -> str:
        """登记新转写会话，返回 ``session_id``（uuid hex）。

        ``recognizer_factory`` 在登记前调用；工厂异常原样抛出（无残留）。
        重复启动同一 conversation 抛 ``MobileAudioError``
        （code ``voice_session_exists``）。
        """
        if self._conversation_ids.get(conversation_id) in self._sessions:
            raise MobileAudioError(
                "voice_session_exists", "该会话已有进行中的语音转写"
            )
        recognizer = recognizer_factory()
        session_id = uuid.uuid4().hex
        session = _AsrSession(
            session_id=session_id,
            conversation_id=conversation_id,
            connection_key=connection_key,
            recognizer=recognizer,
        )
        self._sessions[session_id] = session
        self._conversation_ids[conversation_id] = session_id
        thread = threading.Thread(
            target=self._pump_worker,
            args=(session,),
            name=f"voice-asr-{session_id[:8]}",
            daemon=True,
        )
        session.thread = thread
        thread.start()
        return session_id

    def feed_chunk(self, session_id: str, seq: int, data_base64: str) -> None:
        """喂入一个 PCM 分片（``data`` = base64(PCM s16le 16kHz mono)）。

        会话不存在/已结束抛 ``MobileAudioError("voice_session_not_found")``；
        base64 非法抛 ``MobileAudioError("voice_audio_invalid_base64")``；
        ``seq`` 从 0 严格 +1 递增，跳号抛
        ``MobileAudioError("voice_audio_seq_gap")``（message 含期望与实际值，
        且不消耗序号）。解码后的字节交给会话的 recognizer（内部泵任务异步
        喂送）。
        """
        session = self._get_session(session_id)
        try:
            pcm = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise MobileAudioError(
                "voice_audio_invalid_base64", "音频分片不是合法 base64"
            ) from None
        if seq != session.expected_seq:
            raise MobileAudioError(
                "voice_audio_seq_gap",
                f"音频分片序号跳号：期望 {session.expected_seq}，实际 {seq}",
            )
        session.expected_seq += 1
        session.ready.wait()
        assert session.loop is not None and session.queue is not None
        session.loop.call_soon_threadsafe(session.queue.put_nowait, pcm)

    def end_session(self, session_id: str) -> str:
        """结束识别（对应 ``voice.mobile_ptt_stop``）。

        向识别器发流结束哨兵，等待收尾取得最终文本；回调
        ``on_transcript(..., is_final=True)``，清理会话，返回 final 文本。
        文本可能为空串——空串由调用方决定是否报 ``voice_transcript_empty``
        （§5.1），本模块如实返回并同样回调。识别器报错时抛
        ``MobileAudioError("voice_asr_failed")``（message 含底层错误）。
        """
        session = self._get_session(session_id)
        session.stopped = True
        self._remove_session(session)
        session.ready.wait()
        assert session.loop is not None and session.queue is not None
        session.loop.call_soon_threadsafe(session.queue.put_nowait, _ASR_END)
        session.done.wait()
        if session.error is not None:
            raise MobileAudioError("voice_asr_failed", session.error)
        text = session.final_text
        self._on_transcript(session.conversation_id, session_id, text, True)
        return text

    def cancel_session(self, session_id: str) -> None:
        """静默取消（连接断开/错误路径）：清理会话，不发任何事件。

        幂等：未知 ``session_id`` 直接返回。取消会向识别器发流结束哨兵，
        收尾在后台泵线程完成（daemon），不阻塞调用方。
        """
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        self._conversation_ids.pop(session.conversation_id, None)
        session.cancelled = True
        session.stopped = True
        if not session.done.is_set() and session.ready.is_set():
            try:
                session.loop.call_soon_threadsafe(  # type: ignore[union-attr]
                    session.queue.put_nowait, _ASR_END  # type: ignore[union-attr]
                )
            except RuntimeError:
                # 泵线程恰在收尾后关闭事件循环的竞态：会话已清理，无需再发哨兵
                pass

    def cancel_all_for_connection(self, connection_key: str) -> None:
        """取消某连接的全部会话（连接断开时调用；幂等，不发事件）。"""
        for session_id in [
            sid
            for sid, s in self._sessions.items()
            if s.connection_key == connection_key
        ]:
            self.cancel_session(session_id)

    # ------------------------------------------------------------------ 内部

    def _get_session(self, session_id: str) -> _AsrSession:
        session = self._sessions.get(session_id)
        if session is None or session.stopped:
            raise MobileAudioError(
                "voice_session_not_found", "转写会话不存在或已结束"
            )
        return session

    def _remove_session(self, session: _AsrSession) -> None:
        self._sessions.pop(session.session_id, None)
        if self._conversation_ids.get(session.conversation_id) == session.session_id:
            del self._conversation_ids[session.conversation_id]

    def _pump_worker(self, session: _AsrSession) -> None:
        # 泵线程：独立事件循环驱动识别器，与调用方线程互不阻塞
        asyncio.run(self._pump_async(session))

    async def _pump_async(self, session: _AsrSession) -> None:
        try:
            session.loop = asyncio.get_running_loop()
            queue: asyncio.Queue[bytes | object] = asyncio.Queue()
            session.queue = queue
            session.ready.set()
            if session.cancelled:
                queue.put_nowait(_ASR_END)
            async for event in session.recognizer.stream_transcribe(
                _feed_stream(queue)
            ):
                self._on_asr_event(session, event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 识别器异常必须如实记录
            if session.error is None:
                session.error = f"语音识别异常：{exc}"
        finally:
            session.ready.set()
            session.done.set()

    def _on_asr_event(self, session: _AsrSession, event: AsrEvent) -> None:
        if session.cancelled:
            return  # 静默取消不发事件
        if event.type == "partial":
            if event.text:
                self._on_transcript(
                    session.conversation_id, session.session_id, event.text, False
                )
        elif event.type == "final":
            session.final_text = event.text
        elif event.type == "error":
            if session.error is None:
                session.error = event.error or "语音识别失败"


async def _feed_stream(
    queue: asyncio.Queue[bytes | object],
) -> AsyncIterator[bytes]:
    """把队列里的 PCM 分片转成识别器消费的异步字节流；哨兵结束。"""
    while True:
        item = await queue.get()
        if item is _ASR_END:
            return
        yield item  # type: ignore[misc]


#: 已中断（stop）条目的保留上限：按唯一 message_id 记账，只保留最近这些
#: 墓碑，供尚未观察到取消的在途中继任务如实收尾；再早的中断记录按未知
#: message_id 处理（协议错误），不会无限增长。
_MAX_STOPPED_TTS_ENTRIES = 128


@dataclass
class _TtsEntry:
    message_id: str
    conversation_id: str
    next_seq: int = 0
    closed: bool = False
    stopped: bool = False


class MobileTtsSequencer:
    """下行 TTS 分片编目（契约 §5.2）。

    生命周期：``begin(message_id, conversation_id)`` → ``feed*`` →
    ``end``；``stop``（对应 ``voice.mobile_tts_stop``）随时中断。

    重入语义：
    - 重复 ``begin`` 同一 message_id 一律抛
      ``MobileAudioError("voice_tts_message_exists")``——包括被 ``stop``
      中断之后。**不支持在旧生产者可能仍在途时重用同一 message_id**：
      重用会让旧任务的 ``feed()`` 写进新一代条目（分片序号与内容错配）。
      生产路径上每条消息只中继一次、抢占用的是新消息的新 id，因此不需要重用；
      确实需要重发时请用新的 message_id。
    - ``end`` 幂等（重复调用返回相同 payload）；``end`` 后继续 ``feed`` →
      ``voice_tts_message_closed``；
    - ``stop`` 幂等（重复 stop 不重复记账）；被 ``stop`` 中断的
      message_id 继续 ``feed``/``end`` → ``MobileTtsInterrupted``
      （正常中断，不是协议错误）；
    - 未知 message_id 的 ``feed``/``end`` → ``voice_tts_message_not_found``
      （真实协议错误照旧暴露，不被中断语义吞掉）。

    单事件循环内使用即可，不要求线程安全（本类无后台线程）。
    """

    def __init__(self) -> None:
        self._entries: dict[str, _TtsEntry] = {}
        #: 已中断 message_id 的墓碑账（按唯一 id 计，先中断的在前；上限见
        #: _MAX_STOPPED_TTS_ENTRIES）。重复 stop 同一 id 不重复记账。
        self._stopped: dict[str, None] = {}

    def begin(self, message_id: str, conversation_id: str) -> None:
        """登记一条下行 TTS 消息（``conversation_id`` 在此传入）。

        同一 message_id 已登记过（进行中、已 ``end`` 或被 ``stop`` 中断）
        一律抛 ``voice_tts_message_exists``：中断墓碑仍在，说明旧生产者可能
        还会 ``feed()``，重用会把它写进新条目。
        """
        if message_id in self._entries:
            raise MobileAudioError(
                "voice_tts_message_exists", f"TTS 消息已存在：{message_id}"
            )
        self._entries[message_id] = _TtsEntry(
            message_id=message_id, conversation_id=conversation_id
        )

    def feed(self, message_id: str, pcm: bytes) -> dict[str, Any]:
        """喂入一个 PCM 分片，返回 ``voice.mobile_tts_chunk`` 事件 payload。

        ``seq`` 从 0 单调递增；``mime`` 固定 ``audio/pcm;rate=24000``；
        ``data`` = base64(pcm)。

        已被 ``stop`` 中断的消息抛 ``MobileTtsInterrupted``：生产者按正常
        中断收尾，不产生失败事件（V039-S4-018）。
        """
        entry = self._live_entry(message_id)
        if entry.closed:
            raise MobileAudioError(
                "voice_tts_message_closed", f"TTS 消息已结束：{message_id}"
            )
        seq = entry.next_seq
        entry.next_seq += 1
        return {
            "conversation_id": entry.conversation_id,
            "message_id": message_id,
            "seq": seq,
            "mime": TTS_MIME,
            "data": base64.b64encode(pcm).decode("ascii"),
        }

    def end(self, message_id: str) -> dict[str, str]:
        """结束一条 TTS 消息，返回 ``voice.mobile_tts_end`` 事件 payload。

        幂等：重复调用返回相同 payload。已被 ``stop`` 中断的消息抛
        ``MobileTtsInterrupted``（不得为已中断的合成补一个“完成”事件）。
        """
        entry = self._live_entry(message_id)
        entry.closed = True
        return {"conversation_id": entry.conversation_id, "message_id": message_id}

    def stop(self, message_id: str) -> None:
        """中断（``voice.mobile_tts_stop``）：标记条目已中断，不再接受 ``feed``。

        幂等：未知 message_id 直接返回（不制造“已中断”记录——未知仍是未知，
        不把真实协议错误变成静默中断）。

        条目保留为墓碑而不再立即删除：抢占旧消息时上层先 ``task.cancel()`` 再
        ``stop()``，而取消可能被已就绪的等待吞掉（Python 3.11
        ``asyncio.wait_for`` 在 future 已完成时返回结果而不抛
        ``CancelledError``），在途的中继任务因此还会走到下一次
        ``feed()``/``end()``。此时必须按“已中断”如实收尾，而不是报
        “消息不存在”并被上层记成合成失败（V039-S4-018）。

        重复 stop 同一 id 幂等：墓碑按唯一 message_id 记账，不会因为重复
        调用而挤掉其他仍在窗口内的中断记录。
        """
        entry = self._entries.get(message_id)
        if entry is None or entry.stopped:
            return
        entry.stopped = True
        self._stopped[message_id] = None
        self._prune_stopped()

    def _live_entry(self, message_id: str) -> _TtsEntry:
        """取在进行中的条目；未知消息 = 协议错误，已中断 = 正常中断。"""
        entry = self._entries.get(message_id)
        if entry is None:
            raise MobileAudioError(
                "voice_tts_message_not_found", f"TTS 消息不存在：{message_id}"
            )
        if entry.stopped:
            raise MobileTtsInterrupted(message_id)
        return entry

    def _prune_stopped(self) -> None:
        """限制“已中断”墓碑数量：超限后最早的按未知 message_id 处理。"""
        while len(self._stopped) > _MAX_STOPPED_TTS_ENTRIES:
            oldest = next(iter(self._stopped))
            del self._stopped[oldest]
            entry = self._entries.get(oldest)
            if entry is not None and entry.stopped:
                del self._entries[oldest]
