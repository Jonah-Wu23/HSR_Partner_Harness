"""聊天级摘要纯逻辑（V0.3.9 契约冻结 §2）。

契约出处：``docs/plans/V0.3.9-契约冻结.md`` §2（原文、摘要、投影与记忆）。

- 摘要键只含 ``conversation_id``，不得跨聊天读取；
- 角色消息计数只统计 ``source=user|character``、``origin!=character_delegation``
  且正文非空的最终消息；流式 delta、助手、工具、思考、系统状态不计数；
- 自上次成功摘要覆盖终点之后达到 80 条，或这些消息 UTF-8 正文累计达到
  256 KiB，任一先到即启动压缩；
- 摘要必须覆盖连续、已最终落库的消息区间；
- 代码只校验 JSON 结构、身份、连续区间与安全边界，不做语义判断，不改写模型摘要；
- 失败保存原始错误、保留原投影，不生成空摘要。

本模块是纯逻辑，不读写数据库、不调用模型。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import (
    FrozenModel,
    Message,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    enum_value,
    utc_now,
)

# ---- 契约 §2 阈值（冻结） ----
SUMMARY_TRIGGER_MESSAGE_COUNT = 80
SUMMARY_TRIGGER_BYTES = 256 * 1024
ROLE_CONTEXT_LIMIT_AFTER_SUMMARY = 12
# 摘要触发前的角色上下文上限：沿用 V0.3.7 现状（世界书扫描缓冲 50）。
# 触发摘要后按契约收窄到 ROLE_CONTEXT_LIMIT_AFTER_SUMMARY。
ROLE_CONTEXT_LIMIT_PRE_SUMMARY = 50
# 摘要内容安全边界：超过即拒绝（summary_invalid），不静默截断。
MAX_SUMMARY_CONTENT_BYTES = 256 * 1024

SUMMARY_STATUSES = ("idle", "running", "completed", "failed")

# 契约 §7 错误码（摘要相关）。
SUMMARY_PROVIDER_ERROR = "summary_provider_error"
SUMMARY_INVALID = "summary_invalid"
SUMMARY_TIMEOUT = "summary_timeout"
SUMMARY_ERROR_CODES = (SUMMARY_PROVIDER_ERROR, SUMMARY_INVALID, SUMMARY_TIMEOUT)

# "最终消息"：不在途（sending/queued/received/processing）的已落库消息。
FINAL_MESSAGE_STATUSES = frozenset(
    {
        MessageStatus.DONE.value,
        MessageStatus.FAILED.value,
        MessageStatus.CANCELLED.value,
    }
)


class SummaryError(ValueError):
    """摘要操作的真实失败；``code`` 为契约错误码。"""

    def __init__(self, message: str, *, code: str = SUMMARY_INVALID) -> None:
        super().__init__(message)
        self.code = code


def is_final_message(message: Message) -> bool:
    """消息是否已最终落库（不在途）。"""
    return enum_value(message.status) in FINAL_MESSAGE_STATUSES


def is_role_message(message: Message) -> bool:
    """契约 §2 的角色消息计数定义。

    只统计 ``source=user|character``、``origin!=character_delegation``、
    正文非空且已最终落库的消息；助手/工具/系统状态与委派镜像不计数。
    """
    if message.source not in (MessageSource.USER, MessageSource.CHARACTER):
        return False
    if message.origin == MessageOrigin.CHARACTER_DELEGATION:
        return False
    if not message.text.strip():
        return False
    return is_final_message(message)


def role_messages(messages: Iterable[Message]) -> tuple[Message, ...]:
    """按契约定义过滤角色消息（保持入参顺序）。"""
    return tuple(message for message in messages if is_role_message(message))


def messages_after_coverage(
    messages: Iterable[Message], covered_to_message_id: str | None
) -> tuple[Message, ...]:
    """返回覆盖终点之后（不含终点）的消息；终点不存在即真实失败。

    ``covered_to_message_id`` 为 None 表示尚无成功摘要覆盖，返回全部消息。
    """
    ordered = tuple(messages)
    if not covered_to_message_id:
        return ordered
    for index, message in enumerate(ordered):
        if message.message_id == covered_to_message_id:
            return ordered[index + 1 :]
    raise SummaryError(
        f"摘要覆盖终点不在会话消息中：{covered_to_message_id}",
        code=SUMMARY_INVALID,
    )


@dataclass(frozen=True)
class SummaryTrigger:
    """压缩触发判定结果（``reason`` 为 None 表示未触发）。"""

    message_count: int
    utf8_bytes: int
    should_start: bool
    reason: str | None


def summary_trigger(
    messages: Iterable[Message], *, covered_to_message_id: str | None = None
) -> SummaryTrigger:
    """契约 §2 触发判定：条数 80 或 UTF-8 正文 256 KiB，任一先到即触发。"""
    pending = role_messages(messages_after_coverage(messages, covered_to_message_id))
    utf8_bytes = sum(len(message.text.encode("utf-8")) for message in pending)
    reason: str | None = None
    if len(pending) >= SUMMARY_TRIGGER_MESSAGE_COUNT:
        reason = "message_count"
    elif utf8_bytes >= SUMMARY_TRIGGER_BYTES:
        reason = "utf8_bytes"
    return SummaryTrigger(
        message_count=len(pending),
        utf8_bytes=utf8_bytes,
        should_start=reason is not None,
        reason=reason,
    )


class ConversationSummary(FrozenModel):
    """一条聊天摘要记录（与 TS ``ConversationSummary`` 同形；契约 §2）。

    状态为 ``idle|running|completed|failed``：

    - ``completed`` 必须含覆盖区间、正数覆盖计数与模型产出的 JSON 对象内容；
    - ``failed`` 必须保存原始 ``error`` 与 ``error_code``，不得生成空摘要内容；
    - ``idle``/``running`` 不得携带内容。
    """

    summary_id: str
    conversation_id: str
    status: Literal["idle", "running", "completed", "failed"] = "idle"
    covers_from_message_id: str | None = None
    covers_to_message_id: str | None = None
    covers_message_count: int = Field(default=0, ge=0)
    content: Mapping[str, Any] | None = None
    provider: str | None = None
    model: str | None = None
    error_code: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("summary_id", "conversation_id")
    @classmethod
    def _require_id(cls, value: str, info: Any) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} 不得为空")
        return text

    @field_validator("content")
    @classmethod
    def _require_object(cls, value: Any) -> Mapping[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("摘要内容必须是 JSON 对象")
        dumped = json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
        size = len(dumped.encode("utf-8"))
        if size > MAX_SUMMARY_CONTENT_BYTES:
            raise ValueError(
                f"摘要内容超过安全边界：{size} > {MAX_SUMMARY_CONTENT_BYTES} 字节"
            )
        return dict(value)

    @model_validator(mode="after")
    def _validate_state(self) -> "ConversationSummary":
        if self.status == "completed":
            if self.content is None:
                raise ValueError("completed 摘要必须包含模型产出的内容")
            if not self.covers_from_message_id or not self.covers_to_message_id:
                raise ValueError("completed 摘要必须包含覆盖区间")
            if self.covers_message_count <= 0:
                raise ValueError("completed 摘要的覆盖计数必须为正数")
            if self.error or self.error_code:
                raise ValueError("completed 摘要不得携带错误")
        elif self.status == "failed":
            if not (self.error or "").strip():
                raise ValueError("failed 摘要必须保存原始错误")
            if not (self.error_code or "").strip():
                raise ValueError("failed 摘要必须保存错误码")
            if self.content is not None:
                raise ValueError("failed 摘要不得生成空摘要或部分内容")
        else:
            if self.content is not None:
                raise ValueError(f"{self.status} 状态不得携带摘要内容")
        return self


def validate_summary_coverage(
    messages: Iterable[Message], summary: ConversationSummary
) -> None:
    """校验摘要覆盖真实存在、连续且已最终落库的消息区间（契约 §2）。

    只做结构校验：区间端点存在、起点不晚于终点、区间内消息全部最终落库、
    区间内角色消息数与 ``covers_message_count`` 一致。不判断摘要语义。
    """
    ordered = tuple(messages)
    if not summary.covers_from_message_id or not summary.covers_to_message_id:
        raise SummaryError("摘要缺少覆盖区间", code=SUMMARY_INVALID)
    ids = [message.message_id for message in ordered]
    try:
        start = ids.index(summary.covers_from_message_id)
        end = ids.index(summary.covers_to_message_id)
    except ValueError as exc:
        raise SummaryError(
            "摘要覆盖区间引用了会话中不存在的消息", code=SUMMARY_INVALID
        ) from exc
    if start > end:
        raise SummaryError("摘要覆盖区间起点晚于终点", code=SUMMARY_INVALID)
    window = ordered[start : end + 1]
    for message in window:
        if message.conversation_id != summary.conversation_id:
            raise SummaryError(
                "摘要覆盖区间包含其他聊天的消息："
                f"{message.message_id}（{message.conversation_id}）",
                code=SUMMARY_INVALID,
            )
        if not is_final_message(message):
            raise SummaryError(
                f"摘要覆盖区间包含未最终落库的消息：{message.message_id}",
                code=SUMMARY_INVALID,
            )
    actual = len(role_messages(window))
    if actual != summary.covers_message_count:
        raise SummaryError(
            "摘要覆盖计数与真实区间不一致："
            f"记录 {summary.covers_message_count}，实际 {actual}",
            code=SUMMARY_INVALID,
        )


def require_summary_conversation(
    summary: ConversationSummary, conversation_id: str
) -> None:
    """摘要只能属于当前聊天（契约 §2：摘要键只含 conversation_id）。"""
    if summary.conversation_id != conversation_id:
        raise SummaryError(
            "摘要不属于当前聊天："
            f"{summary.conversation_id} != {conversation_id}",
            code=SUMMARY_INVALID,
        )


def completed_summary(
    *,
    summary_id: str,
    conversation_id: str,
    covers_from_message_id: str,
    covers_to_message_id: str,
    covers_message_count: int,
    content: Mapping[str, Any],
    provider: str | None = None,
    model: str | None = None,
    now: datetime | None = None,
) -> ConversationSummary:
    """构造成功摘要记录（内容原样保存，不改写）。"""
    timestamp = now or utc_now()
    return ConversationSummary(
        summary_id=summary_id,
        conversation_id=conversation_id,
        status="completed",
        covers_from_message_id=covers_from_message_id,
        covers_to_message_id=covers_to_message_id,
        covers_message_count=covers_message_count,
        content=content,
        provider=provider,
        model=model,
        created_at=timestamp,
        updated_at=timestamp,
    )


def failed_summary(
    *,
    summary_id: str,
    conversation_id: str,
    error_code: str,
    error: str,
    covers_from_message_id: str | None = None,
    covers_to_message_id: str | None = None,
    covers_message_count: int = 0,
    provider: str | None = None,
    model: str | None = None,
    now: datetime | None = None,
) -> ConversationSummary:
    """构造失败摘要记录：保留原始错误，不生成空摘要内容。"""
    timestamp = now or utc_now()
    return ConversationSummary(
        summary_id=summary_id,
        conversation_id=conversation_id,
        status="failed",
        covers_from_message_id=covers_from_message_id,
        covers_to_message_id=covers_to_message_id,
        covers_message_count=covers_message_count,
        provider=provider,
        model=model,
        error_code=error_code,
        error=error,
        created_at=timestamp,
        updated_at=timestamp,
    )


def summary_event_payload(
    summary: ConversationSummary,
    *,
    account_id: str,
    project_id: str,
    pair_id: str,
    character_ref: str,
    assistant_identity: str,
) -> dict:
    """``summary.started/completed/failed`` 事件载荷（契约 §2）。

    失败事件额外携带 ``error_code/error``；不携带隐藏提示内容。
    """
    payload: dict = {
        "summary_id": summary.summary_id,
        "conversation_id": summary.conversation_id,
        "status": summary.status,
        "account_id": account_id,
        "project_id": project_id,
        "pair_id": pair_id,
        "character_ref": character_ref,
        "assistant_identity": assistant_identity,
        "covers_from_message_id": summary.covers_from_message_id,
        "covers_to_message_id": summary.covers_to_message_id,
        "covers_message_count": summary.covers_message_count,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
    }
    if summary.status == "failed":
        payload["error_code"] = summary.error_code
        payload["error"] = summary.error
    return payload
