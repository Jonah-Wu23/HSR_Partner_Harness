from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from .contracts import (
    ApprovalDecision,
    ApprovalMode,
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
from .repository import ConversationSnapshot


class DialogueModel(ABC):
    @abstractmethod
    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        if False:
            yield

    async def aclose(self) -> None:
        """释放对话模型持有的资源（如自建 HTTP client）。

        注入外部 client 的适配器应把关闭留给调用方；默认实现不做任何事。
        """
        return

    @abstractmethod
    async def generate_title(
        self, *, pair_id: str, context: tuple[Message, ...]
    ) -> str:
        """用助手身份为首次完整回复后的聊天生成一个短标题。

        请求失败或模型没有给出可用标题时抛出异常，异常信息带原始原因。
        """
        raise NotImplementedError

    @abstractmethod
    async def generate_summary(
        self, *, pair_id: str, assistant_prompt: str, context_text: str
    ) -> dict[str, Any]:
        """用配置的真实模型生成聊天摘要结构化对象。

        返回的字典由模型负责，调用方只校验结构与身份，不改写语义。
        请求失败或正文不是 JSON 对象时抛出异常，异常信息带原始原因。
        """
        raise NotImplementedError

    @abstractmethod
    async def complete_json(
        self, *, system: str, user: str, max_tokens: int
    ) -> dict[str, Any]:
        """发送一次非流式请求，要求模型只输出一个 JSON 对象并返回解析结果。

        审查、标题与摘要共用这个接口。请求失败、响应为空或正文不是 JSON
        对象时抛出异常，异常信息带原始原因。
        """
        raise NotImplementedError


class CodingEngine(ABC):
    @abstractmethod
    async def open_session(
        self,
        project: ProjectRef,
        stored_ref: EngineSessionRef | None = None,
        *,
        approval_mode: ApprovalMode,
        developer_instructions: str | None = None,
    ) -> EngineSessionRef:
        """打开（或恢复）引擎会话。

        ``approval_mode`` 是当前任务的审批模式。沙箱与审批裁决由编排器负责：
        引擎在任何审批模式下都要在工具执行前发出 APPROVAL_REQUESTED，
        等待 ``resolve_approval`` 的裁决后再执行或放弃该工具。
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        """释放引擎持有的资源（如 transport 与子进程）；默认实现不做任何事。"""
        return

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
    def load_conversation(self, conversation_id: str) -> ConversationSnapshot:
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
