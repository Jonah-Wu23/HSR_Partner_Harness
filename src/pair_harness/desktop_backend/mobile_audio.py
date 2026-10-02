# 手机远程语音的服务端逻辑：上行转写会话与下行 TTS 分片编目，不碰网络与应用服务。

from __future__ import annotations

import asyncio
import base64
import binascii
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pair_harness.core.contracts import AsrEvent

# 下行 PCM 的 MIME 类型，与桌面 AudioPlayer 同规格
TTS_MIME = "audio/pcm;rate=24000"

# 转写输入流结束哨兵
_ASR_END: object = object()


class MobileAudioError(ValueError):
    """手机语音的协议与会话错误；``code`` 是返回给手机端的错误码。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message if message else code)
        self.code = code


class RecognizerPort(Protocol):
    """流式识别器接口，与 ``QwenStreamingRecognizer.stream_transcribe`` 一致。

    音频流结束后产出 partial / final / error 事件；final 只在文本非空时产出。
    """

    def stream_transcribe(
        self, audio_stream: AsyncIterable[bytes]
    ) -> AsyncIterator[AsrEvent]: ...


@dataclass
class _AsrSession:
    session_id: str
    conversation_id: str
    connection_key: str
    queue: asyncio.Queue[bytes | object] = field(default_factory=asyncio.Queue)
    expected_seq: int = 0
    cancelled: bool = False  # 静默取消：不再回调任何转写
    final_text: str = ""
    error: str | None = None
    task: asyncio.Task[None] | None = None


class MobileAsrSessionManager:
    """上行转写会话（voice.mobile_ptt_start / audio_chunk / ptt_stop）。

    每个会话是主事件循环里的一个任务，驱动识别器的 ``stream_transcribe``；
    DashScope SDK 在自有线程回调，由识别器适配器经 ``call_soon_threadsafe``
    送回该循环，本类全部方法都在事件循环线程调用。同一 conversation 同时
    只允许一个活动会话；连接断开时静默取消该连接的全部会话。
    """

    def __init__(
        self,
        *,
        on_transcript: Callable[[str, str, str, bool], None],
    ) -> None:
        # on_transcript(conversation_id, session_id, text, is_final)
        self._on_transcript = on_transcript
        self._sessions: dict[str, _AsrSession] = {}
        # 已取消会话的识别任务仍在后台收尾，这里持有引用直到任务结束。
        self._tasks: set[asyncio.Task[None]] = set()

    def start_session(
        self,
        conversation_id: str,
        connection_key: str,
        recognizer_factory: Callable[[], RecognizerPort],
    ) -> str:
        """登记新转写会话并启动识别任务，返回 ``session_id``。"""
        if any(s.conversation_id == conversation_id for s in self._sessions.values()):
            raise MobileAudioError(
                "voice_session_exists", "该会话已有进行中的语音转写"
            )
        recognizer = recognizer_factory()
        session = _AsrSession(
            session_id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            connection_key=connection_key,
        )
        session.task = asyncio.create_task(
            self._pump(session, recognizer),
            name=f"voice-asr-{session.session_id[:8]}",
        )
        self._tasks.add(session.task)
        session.task.add_done_callback(self._tasks.discard)
        self._sessions[session.session_id] = session
        return session.session_id

    def feed_chunk(self, session_id: str, seq: int, data_base64: str) -> None:
        """喂入一个 PCM 分片（base64 编码的 s16le 16kHz 单声道）。

        ``seq`` 从 0 严格递增；跳号抛 ``voice_audio_seq_gap`` 且不消耗序号。
        """
        session = self._live_session(session_id)
        try:
            pcm = base64.b64decode(data_base64, validate=True)
        except binascii.Error:
            raise MobileAudioError(
                "voice_audio_invalid_base64", "音频分片不是合法 base64"
            ) from None
        if seq != session.expected_seq:
            raise MobileAudioError(
                "voice_audio_seq_gap",
                f"音频分片序号跳号：期望 {session.expected_seq}，实际 {seq}",
            )
        session.expected_seq += 1
        session.queue.put_nowait(pcm)

    async def end_session(self, session_id: str) -> tuple[str, str]:
        """结束识别并等待收尾，回调 final 转写，返回 ``(conversation_id, 文本)``。

        文本可能为空串，由调用方决定是否报 ``voice_transcript_empty``；
        识别器报错时抛 ``voice_asr_failed``。
        """
        session = self._live_session(session_id)
        del self._sessions[session_id]
        session.queue.put_nowait(_ASR_END)
        assert session.task is not None
        await session.task
        if session.error is not None:
            raise MobileAudioError("voice_asr_failed", session.error)
        self._on_transcript(session.conversation_id, session_id, session.final_text, True)
        return session.conversation_id, session.final_text

    def cancel_session(self, session_id: str) -> str | None:
        """静默取消（连接断开或超时），返回 conversation_id；未知会话返回 None。

        识别器在后台收到流结束后自行收尾，不阻塞调用方。
        """
        session = self._sessions.pop(session_id, None)
        if session is None:
            return None
        session.cancelled = True
        session.queue.put_nowait(_ASR_END)
        return session.conversation_id

    def cancel_all_for_connection(self, connection_key: str) -> list[str]:
        """静默取消某连接的全部会话，返回被取消的 session_id。"""
        session_ids = [
            sid for sid, s in self._sessions.items() if s.connection_key == connection_key
        ]
        for session_id in session_ids:
            self.cancel_session(session_id)
        return session_ids

    def _live_session(self, session_id: str) -> _AsrSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise MobileAudioError(
                "voice_session_not_found", "转写会话不存在或已结束"
            )
        return session

    async def _pump(self, session: _AsrSession, recognizer: RecognizerPort) -> None:
        try:
            async for event in recognizer.stream_transcribe(_feed_stream(session.queue)):
                self._on_asr_event(session, event)
        except Exception as exc:  # noqa: BLE001 - 识别器异常由 end_session 以 voice_asr_failed 抛出
            if session.error is None:
                session.error = f"语音识别异常：{exc}"

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


@dataclass
class TtsStream:
    """一条下行 TTS 消息的分片编目。

    ``stopped`` 由 :meth:`MobileTtsSequencer.stop` 置位；生产者在下发每个分片
    和结束事件前自查，置位后停止下发。
    """

    message_id: str
    conversation_id: str
    next_seq: int = 0
    stopped: bool = False

    def chunk(self, pcm: bytes) -> dict[str, Any]:
        """返回 ``voice.mobile_tts_chunk`` 载荷，``seq`` 从 0 递增。"""
        seq = self.next_seq
        self.next_seq += 1
        return {
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "seq": seq,
            "mime": TTS_MIME,
            "data": base64.b64encode(pcm).decode("ascii"),
        }

    def end_payload(self) -> dict[str, str]:
        """返回 ``voice.mobile_tts_end`` 载荷。"""
        return {"conversation_id": self.conversation_id, "message_id": self.message_id}


class MobileTtsSequencer:
    """按 message_id 登记进行中的下行 TTS 消息，供手机端停止与新回复抢占时中断。"""

    def __init__(self) -> None:
        self._streams: dict[str, TtsStream] = {}

    def begin(self, message_id: str, conversation_id: str) -> TtsStream:
        """登记并返回句柄；同一 message_id 仍在下发时抛 ``voice_tts_message_exists``。"""
        if message_id in self._streams:
            raise MobileAudioError(
                "voice_tts_message_exists", f"TTS 消息已存在：{message_id}"
            )
        stream = TtsStream(message_id=message_id, conversation_id=conversation_id)
        self._streams[message_id] = stream
        return stream

    def stop(self, message_id: str) -> None:
        """中断进行中的消息；未知或已结束的 message_id 直接返回。"""
        stream = self._streams.pop(message_id, None)
        if stream is not None:
            stream.stopped = True

    def finish(self, stream: TtsStream) -> None:
        """生产者结束（完成、失败或被中断）后注销句柄。"""
        if self._streams.get(stream.message_id) is stream:
            del self._streams[stream.message_id]
