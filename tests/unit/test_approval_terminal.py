from __future__ import annotations

import asyncio

import pytest

import pair_harness.desktop_backend.application_service as app_service_module
from pair_harness.core.contracts import (
    ApprovalDecision,
    EngineEvent,
    EngineEventType,
    PendingOperation,
)
from pair_harness.desktop_backend.application_service import (
    ApprovalBroker,
    ServiceError,
)
from pair_harness.desktop_backend.events import EventEmitter
from tests.service_helpers import EventLog, call, expect_service_error, wait_until


def _operation() -> PendingOperation:
    return PendingOperation(
        tool_kind="shell", command="echo hi", paths=(), summary="测试操作"
    )


def _engine_resolved(
    *,
    approval_id: str,
    decision: str,
    actor: str,
    resolution_reason: str | None = None,
) -> EngineEvent:
    return EngineEvent(
        conversation_id="c1",
        task_id="t1",
        engine_turn_id="e1",
        sequence=2,
        type=EngineEventType.APPROVAL_RESOLVED,
        payload={
            "approval_id": approval_id,
            "decision": decision,
            "actor": actor,
            "request_reason": "需要审批",
            "resolution_reason": resolution_reason,
            "suggestion": "",
        },
    )


@pytest.mark.asyncio
async def test_timeout_is_single_terminal_state(monkeypatch) -> None:
    """超时只广播一次终态，迟到的应答收到 approval_already_resolved 与超时终态。"""
    # ApprovalBroker 的等待上限是模块常量，测试里缩短
    monkeypatch.setattr(app_service_module, "APPROVAL_TIMEOUT_S", 0.05)
    log = EventLog()
    broker = ApprovalBroker(EventEmitter(log))

    with pytest.raises(ServiceError) as excinfo:
        await broker.request(
            operation=_operation(),
            approval_id="a1",
            reason="需要审批",
            conversation_id="c1",
            task_id="t1",
        )
    assert excinfo.value.code == "approval_timeout"
    assert broker._pending == {}

    assert [item["event"] for item in log.items] == [
        "approval.requested",
        "approval.resolved",
    ]
    resolved = log.payloads("approval.resolved")
    assert len(resolved) == 1
    payload = resolved[0]
    assert payload["approval_id"] == "a1"
    assert payload["conversation_id"] == "c1"
    assert payload["task_id"] == "t1"
    assert payload["decision"] == "timeout"
    assert payload["resolved_by"] == "system"
    assert payload["actor"] == "system"
    assert payload["request_reason"] == "需要审批"
    assert payload["resolution_reason"] == "等待审批超时"
    assert payload["error_code"] == "approval_timeout"
    assert payload["resolved_at"]

    with pytest.raises(ServiceError) as late:
        broker.resolve("a1", "allow")
    assert late.value.code == "approval_already_resolved"
    assert late.value.details == payload
    assert len(log.payloads("approval.resolved")) == 1


@pytest.mark.asyncio
async def test_client_cannot_forge_timeout_decision() -> None:
    """timeout 是服务端专属终态：客户端提交按 invalid_decision 拒绝。"""
    log = EventLog()
    broker = ApprovalBroker(EventEmitter(log))
    task = asyncio.create_task(
        broker.request(
            operation=_operation(),
            approval_id="a3",
            reason="需要审批",
            conversation_id="c1",
            task_id="t1",
        )
    )
    await wait_until(lambda: "a3" in broker._pending)

    with pytest.raises(ServiceError) as forged:
        broker.resolve("a3", "timeout")
    assert forged.value.code == "invalid_decision"
    assert "a3" in broker._pending  # 未决状态不被伪造请求破坏
    assert log.payloads("approval.resolved") == []

    broker.resolve("a3", "deny")
    assert await task is ApprovalDecision.DENY


@pytest.mark.asyncio
async def test_first_user_resolution_wins_and_engine_path_emits_once(service) -> None:
    """首个应答获胜，后到的应答拿到先到者终态；引擎路径补广播一次并带应答来源。"""
    broker = service.approval_broker
    task = asyncio.create_task(
        broker.request(
            operation=_operation(),
            approval_id="a4",
            reason="需要审批",
            conversation_id="c1",
            task_id="t1",
        )
    )
    await wait_until(lambda: "a4" in broker._pending)

    first = await call(
        service, "r1", "approval.resolve", approval_id="a4", decision="deny", origin="remote"
    )
    assert first == {
        "approval_id": "a4",
        "accepted": True,
        "resolved_by": "remote",
        "decision": "deny",
    }
    assert await task is ApprovalDecision.DENY
    # 用户裁决本身不广播，等引擎路径带上完整结果后统一广播
    assert service.event_log.payloads("approval.resolved") == []

    late = await expect_service_error(
        lambda: call(service, "r2", "approval.resolve", approval_id="a4", decision="allow"),
        "approval_already_resolved",
    )
    assert late.details["decision"] == "deny"
    assert late.details["resolved_by"] == "remote"
    assert late.details["actor"] == "user"

    service._on_engine_event(
        _engine_resolved(approval_id="a4", decision="deny", actor="user")
    )
    resolved = service.event_log.payloads("approval.resolved")
    assert len(resolved) == 1
    assert resolved[0]["decision"] == "deny"
    assert resolved[0]["resolved_by"] == "remote"
    assert resolved[0]["actor"] == "user"
    assert resolved[0]["error_code"] is None
    assert resolved[0]["resolved_at"]


@pytest.mark.asyncio
async def test_resolve_unknown_approval_reports_not_found(service) -> None:
    await expect_service_error(
        lambda: call(
            service, "n1", "approval.resolve", approval_id="never-requested", decision="allow"
        ),
        "approval_not_found",
    )


@pytest.mark.asyncio
async def test_cancel_wins_and_engine_path_does_not_duplicate(service) -> None:
    """取消终态先到即获胜，引擎路径不再重复广播。"""
    broker = service.approval_broker
    task = asyncio.create_task(
        broker.request(
            operation=_operation(),
            approval_id="a5",
            reason="需要审批",
            conversation_id="c1",
            task_id="t1",
        )
    )
    await wait_until(lambda: "a5" in broker._pending)

    broker.cancel_for_conversation("c1")
    assert await task is ApprovalDecision.DENY
    first = service.event_log.payloads("approval.resolved")
    assert len(first) == 1
    assert first[0]["decision"] == "deny"
    assert first[0]["resolved_by"] == "system"
    assert first[0]["actor"] == "system"

    service._on_engine_event(
        _engine_resolved(approval_id="a5", decision="deny", actor="user")
    )
    assert len(service.event_log.payloads("approval.resolved")) == 1


@pytest.mark.asyncio
async def test_engine_reviewer_decision_keeps_resolved_by_null(service) -> None:
    """未经 broker 的审查裁决按引擎载荷广播，resolved_by 为 null。"""
    service._on_engine_event(
        _engine_resolved(
            approval_id="a6",
            decision="deny",
            actor="reviewer",
            resolution_reason="审查否决",
        )
    )
    resolved = service.event_log.payloads("approval.resolved")
    assert len(resolved) == 1
    assert resolved[0]["decision"] == "deny"
    assert resolved[0]["resolved_by"] is None
    assert resolved[0]["actor"] == "reviewer"
    assert resolved[0]["request_reason"] == "需要审批"
    assert resolved[0]["resolution_reason"] == "审查否决"
    assert resolved[0]["resolved_at"]


@pytest.mark.asyncio
async def test_resolved_record_is_bounded_and_keeps_terminal_fields(service) -> None:
    """已决记录容量有界，且保留终态字段供幂等应答使用。"""
    broker = service.approval_broker
    capacity = broker._RESOLVED_CAPACITY
    for index in range(capacity + 5):
        approval_id = f"a-{index}"
        task = asyncio.create_task(
            broker.request(
                operation=_operation(),
                approval_id=approval_id,
                reason="需要审批",
                conversation_id="c1",
                task_id="t1",
            )
        )
        await wait_until(lambda approval_id=approval_id: approval_id in broker._pending)
        broker.resolve(approval_id, "allow")
        await task
    assert len(broker._resolved) == capacity
    latest = broker._resolved.get(f"a-{capacity + 4}")
    assert latest is not None
    assert latest["decision"] == "allow"
    assert latest["resolved_by"] == "desktop"
    assert latest["actor"] == "user"
    assert latest["resolved_at"]
