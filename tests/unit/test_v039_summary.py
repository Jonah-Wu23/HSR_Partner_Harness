"""V0.3.9 契约 §2：摘要计数、触发阈值、覆盖区间与状态不变量。

契约出处：``.archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md`` §2。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pair_harness.core.contracts import (
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
)
from pair_harness.core.summary import (
    MAX_SUMMARY_CONTENT_BYTES,
    ROLE_CONTEXT_LIMIT_AFTER_SUMMARY,
    SUMMARY_INVALID,
    SUMMARY_TRIGGER_BYTES,
    SUMMARY_TRIGGER_MESSAGE_COUNT,
    ConversationSummary,
    SummaryError,
    completed_summary,
    failed_summary,
    is_role_message,
    messages_after_coverage,
    require_summary_conversation,
    role_messages,
    summary_event_payload,
    summary_trigger,
    validate_summary_coverage,
)

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _message(
    index: int,
    text: str | None = None,
    *,
    source: MessageSource = MessageSource.USER,
    origin: MessageOrigin = MessageOrigin.USER,
    status: MessageStatus = MessageStatus.DONE,
    conversation_id: str = "conv-1",
    kind: MessageKind = MessageKind.USER_TEXT,
) -> Message:
    return Message(
        message_id=f"m{index}",
        conversation_id=conversation_id,
        pair_id="phainon_ancient_machine",
        source=source,
        kind=kind,
        text=text if text is not None else f"消息{index}",
        origin=origin,
        status=status,
        created_at=_T0 + timedelta(seconds=index),
    )


def test_role_message_definition() -> None:
    assert is_role_message(_message(1))
    assert is_role_message(
        _message(2, source=MessageSource.CHARACTER, kind=MessageKind.CHARACTER_SPEECH)
    )
    # 委派镜像（user + character_delegation）不是用户真实发言
    assert not is_role_message(_message(3, origin=MessageOrigin.CHARACTER_DELEGATION))
    # 助手、工具、系统不计数
    assert not is_role_message(
        _message(4, source=MessageSource.ASSISTANT, kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE)
    )
    assert not is_role_message(
        _message(5, source=MessageSource.TOOL, kind=MessageKind.TOOL_RECORD)
    )
    assert not is_role_message(
        _message(6, source=MessageSource.SYSTEM, kind=MessageKind.SYSTEM_STATUS)
    )
    # 空正文不计数
    assert not is_role_message(_message(7, "   "))
    # 未最终落库（在途）不计数
    assert not is_role_message(_message(8, status=MessageStatus.PROCESSING))


def test_role_messages_preserves_order() -> None:
    messages = [_message(i) for i in range(1, 4)]
    assert [m.message_id for m in role_messages(messages)] == ["m1", "m2", "m3"]


def test_messages_after_coverage_is_exclusive() -> None:
    messages = [_message(i) for i in range(1, 5)]
    assert [m.message_id for m in messages_after_coverage(messages, "m2")] == [
        "m3",
        "m4",
    ]
    assert len(messages_after_coverage(messages, None)) == 4


def test_messages_after_coverage_unknown_endpoint_is_real_failure() -> None:
    with pytest.raises(SummaryError) as excinfo:
        messages_after_coverage([_message(1)], "missing")
    assert excinfo.value.code == SUMMARY_INVALID


def test_trigger_by_message_count() -> None:
    messages = [_message(i) for i in range(SUMMARY_TRIGGER_MESSAGE_COUNT)]
    trigger = summary_trigger(messages)
    assert trigger.should_start is True
    assert trigger.reason == "message_count"
    assert trigger.message_count == SUMMARY_TRIGGER_MESSAGE_COUNT
    assert summary_trigger(messages[:-1]).should_start is False


def test_trigger_by_utf8_bytes() -> None:
    text = "字" * (SUMMARY_TRIGGER_BYTES // 3 + 1)
    messages = [_message(1, text)]
    trigger = summary_trigger(messages)
    assert trigger.should_start is True
    assert trigger.reason == "utf8_bytes"
    assert trigger.utf8_bytes >= SUMMARY_TRIGGER_BYTES


def test_trigger_counts_only_messages_after_coverage_endpoint() -> None:
    messages = [_message(i) for i in range(SUMMARY_TRIGGER_MESSAGE_COUNT + 5)]
    trigger = summary_trigger(messages, covered_to_message_id="m5")
    assert trigger.message_count == SUMMARY_TRIGGER_MESSAGE_COUNT - 1
    assert trigger.should_start is False


def test_trigger_ignores_ineligible_messages() -> None:
    messages = [
        _message(i, source=MessageSource.ASSISTANT, kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE)
        for i in range(SUMMARY_TRIGGER_MESSAGE_COUNT * 2)
    ]
    assert summary_trigger(messages).should_start is False


def test_completed_summary_requires_content_and_range() -> None:
    summary = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m3",
        covers_message_count=3,
        content={"topics": ["开场"]},
        provider="deepseek",
        model="deepseek-chat",
    )
    assert summary.status == "completed"
    assert summary.content == {"topics": ["开场"]}

    # completed 但缺少模型内容：真实失败，不生成空摘要
    with pytest.raises(ValidationError):
        ConversationSummary(
            summary_id="s2",
            conversation_id="conv-1",
            status="completed",
            covers_from_message_id="m1",
            covers_to_message_id="m3",
            covers_message_count=3,
            content=None,
        )


def test_completed_summary_rejects_missing_range_or_zero_count() -> None:
    with pytest.raises(ValidationError):
        ConversationSummary(
            summary_id="s1",
            conversation_id="conv-1",
            status="completed",
            content={"a": 1},
            covers_message_count=0,
        )
    with pytest.raises(ValidationError):
        ConversationSummary(
            summary_id="s1",
            conversation_id="conv-1",
            status="completed",
            content={"a": 1},
            covers_from_message_id="m1",
            covers_to_message_id="m1",
            covers_message_count=0,
        )


def test_failed_summary_keeps_original_error_and_no_content() -> None:
    summary = failed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        error_code="summary_timeout",
        error="provider timeout after 30s",
        covers_from_message_id="m1",
        covers_to_message_id="m3",
        covers_message_count=3,
    )
    assert summary.status == "failed"
    assert summary.content is None
    assert summary.error == "provider timeout after 30s"
    assert summary.error_code == "summary_timeout"

    with pytest.raises(ValidationError):
        ConversationSummary(
            summary_id="s2",
            conversation_id="conv-1",
            status="failed",
            error_code="summary_timeout",
            error="",
        )
    with pytest.raises(ValidationError):
        ConversationSummary(
            summary_id="s3",
            conversation_id="conv-1",
            status="failed",
            error_code="summary_timeout",
            error="timeout",
            content={"partial": "not allowed"},
        )


def test_running_and_idle_summaries_carry_no_content() -> None:
    running = ConversationSummary(
        summary_id="s1", conversation_id="conv-1", status="running"
    )
    assert running.content is None
    with pytest.raises(ValidationError):
        ConversationSummary(
            summary_id="s2",
            conversation_id="conv-1",
            status="running",
            content={"a": 1},
        )


def test_summary_content_size_boundary_is_rejected_not_truncated() -> None:
    with pytest.raises(ValidationError):
        ConversationSummary(
            summary_id="s1",
            conversation_id="conv-1",
            status="completed",
            covers_from_message_id="m1",
            covers_to_message_id="m1",
            covers_message_count=1,
            content={"blob": "x" * (MAX_SUMMARY_CONTENT_BYTES + 1)},
        )


def test_validate_coverage_accepts_contiguous_range() -> None:
    messages = [_message(i) for i in range(1, 5)]
    summary = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m4",
        covers_message_count=4,
        content={"a": 1},
    )
    validate_summary_coverage(messages, summary)


def test_validate_coverage_counts_only_role_messages() -> None:
    messages = [
        _message(1),
        _message(2, source=MessageSource.ASSISTANT, kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE),
        _message(3),
    ]
    summary = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m3",
        covers_message_count=2,
        content={"a": 1},
    )
    validate_summary_coverage(messages, summary)

    wrong = summary.model_copy(update={"covers_message_count": 3})
    with pytest.raises(SummaryError) as excinfo:
        validate_summary_coverage(messages, wrong)
    assert excinfo.value.code == SUMMARY_INVALID


def test_validate_coverage_rejects_unknown_endpoint_and_reversed_range() -> None:
    messages = [_message(i) for i in range(1, 4)]
    unknown = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m9",
        covers_message_count=3,
        content={"a": 1},
    )
    with pytest.raises(SummaryError):
        validate_summary_coverage(messages, unknown)

    reversed_range = completed_summary(
        summary_id="s2",
        conversation_id="conv-1",
        covers_from_message_id="m3",
        covers_to_message_id="m1",
        covers_message_count=3,
        content={"a": 1},
    )
    with pytest.raises(SummaryError):
        validate_summary_coverage(messages, reversed_range)


def test_validate_coverage_rejects_in_flight_or_foreign_messages() -> None:
    in_flight = [_message(1), _message(2, status=MessageStatus.PROCESSING)]
    summary = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m2",
        covers_message_count=2,
        content={"a": 1},
    )
    with pytest.raises(SummaryError) as excinfo:
        validate_summary_coverage(in_flight, summary)
    assert excinfo.value.code == SUMMARY_INVALID

    foreign = [_message(1), _message(2, conversation_id="conv-other")]
    with pytest.raises(SummaryError):
        validate_summary_coverage(foreign, summary)


def test_require_summary_conversation_blocks_cross_chat_reads() -> None:
    summary = completed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m1",
        covers_message_count=1,
        content={"a": 1},
    )
    require_summary_conversation(summary, "conv-1")
    with pytest.raises(SummaryError) as excinfo:
        require_summary_conversation(summary, "conv-2")
    assert excinfo.value.code == SUMMARY_INVALID


def test_summary_event_payload_identity_and_failure_fields() -> None:
    summary = failed_summary(
        summary_id="s1",
        conversation_id="conv-1",
        error_code="summary_provider_error",
        error="http 500",
    )
    payload = summary_event_payload(
        summary,
        account_id="acc-1",
        project_id="proj-1",
        pair_id="phainon_ancient_machine",
        character_ref="builtin:phainon",
        assistant_identity="ancient_machine",
    )
    assert payload["account_id"] == "acc-1"
    assert payload["project_id"] == "proj-1"
    assert payload["pair_id"] == "phainon_ancient_machine"
    assert payload["character_ref"] == "builtin:phainon"
    assert payload["assistant_identity"] == "ancient_machine"
    assert payload["error_code"] == "summary_provider_error"
    assert payload["error"] == "http 500"
    assert "content" not in payload

    completed = completed_summary(
        summary_id="s2",
        conversation_id="conv-1",
        covers_from_message_id="m1",
        covers_to_message_id="m1",
        covers_message_count=1,
        content={"a": 1},
    )
    ok_payload = summary_event_payload(
        completed,
        account_id="acc-1",
        project_id="proj-1",
        pair_id="phainon_ancient_machine",
        character_ref="builtin:phainon",
        assistant_identity="ancient_machine",
    )
    assert "error_code" not in ok_payload
    assert "content" not in ok_payload


def test_role_context_limit_constant_is_contract_value() -> None:
    assert ROLE_CONTEXT_LIMIT_AFTER_SUMMARY == 12
