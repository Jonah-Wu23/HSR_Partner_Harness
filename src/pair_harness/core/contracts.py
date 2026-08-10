from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=True)


class MessageSource(str, Enum):
    USER = "user"
    CHARACTER = "character"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class MessageKind(str, Enum):
    USER_TEXT = "user.text"
    CHARACTER_SPEECH = "character.speech"
    ASSISTANT_NATURAL_LANGUAGE = "assistant.natural_language"
    TOOL_RECORD = "tool.record"
    SYSTEM_STATUS = "system.status"
    APPROVAL = "system.approval"
    CODE = "assistant.code"
    COMMAND = "assistant.command"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AMENDMENT_PENDING = "amendment_pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Message(FrozenModel):
    message_id: str = Field(default_factory=new_id)
    conversation_id: str
    pair_id: str
    turn_id: str | None = None
    source: MessageSource
    kind: MessageKind
    text: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    tts_eligible: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class TaskRequestDraft(FrozenModel):
    instructions: str = Field(min_length=1)
    constraints: tuple[str, ...] = ()


class TaskAmendmentDraft(FrozenModel):
    instructions: str = Field(min_length=1)
    target_task_id: str | None = None
    revision: int | None = Field(default=None, ge=1)


DelegationDraft = TaskRequestDraft | TaskAmendmentDraft


class CharacterTurn(FrozenModel):
    speech: str
    delegation: DelegationDraft | None = None


class DialogueEvent(FrozenModel):
    type: Literal["speech.delta", "character.final"]
    delta: str | None = None
    turn: CharacterTurn | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "DialogueEvent":
        if self.type == "speech.delta" and self.delta is None:
            raise ValueError("speech.delta requires delta")
        if self.type == "character.final" and self.turn is None:
            raise ValueError("character.final requires turn")
        return self


class DialogueRequest(FrozenModel):
    pair_id: str
    conversation_id: str
    user_message: Message
    recent_messages: tuple[Message, ...] = ()
    progress_summary: str | None = None
    result_summary: "CharacterResultSummary | None" = None


class ProjectRef(FrozenModel):
    project_id: str
    name: str
    root_path: str


class TaskRequest(FrozenModel):
    task_id: str = Field(default_factory=new_id)
    conversation_id: str
    origin_message_id: str
    instructions: str = Field(min_length=1)
    constraints: tuple[str, ...] = ()
    revision: int = Field(default=0, ge=0)


class TaskAmendment(FrozenModel):
    amendment_id: str = Field(default_factory=new_id)
    target_task_id: str
    origin_message_id: str
    revision: int = Field(ge=1)
    instructions: str = Field(min_length=1)


class EngineEventType(str, Enum):
    TURN_STARTED = "turn.started"
    ASSISTANT_DELTA = "assistant.delta"
    ASSISTANT_FINAL = "assistant.final"
    TOOL_STARTED = "tool.started"
    TOOL_PROGRESS = "tool.progress"
    TOOL_FINISHED = "tool.finished"
    FILE_PATCH = "file.patch"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"


class EngineEvent(FrozenModel):
    event_id: str = Field(default_factory=new_id)
    conversation_id: str
    task_id: str
    engine_turn_id: str
    sequence: int = Field(ge=0)
    type: EngineEventType
    tool_call_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolRun(FrozenModel):
    tool_call_id: str
    conversation_id: str
    task_id: str
    engine_turn_id: str
    sequence: int = Field(ge=0)
    status: Literal["running", "succeeded", "failed", "denied"]
    title: str
    summary: str = ""
    details: str = ""


class EngineSessionRef(FrozenModel):
    engine_type: str
    opaque_ref: str


class ExecutionReceipt(FrozenModel):
    task_id: str
    engine_turn_id: str
    status: Literal["completed", "failed", "cancelled"]
    summary: str
    changed_files: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    pending_questions: tuple[str, ...] = ()


class CharacterResultSummary(FrozenModel):
    task_id: str
    status: Literal["completed", "failed", "cancelled"]
    summary: str
    user_visible_changes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    pending_questions: tuple[str, ...] = ()


class ApprovalMode(str, Enum):
    REQUEST_APPROVAL = "request_approval"
    REVIEW = "review"
    FULL_AUTO = "full_auto"


class ApprovalDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_FOR_CONVERSATION = "allow_for_conversation"
    DENY = "deny"


class ReviewerVerdict(FrozenModel):
    allow: bool
    reason: str = ""
    suggestion: str = ""


class PendingOperation(FrozenModel):
    """一次等待沙箱与审批检查的工具操作。"""

    tool_kind: Literal["file_write", "file_delete", "shell", "patch"]
    command: str | None = None
    paths: list[str] = Field(default_factory=list)
    patch_file_count: int | None = None
    summary: str = ""


class AsrEvent(FrozenModel):
    type: Literal["partial", "final", "error"]
    text: str = ""
    error: str | None = None


class AudioChunk(FrozenModel):
    pcm: bytes
    sample_rate: int = 16_000
    channels: int = 1
    final: bool = False


class SpeechRequest(FrozenModel):
    text: str
    voice_id: str
    message_id: str


class VadEvent(FrozenModel):
    type: Literal["listening", "speech_started", "speech_ended", "false_trigger"]


DialogueRequest.model_rebuild()

