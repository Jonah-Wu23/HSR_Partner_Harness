from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from .contracts import (
    ApprovalDecision,
    AsrEvent,
    AudioChunk,
    DialogueEvent,
    DialogueRequest,
    EngineEvent,
    EngineSessionRef,
    Message,
    PendingOperation,
    ProjectRef,
    ReviewerVerdict,
    SpeechRequest,
    TaskAmendment,
    TaskRequest,
    ToolRun,
    VadEvent,
)


class DialogueModel(ABC):
    @abstractmethod
    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        if False:
            yield

    async def aclose(self) -> None:
        """O3.2：释放对话模型持有的资源（如自建 HTTP client）。

        注入外部 client 的适配器应把关闭留给调用方；默认实现不做任何事。
        """
        return

    async def generate_title(
        self, *, pair_id: str, context: tuple[Message, ...]
    ) -> str | None:
        """用助手身份为首次完整回复后的聊天生成一个短标题。"""
        del pair_id, context
        return None


class CodingEngine(ABC):
    native_preexecution_approval: bool = False

    @abstractmethod
    async def open_session(
        self,
        project: ProjectRef,
        stored_ref: EngineSessionRef | None = None,
        *,
        approval_policy: str | None = None,
        sandbox: str | None = None,
        approvals_reviewer: str | None = None,
        developer_instructions: str | None = None,
    ) -> EngineSessionRef:
        """打开（或恢复）引擎会话。

        O3.1：``approval_policy``/``sandbox``/``approvals_reviewer`` 是
        app-server 策略映射的预留位置（thread/start 的 approvalPolicy /
        sandbox / approvalsReviewer 字段），B1 联调时由编排器按审批模式
        与沙箱配置传入；None 表示不设置，交给引擎默认值。
        """
        raise NotImplementedError

    @abstractmethod
    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        if False:
            yield

    @abstractmethod
    async def cancel_turn(self, session_ref: EngineSessionRef, turn_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def amend_turn(
        self,
        session_ref: EngineSessionRef,
        engine_turn_id: str,
        amendment: TaskAmendment,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def resolve_approval(
        self,
        session_ref: EngineSessionRef,
        approval_id: str,
        decision: ApprovalDecision,
    ) -> None:
        raise NotImplementedError


class StateStore(ABC):
    @abstractmethod
    def save_message(self, message: Message) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_tool_run(self, tool_run: ToolRun) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_engine_session(self, conversation_id: str, session_ref: EngineSessionRef) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_conversation(self, conversation_id: str) -> dict[str, Any]:
        raise NotImplementedError

    # ---- V0.3.9 普通增量缓冲（contract-v1 第 4 节）----
    # 批量实现（SQLiteStore）把普通增量合并成 50 条 / 50ms 的事务；
    # 这里给出的默认实现没有缓冲，直接同步落库并让 flush 成为空操作。
    # 默认实现不会丢数据，只是不做批量合并，因此端口替换仍然安全。

    def enqueue_message(self, message: Message) -> None:
        """普通增量入队；默认实现直接同步落库。"""
        self.save_message(message)

    def enqueue_tool_run(self, tool_run: ToolRun) -> None:
        """普通增量入队；默认实现直接同步落库。"""
        self.save_tool_run(tool_run)

    def flush(self) -> int:
        """强制刷盘挂起的普通增量；默认实现无缓冲，返回 0。"""
        return 0

    def flush_if_due(self, now: float | None = None) -> bool:
        """按阈值刷盘；默认实现无缓冲，返回 False。"""
        del now
        return False

    def next_flush_deadline(self, now: float | None = None) -> float | None:
        """下一个刷盘截止时间；默认实现无缓冲，返回 None。"""
        del now
        return None


class Reviewer(ABC):
    @abstractmethod
    async def review(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict:
        raise NotImplementedError


class SpeechRecognizer(ABC):
    @abstractmethod
    async def stream_transcribe(self, audio_stream: AsyncIterable[bytes]) -> AsyncIterator[AsrEvent]:
        if False:
            yield


class SpeechSynthesizer(ABC):
    @abstractmethod
    async def synthesize(self, request: SpeechRequest) -> AsyncIterator[AudioChunk]:
        if False:
            yield


class VoiceActivityDetector(ABC):
    @abstractmethod
    async def detect(self, pcm_stream: AsyncIterable[bytes]) -> AsyncIterator[VadEvent]:
        if False:
            yield
