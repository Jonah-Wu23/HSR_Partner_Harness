from __future__ import annotations

from collections.abc import Mapping as ABCMapping
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def next_created_at(after: datetime | None) -> datetime:
    """严格单调的消息创建时间戳：不早于 *after*，相同则前进 1µs。

    同一回合内多条消息可能落在同一个微秒；持久化按 (created_at,
    message_id) 排序，并列时间戳会让恢复后的顺序由随机的 message_id
    决定，与内存创建顺序不一致（重开聊天会看到顺序交换）。
    """
    now = utc_now()
    if after is not None and now <= after:
        return after + timedelta(microseconds=1)
    return now


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
    """把枚举字段规范化为字符串值。

    FrozenModel 开启 use_enum_values 后字段运行时就是 str，直接构造的
    枚举成员取其 value，入库与上屏统一使用枚举值。
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
    # 摘要与记忆状态走非消息状态条展示。system.summary 只承载摘要记录，
    # system.error 只承载真实消息级错误；两者都不得承载隐藏提示。
    SYSTEM_SUMMARY = "system.summary"
    SYSTEM_ERROR = "system.error"
    CODE = "assistant.code"
    COMMAND = "assistant.command"


class MessageTarget(str, Enum):
    """消息空间归属：这条消息是发给角色还是助手。

    用户消息在提交时标记目标；角色、助手消息按来源继承默认目标
    （character→character，assistant/tool→assistant）。
    user+target=assistant 只进工作台。
    """

    CHARACTER = "character"
    ASSISTANT = "assistant"


class MessageOrigin(str, Enum):
    """消息来源语义：用户直发、角色委派产生或系统。

    委派任务通过 ``Message.delegation_id`` 连接角色区与工作台两侧。
    """

    USER = "user"
    CHARACTER_DELEGATION = "character_delegation"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    """消息生命周期状态（发送中→…→完成、失败或取消）。

    后端同步落库后返回真实 id 与初始状态，前端按 id 对账推进状态。
    """

    SENDING = "sending"
    QUEUED = "queued"
    RECEIVED = "received"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Message(FrozenModel):
    message_id: str = Field(default_factory=new_id)
    conversation_id: str
    pair_id: str
    # 消息归属的引擎回合（engine turn）id，只是展示与溯源元数据，
    # 不是聊天轮次号。
    engine_turn_id: str | None = None
    source: MessageSource
    kind: MessageKind
    text: str = ""
    # payload 约定只读：frozen 模型只冻结字段本身，需要改写时先拷贝，
    # 再用 model_copy(update=...) 生成新消息。
    payload: Mapping[str, Any] = Field(default_factory=dict)
    tts_eligible: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    # 消息空间归属与生命周期状态。target、origin、delegation_id 由编排器
    # 在创建消息时填写；status 由提交与处理路径推进。
    target: MessageTarget | None = None
    origin: MessageOrigin = MessageOrigin.USER
    delegation_id: str | None = None
    status: MessageStatus = MessageStatus.DONE
    # 助手 segment 归属的任务与统一时间线序号，保存在 message_json 内；
    # 旧记录为 None，前端按旧版分组展示。
    task_id: str | None = None
    timeline_order: int | None = None

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


class MemoryDraft(FrozenModel):
    """角色本轮要求写入的长期记忆条目。

    content 是模型给出的 JSON 对象，代码不改写、不摘要、不截断；作用域
    由会话在持久化侧权威解析（account、project、pair、character_ref、
    assistant_identity 五分量），模型无法指定归属。要不要记、记什么
    完全由模型自己判断，代码只做协议一致性检查。
    """

    content: dict[str, Any] = Field(min_length=1)


class CharacterTurn(FrozenModel):
    speech: str
    delegation: DelegationDraft | None = None
    # 模型声明的长期记忆条目；空元组表示本轮没有要记的内容。
    memory: tuple[MemoryDraft, ...] = ()
    # 供应商实际返回、允许展示的思考文本。正文与思考分开持久化和渲染；
    # 不返回思考字段的供应商保持空字符串。
    reasoning: str = ""
    # 模型自报 delegate=true 却没有返回结构化 delegation，属于协议违规；
    # 编排器据此向用户与日志如实暴露。意图判定交给语言模型，代码只检查
    # 这一协议一致性。
    delegation_missed: bool = False


class DialogueEvent(FrozenModel):
    """对话流式事件。

    - ``reasoning.started/delta/completed``：思考通道增量；
    - ``speech.started/delta/completed``：角色正文（干净 speech）增量；
    - ``character.final``：最终完整对象，覆盖并确认临时预览。
    ``raw`` 只用于增量解析失败时把原始输出收进技术详情，不进入气泡。
    """

    type: Literal[
        "reasoning.started",
        "reasoning.delta",
        "reasoning.completed",
        "speech.started",
        "speech.delta",
        "speech.completed",
        "character.final",
    ]
    delta: str | None = None
    turn: CharacterTurn | None = None
    raw: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "DialogueEvent":
        if self.type.endswith(".delta") and self.delta is None:
            raise ValueError(f"{self.type} requires delta")
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
    # 项目运行上下文（名称、目录、时间、时区、模式），角色与助手按此理解
    # 当前工作环境与能力边界；聊天模式下角色不能委派助手。
    runtime_context: "ProjectRuntimeContext | None" = None
    # 本轮序号：该会话含当前用户消息的用户发起消息累计数，1 起算，
    # 开场白不计入。供世界书 atDepth 注入与确定性触发按回合号匹配。
    turn_index: int = 0


class ProjectRef(FrozenModel):
    project_id: str
    name: str
    root_path: str


class ProjectRuntimeContext(FrozenModel):
    """注入角色与助手的项目运行上下文。

    以“当前工作环境”注入系统上下文，不显示成普通聊天消息。
    ``conversation_mode`` 是后端按会话持久化的模式（chat/collaboration）。
    """

    project_name: str = ""
    project_abs_dir: str = ""
    local_time: str = ""
    timezone: str = ""
    conversation_mode: Literal["chat", "collaboration"] = "collaboration"
    # 只有绑定了项目的聊天才有长期记忆作用域。运行时协议据此决定是否向
    # 模型提供 memory 字段，没有作用域就不提供，避免模型写下无处归属的条目。
    memory_enabled: bool = False


class TurnStatus(str, Enum):
    """统一运行模型：一次提交或一次执行对应一个 Turn。"""

    QUEUED = "queued"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Turn(FrozenModel):
    """会话轮次：Conversation → Turn → Message/Reasoning/Tool/Review item。

    每个事件携带 account_id、project_id、conversation_id、turn_id 与
    sequence，前端按 id 与 sequence 消费事件、重连后重新水合。
    """

    turn_id: str = Field(default_factory=new_id)
    account_id: str = ""
    project_id: str
    conversation_id: str
    target: MessageTarget
    source_message_id: str
    status: TurnStatus = TurnStatus.ACCEPTED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class QueueIntent(str, Enum):
    """排队语义：忙碌时默认 followup，明确选择「立即插入」才是 steer。"""

    FOLLOWUP = "followup"
    STEER = "steer"


class QueueItem(FrozenModel):
    """持久化会话队列项（conversation_inbox）。

    入队先持久化，再向前端确认；支持编辑、撤回、调序。
    """

    queue_item_id: str = Field(default_factory=new_id)
    account_id: str = ""
    conversation_id: str
    target: MessageTarget
    text: str
    intent: QueueIntent = QueueIntent.FOLLOWUP
    position: int = 0
    status: Literal["queued", "processing", "withdrawn"] = "queued"
    created_at: datetime = Field(default_factory=utc_now)
    source_message_id: str | None = None


class AccountRecord(FrozenModel):
    """本地账号快照（不含密码派生结果与密钥）。

    账号是项目/聊天/配置/主题偏好/引导标记的隔离边界。
    """

    account_id: str
    username: str
    display_name: str
    avatar: str = ""
    last_login_at: str | None = None
    onboarding_complete: bool = False
    theme: Literal["dark", "light"] = "dark"


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
    # 修改来源：用户直接发给助手的指令，或角色建议的修改。
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
    # 引擎上报的上下文用量（payload: context_used、context_size）。
    USAGE = "usage.updated"


class EngineEvent(FrozenModel):
    event_id: str = Field(default_factory=new_id)
    conversation_id: str
    task_id: str
    engine_turn_id: str
    sequence: int = Field(ge=0)
    type: EngineEventType
    tool_call_id: str | None = None
    # payload 约定只读，需要改写时先拷贝再 model_copy
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
    # 首次观察到工具事件时分配一次，后续更新沿用原序号，与助手 segment
    # 在同一时间线上混排。
    timeline_order: int | None = None


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
    """执行期间注入角色的压缩进度摘要。

    只含中性描述：当前步骤简述、已完成步骤数、状态；不含原始命令、
    文件路径与工具输出原文。
    """

    current_step: str = "任务准备中"
    completed_steps: int = Field(default=0, ge=0)
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
    # 构造时传 list 会被 pydantic 收敛为不可变 tuple
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
