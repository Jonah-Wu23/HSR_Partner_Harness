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
from pair_harness.core.projection import role_context_window
from pair_harness.core.summary import (
    MAX_SUMMARY_CONTENT_BYTES,
    ROLE_CONTEXT_LIMIT_AFTER_SUMMARY,
    ROLE_CONTEXT_LIMIT_PRE_SUMMARY,
    SUMMARY_INVALID,
    SUMMARY_TRIGGER_BYTES,
    SUMMARY_TRIGGER_MESSAGE_COUNT,
    ConversationSummary,
    SummaryError,
    is_role_message,
    messages_after_coverage,
    require_summary_conversation,
    summary_event_payload,
    summary_trigger,
    validate_summary_coverage,
)

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ASSISTANT = {
    "source": MessageSource.ASSISTANT,
    "kind": MessageKind.ASSISTANT_NATURAL_LANGUAGE,
}
_IDENTITY = {
    "account_id": "acc-1",
    "project_id": "proj-1",
    "pair_id": "phainon_ancient_machine",
    "character_ref": "builtin:phainon",
    "assistant_identity": "ancient_machine",
}


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


def _messages(texts: list[str]) -> list[Message]:
    return [_message(index, text) for index, text in enumerate(texts, start=1)]


def _completed(
    covers_from: str = "m1", covers_to: str = "m1", count: int = 1
) -> ConversationSummary:
    return ConversationSummary(
        summary_id="s1",
        conversation_id="conv-1",
        status="completed",
        covers_from_message_id=covers_from,
        covers_to_message_id=covers_to,
        covers_message_count=count,
        content={"a": 1},
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"source": MessageSource.CHARACTER, "kind": MessageKind.CHARACTER_SPEECH}, True),
        # 委派镜像（user + character_delegation）不是用户真实发言
        ({"origin": MessageOrigin.CHARACTER_DELEGATION}, False),
        (_ASSISTANT, False),
        ({"source": MessageSource.TOOL, "kind": MessageKind.TOOL_RECORD}, False),
        ({"source": MessageSource.SYSTEM, "kind": MessageKind.SYSTEM_STATUS}, False),
        ({"text": "   "}, False),
        ({"status": MessageStatus.PROCESSING}, False),
    ],
    ids=[
        "user",
        "character",
        "delegation_mirror",
        "assistant",
        "tool",
        "system",
        "blank",
        "in_flight",
    ],
)
def test_role_message_definition(overrides: dict, expected: bool) -> None:
    assert is_role_message(_message(1, **overrides)) is expected


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


@pytest.mark.parametrize(
    ("texts", "below_texts", "reason"),
    [
        (
            ["消息"] * SUMMARY_TRIGGER_MESSAGE_COUNT,
            ["消息"] * (SUMMARY_TRIGGER_MESSAGE_COUNT - 1),
            "message_count",
        ),
        (["a" * SUMMARY_TRIGGER_BYTES], ["a" * (SUMMARY_TRIGGER_BYTES - 1)], "utf8_bytes"),
    ],
    ids=["message_count", "utf8_bytes"],
)
def test_trigger_starts_exactly_at_threshold(
    texts: list[str], below_texts: list[str], reason: str
) -> None:
    trigger = summary_trigger(_messages(texts))
    assert (trigger.should_start, trigger.reason) == (True, reason)
    assert summary_trigger(_messages(below_texts)).should_start is False


def test_trigger_counts_only_messages_after_coverage_endpoint() -> None:
    messages = [_message(i) for i in range(SUMMARY_TRIGGER_MESSAGE_COUNT + 5)]
    trigger = summary_trigger(messages, covered_to_message_id="m5")
    assert trigger.message_count == SUMMARY_TRIGGER_MESSAGE_COUNT - 1
    assert trigger.should_start is False


def test_trigger_ignores_ineligible_messages() -> None:
    messages = [_message(i, **_ASSISTANT) for i in range(SUMMARY_TRIGGER_MESSAGE_COUNT * 2)]
    assert summary_trigger(messages).should_start is False


_RANGE = {
    "covers_from_message_id": "m1",
    "covers_to_message_id": "m3",
    "covers_message_count": 3,
}


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "completed", **_RANGE, "content": None},
        {"status": "completed", "content": {"a": 1}},
        {"status": "completed", **_RANGE, "covers_message_count": 0, "content": {"a": 1}},
        {"status": "failed", "error_code": "summary_timeout", "error": ""},
        {
            "status": "failed",
            "error_code": "summary_timeout",
            "error": "timeout",
            "content": {"partial": "not allowed"},
        },
        {"status": "running", "content": {"a": 1}},
        # 超过安全边界即拒绝，不截断
        {
            "status": "completed",
            **_RANGE,
            "content": {"blob": "x" * (MAX_SUMMARY_CONTENT_BYTES + 1)},
        },
    ],
    ids=[
        "completed_without_content",
        "completed_without_range",
        "completed_with_zero_count",
        "failed_without_error",
        "failed_with_content",
        "running_with_content",
        "content_over_limit",
    ],
)
def test_summary_record_rejects_invalid_state(fields: dict) -> None:
    with pytest.raises(ValidationError):
        ConversationSummary(summary_id="s1", conversation_id="conv-1", **fields)


def test_validate_coverage_counts_only_role_messages() -> None:
    messages = [_message(1), _message(2, **_ASSISTANT), _message(3)]
    validate_summary_coverage(messages, _completed("m1", "m3", 2))


@pytest.mark.parametrize(
    ("messages", "summary"),
    [
        ([_message(1), _message(2, **_ASSISTANT), _message(3)], _completed("m1", "m3", 3)),
        ([_message(i) for i in range(1, 4)], _completed("m1", "m9", 3)),
        ([_message(i) for i in range(1, 4)], _completed("m3", "m1", 3)),
        ([_message(1), _message(2, status=MessageStatus.PROCESSING)], _completed("m1", "m2", 2)),
        ([_message(1), _message(2, conversation_id="conv-other")], _completed("m1", "m2", 2)),
    ],
    ids=["count_mismatch", "unknown_endpoint", "reversed_range", "in_flight", "foreign_message"],
)
def test_validate_coverage_rejects_invalid_range(
    messages: list[Message], summary: ConversationSummary
) -> None:
    with pytest.raises(SummaryError) as excinfo:
        validate_summary_coverage(messages, summary)
    assert excinfo.value.code == SUMMARY_INVALID


def test_require_summary_conversation_blocks_cross_chat_reads() -> None:
    summary = _completed()
    require_summary_conversation(summary, "conv-1")
    with pytest.raises(SummaryError) as excinfo:
        require_summary_conversation(summary, "conv-2")
    assert excinfo.value.code == SUMMARY_INVALID


def test_summary_event_payload_carries_identity_and_hides_content() -> None:
    failed = ConversationSummary(
        summary_id="s1",
        conversation_id="conv-1",
        status="failed",
        error_code="summary_provider_error",
        error="http 500",
    )
    payload = summary_event_payload(failed, **_IDENTITY)
    assert _IDENTITY.items() <= payload.items()
    assert (payload["error_code"], payload["error"]) == ("summary_provider_error", "http 500")
    assert "content" not in payload

    completed = summary_event_payload(_completed(), **_IDENTITY)
    assert "error_code" not in completed
    assert "content" not in completed


def test_role_context_window_narrows_after_summary_coverage() -> None:
    many = [_message(i) for i in range(1, 61)]
    assert len(role_context_window(many)) == ROLE_CONTEXT_LIMIT_PRE_SUMMARY
    window = role_context_window(many, covered_to_message_id="m5")
    assert len(window) == ROLE_CONTEXT_LIMIT_AFTER_SUMMARY
    assert [m.message_id for m in window] == [f"m{i}" for i in range(49, 61)]


def test_role_context_window_keeps_only_role_messages() -> None:
    messages = [_message(1), _message(2, **_ASSISTANT), _message(3), _message(4, "   ")]
    assert [m.message_id for m in role_context_window(messages)] == ["m1", "m3"]
