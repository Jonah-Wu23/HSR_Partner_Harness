from __future__ import annotations

from collections.abc import Mapping as ABCMapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=True)


def _normalize_unicode(value: Any) -> Any:
    """把字符串中的孤立 UTF-16 代理字符替换为 Unicode replacement character。"""
    if isinstance(value, str):
        if not any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            return value
        # surrogatepass 保留成对代理，随后由 decode 合并；孤立代理由
        # errors="replace" 转成可安全序列化的 U+FFFD。
        return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    if isinstance(value, ABCMapping):
        return {
            _normalize_unicode(key): _normalize_unicode(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_unicode(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_unicode(item) for item in value)
    return value


def enum_value(value: "MessageSource | MessageKind | str") -> str:
    """把枚举字段规范化为字符串值（O1.2）。

    FrozenModel 开启 use_enum_values 后字段运行时就是 str；
    这里兼容两种形态，保证入库与上屏统一使用枚举值而非枚举名。
    """
    return value.value if isinstance(value, Enum) else str(value)


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
    # O4.4：语义澄清——记录消息归属的引擎回合（engine turn）id；
    # 与 MessageSource/MessageKind 一样只是展示与溯源元数据，
    # 并非聊天轮次号（曾用名 turn_id 易与对话轮次混淆）。
    engine_turn_id: str | None = None
    source: MessageSource
    kind: MessageKind
    text: str = ""
    # O4.4：payload 声明为只读映射——frozen 模型只冻结字段本身，
    # 内容仍是 dict；约定只读不修改，需要改写时先拷贝
    # （orchestrator 以 model_copy(update=...) 或 dict() 拷贝后修改）。
    payload: Mapping[str, Any] = Field(default_factory=dict)
    tts_eligible: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("text", "payload", mode="before")
    @classmethod
    def normalize_unicode(cls, value: Any) -> Any:
        return _normalize_unicode(value)


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
    # 供应商实际返回、允许展示的思考文本。正文与思考分开持久化和渲染；
    # 不返回思考字段的供应商保持空字符串。
    reasoning: str = ""


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
    progress_summary: "CharacterProgressSummary | None" = None
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
    # O2.4：修改来源——用户直接指令（最高优先级）或角色建议，
    # 便于编排器区分“用户发给助手的新指令”与角色生成的修改。
    origin: Literal["user", "character"] = "character"


class EngineEventType(str, Enum):
    TURN_STARTED = "turn.started"
    ASSISTANT_DELTA = "assistant.delta"
    ASSISTANT_REASONING_DELTA = "assistant.reasoning.delta"
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
    # O4.4：payload 约定只读（Mapping），需要改写时先拷贝再 model_copy
    payload: Mapping[str, Any] = Field(default_factory=dict)


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


class CharacterProgressSummary(FrozenModel):
    """O3.3：执行期间注入角色的压缩进度摘要（设计 §3.2/§9）。

    只含中性描述：当前步骤简述、已完成步骤数、状态；不含原始命令、
    文件路径与工具输出原文。
    """

    current_step: str = "任务准备中"
    completed_steps: int = Field(default=0, ge=0)
    total_steps: int | None = Field(default=None, ge=0)
    status: Literal["running"] = "running"


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
    # O4.4：不可变元组（构造时传 list 会被 pydantic 自动收敛为 tuple），
    # 与 frozen 模型语义一致，避免调用方事后就地修改
    paths: tuple[str, ...] = ()
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
