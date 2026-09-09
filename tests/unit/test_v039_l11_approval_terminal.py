"""V0.3.9 L11：审批统一终态（契约 docs/plans/V0.3.9-契约冻结.md §6/§9）。

覆盖：
1. 超时是终态：恰好一条 approval.resolved(timeout)，字段齐全；
2. 迟到点击返回带真实终态的 approval_already_resolved；
3. 客户端不能伪造 decision=timeout；
4. 用户裁决 + 引擎路径只广播一次，resolved_by 取真实通道来源；
5. 取消终态优先，引擎路径不重复广播；
6. 没有 broker 记录的审查裁决：resolved_by 保持 null，不伪造来源。

离线夹具只证明协议与状态逻辑，不构成真机或真实供应商链路证据。
"""

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
from test_v035_wiring import service, wait_until  # noqa: F401 - fixture/工具复用


class RecordingEmitter:
    """收集事件信封的测试 sink。"""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def __call__(self, envelope: dict) -> None:
        self.items.append(envelope)

    def payloads(self, event: str) -> list[dict]:
        return [item["payload"] for item in self.items if item["event"] == event]


def _operation() -> PendingOperation:
    return PendingOperation(
        tool_kind="shell", command="echo hi", paths=(), summary="测试操作"
    )


def _engine_resolved(
    *, approval_id: str, decision: str, actor: str, reason: str = "需要审批"
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
            "reason": reason,
            "suggestion": "",
        },
    )


@pytest.mark.asyncio
async def test_timeout_broadcasts_single_terminal_event(monkeypatch) -> None:
    """超时广播唯一终态：decision=timeout、resolved_by=system、字段齐全。"""
    monkeypatch.setattr(app_service_module, "APPROVAL_TIMEOUT_S", 0.05)
    log = RecordingEmitter()
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
    assert broker.pending == {}

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
    assert payload["reason"] == "等待审批超时"
    assert payload["error_code"] == "approval_timeout"
    assert payload["resolved_at"]


@pytest.mark.asyncio
async def test_late_resolve_returns_real_terminal_details(monkeypatch) -> None:
    """迟到点击拿到真实终态（timeout），不再是无信息的 not_found。"""
    monkeypatch.setattr(app_service_module, "APPROVAL_TIMEOUT_S", 0.05)
    broker = ApprovalBroker(EventEmitter(RecordingEmitter()))
    with pytest.raises(ServiceError):
        await broker.request(
            operation=_operation(),
            approval_id="a2",
            reason="需要审批",
            conversation_id="c1",
            task_id="t1",
        )

    with pytest.raises(ServiceError) as late:
        broker.resolve("a2", "allow")
    assert late.value.code == "approval_already_resolved"
    assert late.value.details["decision"] == "timeout"
    assert late.value.details["resolved_by"] == "system"
    assert late.value.details["actor"] == "system"
    assert late.value.details["error_code"] == "approval_timeout"
    assert late.value.details["resolved_at"]


@pytest.mark.asyncio
async def test_client_cannot_forge_timeout_decision() -> None:
    """timeout 是服务端专属终态：客户端提交按 invalid_decision 拒绝。"""
    log = RecordingEmitter()
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
    await wait_until(lambda: "a3" in broker.pending)

    with pytest.raises(ServiceError) as forged:
        broker.resolve("a3", "timeout")
    assert forged.value.code == "invalid_decision"
    assert "a3" in broker.pending  # 未决状态不被伪造请求破坏
    assert log.payloads("approval.resolved") == []

    broker.resolve("a3", "deny")
    assert await task is ApprovalDecision.DENY


@pytest.mark.asyncio
async def test_user_resolve_then_engine_event_emits_once(service) -> None:
    """用户裁决先记录终态，引擎路径补广播一次并带真实 resolved_by。"""
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
    await wait_until(lambda: "a4" in broker.pending)

    outcome = broker.resolve("a4", "allow", resolved_by="remote")
    assert outcome == {"decision": "allow", "resolved_by": "remote"}
    assert await task is ApprovalDecision.ALLOW
    # 用户裁决本身不广播（等待引擎路径统一广播）。
    assert service.event_log.payloads("approval.resolved") == []

    service._on_engine_event(
        _engine_resolved(approval_id="a4", decision="allow", actor="user")
    )
    resolved = service.event_log.payloads("approval.resolved")
    assert len(resolved) == 1
    assert resolved[0]["decision"] == "allow"
    assert resolved[0]["resolved_by"] == "remote"
    assert resolved[0]["actor"] == "user"
    assert resolved[0]["error_code"] is None
    assert resolved[0]["resolved_at"]


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
    await wait_until(lambda: "a5" in broker.pending)

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
    """没有 broker 记录的审查裁决：resolved_by 保持 null，不伪造来源。"""
    service._on_engine_event(
        _engine_resolved(
            approval_id="a6",
            decision="deny",
            actor="reviewer",
            reason="审查否决",
        )
    )
    resolved = service.event_log.payloads("approval.resolved")
    assert len(resolved) == 1
    assert resolved[0]["decision"] == "deny"
    assert resolved[0]["resolved_by"] is None
    assert resolved[0]["actor"] == "reviewer"
    assert resolved[0]["reason"] == "审查否决"
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
        await wait_until(lambda approval_id=approval_id: approval_id in broker.pending)
        broker.resolve(approval_id, "allow")
        await task
    assert len(broker._resolved) == capacity
    latest = broker.resolution(f"a-{capacity + 4}")
    assert latest is not None
    assert latest["decision"] == "allow"
    assert latest["resolved_by"] == "desktop"
    assert latest["actor"] == "user"
    assert latest["resolved_at"]
