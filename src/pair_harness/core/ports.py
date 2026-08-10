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


class CodingEngine(ABC):
    @abstractmethod
    async def open_session(
        self,
        project: ProjectRef,
        stored_ref: EngineSessionRef | None = None,
        *,
        approval_policy: str | None = None,
        sandbox: str | None = None,
        approvals_reviewer: str | None = None,
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

