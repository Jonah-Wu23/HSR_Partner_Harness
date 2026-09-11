"""V0.3.9 存储层记录类型（contract-v1 第 1/2/4/5 节）。

本模块只定义持久化记录的结构与结构性校验，不含任何语义判断：

- 身份字段来自服务端解析，客户端不得自行拼接（第 1 节）；
- 长期记忆作用域为 account_id + project_id + pair_id + character_ref +
  assistant_identity，任一分量缺失即拒绝写入（结构性拒绝，不是关键词筛选）；
- 指标缺失字段保持 None（序列化为 SQL NULL），真实零值使用 0；
  存储层不做 None -> 0 的兜底转换（第 5 节）。

协议载荷（TurnMetric 等）由接线方从这些记录映射，本模块不依赖
desktop_backend。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _new_id() -> str:
    return str(uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _Record(BaseModel):
    """冻结记录：字段只读，未知字段直接拒绝。"""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=True)


class SummaryStatus(str, Enum):
    """摘要状态（契约第 2 节：idle|running|completed|failed）。"""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MemoryStatus(str, Enum):
    """长期记忆状态（契约第 2 节：active|deleted）。"""

    ACTIVE = "active"
    DELETED = "deleted"


class ProjectionKind(str, Enum):
    """投影条目类型（契约第 2 节：只引用 message_id/summary_id/tool_call_id）。"""

    MESSAGE = "message"
    SUMMARY = "summary"
    TOOL_RUN = "tool_run"


class TurnKind(str, Enum):
    """指标行类型：角色回合与助手任务各一行。"""

    CHARACTER_TURN = "character_turn"
    ASSISTANT_TASK = "assistant_task"


class MetricStatus(str, Enum):
    """指标行状态；终态不可回退（与 TaskStatus/TurnStatus 对齐）。"""

    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_METRIC_STATUSES = frozenset(
    {MetricStatus.COMPLETED.value, MetricStatus.FAILED.value, MetricStatus.CANCELLED.value}
)


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value


class ConversationSummary(_Record):
    """聊天级摘要（契约第 2 节）。

    covers_* 描述连续、已最终落库的消息区间；content 是模型产出的结构化
    摘要原文，代码不改写、不摘要、不截断。失败保留原始错误。
    """

    summary_id: str = Field(default_factory=_new_id)
    conversation_id: str
    covers_from_message_id: str
    covers_to_message_id: str
    covers_message_count: int = Field(ge=0)
    content: str = ""
    provider: str | None = None
    model: str | None = None
    status: str = SummaryStatus.RUNNING.value
    error_code: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("conversation_id", "covers_from_message_id", "covers_to_message_id")
    @classmethod
    def _validate_ids(cls, value: str, info: Any) -> str:
        return _require_text(value, str(info.field_name))

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        allowed = {item.value for item in SummaryStatus}
        if value not in allowed:
            raise ValueError(f"未知摘要状态：{value}；允许 {sorted(allowed)}")
        return value


class ProjectionEntry(_Record):
    """持久化投影条目：只存引用与顺序，不复制原文（契约第 2 节）。

    - position：投影内顺序，0 起，按会话唯一；
    - covered_by_summary_id：已被摘要覆盖时指向摘要，None 表示仍保留原文；
    - 三个 *_id 中只有与 kind 对应的那个非空。
    """

    conversation_id: str
    entry_id: str = Field(default_factory=_new_id)
    position: int = Field(ge=0)
    kind: str
    message_id: str | None = None
    summary_id: str | None = None
    tool_call_id: str | None = None
    covered_by_summary_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("conversation_id")
    @classmethod
    def _validate_conversation(cls, value: str) -> str:
        return _require_text(value, "conversation_id")

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: str) -> str:
        allowed = {item.value for item in ProjectionKind}
        if value not in allowed:
            raise ValueError(f"未知投影条目类型：{value}；允许 {sorted(allowed)}")
        return value

    @field_validator("position")
    @classmethod
    def _validate_position(cls, value: int) -> int:
        if value < 0:
            raise ValueError("position 必须 >= 0")
        return value

    def reference_id(self) -> str | None:
        """返回该条目引用的记录 id（按其 kind）。"""
        if self.kind == ProjectionKind.MESSAGE.value:
            return self.message_id
        if self.kind == ProjectionKind.SUMMARY.value:
            return self.summary_id
        if self.kind == ProjectionKind.TOOL_RUN.value:
            return self.tool_call_id
        return None


class MemoryScope(_Record):
    """长期记忆作用域（契约第 1 节）。

    五个分量必须全部非空：项目为空的日常聊天不读写长期记忆；
    assistant_identity 是当前权威搭档配置的 pair.assistant.id，
    pair_id 不可替代它。
    """

    account_id: str
    project_id: str
    pair_id: str
    character_ref: str
    assistant_identity: str

    @field_validator(
        "account_id", "project_id", "pair_id", "character_ref", "assistant_identity"
    )
    @classmethod
    def _validate_parts(cls, value: str, info: Any) -> str:
        return _require_text(value, str(info.field_name))

    def as_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.account_id,
            self.project_id,
            self.pair_id,
            self.character_ref,
            self.assistant_identity,
        )


class PairMemory(_Record):
    """配对级长期记忆（契约第 1/2 节）。

    content 由模型负责；存储层只校验结构与作用域。status 为 active|deleted，
    删除是真实持久化状态，不做物理删除。
    """

    memory_id: str = Field(default_factory=_new_id)
    account_id: str
    project_id: str
    pair_id: str
    character_ref: str
    assistant_identity: str
    conversation_id: str | None = None
    content: str
    status: str = MemoryStatus.ACTIVE.value
    provider: str | None = None
    model: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        return _require_text(value, "content")

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        allowed = {item.value for item in MemoryStatus}
        if value not in allowed:
            raise ValueError(f"未知记忆状态：{value}；允许 {sorted(allowed)}")
        return value

    def scope(self) -> MemoryScope:
        return MemoryScope(
            account_id=self.account_id,
            project_id=self.project_id,
            pair_id=self.pair_id,
            character_ref=self.character_ref,
            assistant_identity=self.assistant_identity,
        )


class TurnMetric(_Record):
    """回合/任务指标行（契约第 5 节）。

    未观测或供应商不提供的字段保持 None，键始终存在；真实零值使用 0。
    禁止用字符数估算 token——需要真实 usage 才能写值。
    """

    metric_id: str = Field(default_factory=_new_id)
    account_id: str
    project_id: str
    conversation_id: str
    pair_id: str
    character_ref: str | None = None
    assistant_identity: str | None = None
    turn_kind: str
    turn_id: str
    task_id: str | None = None
    engine_turn_id: str | None = None
    source_message_id: str | None = None
    provider: str | None = None
    model: str | None = None
    engine_type: str | None = None
    reasoning_effort: str | None = None
    status: str = MetricStatus.ACCEPTED.value
    started_at: datetime = Field(default_factory=_utc_now)
    first_event_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    first_event_latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    tool_rounds: int = Field(default=0, ge=0)
    compression_count: int = Field(default=0, ge=0)
    approval_count: int = Field(default=0, ge=0)
    failure_type: str | None = None
    failure_message: str | None = None
    origin: Literal["desktop", "remote"] = "desktop"
    remote_device_key: str | None = None
    remote_device_name: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("account_id", "project_id", "conversation_id", "pair_id", "turn_id")
    @classmethod
    def _validate_required(cls, value: str, info: Any) -> str:
        return _require_text(value, str(info.field_name))

    @field_validator("turn_kind")
    @classmethod
    def _validate_turn_kind(cls, value: str) -> str:
        allowed = {item.value for item in TurnKind}
        if value not in allowed:
            raise ValueError(f"未知 turn_kind：{value}；允许 {sorted(allowed)}")
        return value

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        allowed = {item.value for item in MetricStatus}
        if value not in allowed:
            raise ValueError(f"未知指标状态：{value}；允许 {sorted(allowed)}")
        return value


class TurnMetricQuery(_Record):
    """metrics.query 的存储层过滤条件（契约第 5 节）。

    limit 默认 50、上限 200；cursor 是不透明游标，由
    SQLiteStore.query_turn_metrics 返回并原样回传。
    """

    account_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    pair_id: str | None = None
    character_ref: str | None = None
    assistant_identity: str | None = None
    turn_kind: str | None = None
    status: str | None = None
    origin: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 50
    cursor: str | None = None

    @field_validator("limit")
    @classmethod
    def _validate_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("limit 必须 >= 1")
        return min(value, 200)


class TurnMetricPage(_Record):
    """一页指标结果；next_cursor 为 None 表示没有更多。"""

    items: tuple[TurnMetric, ...] = ()
    next_cursor: str | None = None
