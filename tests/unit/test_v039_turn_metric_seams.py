"""V0.3.9 回合指标接缝：来源身份、失败回执与首事件时间。

三条缺陷：
- 手机回合指标恒显示 desktop（origin/device 未从传输层注入走到 TurnMetric）；
- failed 回合的 failure_message 恒为空串；
- first_event_at 取到终态时间、first_event_latency_ms 恒 null。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import ApprovalMode
from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.storage.records import TurnMetric, TurnMetricQuery


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


async def _wait_until(predicate, *, message: str, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


def _metric_for(service, conversation_id: str, turn_id: str) -> TurnMetric | None:
    page = service.store.query_turn_metrics(
        TurnMetricQuery(conversation_id=conversation_id, limit=50)
    )
    for metric in page.items:
        if metric.turn_id == turn_id:
            return metric
    return None


async def _completed_metric(
    service, conversation_id: str, turn_id: str
) -> TurnMetric:
    await _wait_until(
        lambda: (_metric_for(service, conversation_id, turn_id) is not None),
        message="回合终态应写入指标",
    )
    metric = _metric_for(service, conversation_id, turn_id)
    assert metric is not None
    return metric


@pytest.mark.asyncio
async def test_remote_submit_metric_keeps_origin_and_device(tmp_path: Path) -> None:
    """手机发起的 chat.submit：指标来源为 remote，并携带设备 key/名称。

    传输层（router/ws_server）把 origin/remote_device_key/remote_device_name
    注入 DesktopCommand；服务层必须透传到 TurnMetric，而不是硬编码 desktop。
    """
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            DesktopCommand(
                request_id="chat-remote",
                method="chat.submit",
                params={
                    "conversation_id": conversation_id,
                    "target": "character",
                    "text": "手机发来的消息",
                },
                origin="remote",
                connection_key="phone-conn",
                remote_device_key="device-key-abc",
                remote_device_name="测试手机",
            )
        )
        metric = await _completed_metric(service, conversation_id, result["turn_id"])
        assert metric.origin == "remote"
        assert metric.remote_device_key == "device-key-abc"
        assert metric.remote_device_name == "测试手机"
        assert metric.source_message_id == result["message_id"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_desktop_submit_metric_stays_desktop(tmp_path: Path) -> None:
    """桌面入口提交仍是 desktop，且不带设备字段。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "chat-desktop",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="桌面发来的消息",
            )
        )
        metric = await _completed_metric(service, conversation_id, result["turn_id"])
        assert metric.origin == "desktop"
        assert metric.remote_device_key is None
        assert metric.remote_device_name is None
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_failed_turn_metric_carries_real_failure_reason(tmp_path: Path) -> None:
    """失败回合的 failure_message 必须是真实 reason，不得为空壳。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        await service.handle_command(
            command(
                "settings-1",
                "project.update_settings",
                approval_mode=ApprovalMode.FULL_AUTO.value,
            )
        )

        class FailingEngine(ScriptedCodingEngine):
            """open_session 正常，run_turn 立即抛错——模拟引擎崩溃。"""

            async def run_turn(self, session_ref, request):
                raise RuntimeError("引擎爆炸：demo 注入")
                yield  # pragma: no cover - 保持 async generator 形态

        service.orchestrator.coding_engine = FailingEngine()
        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "chat-fail",
                "chat.submit",
                conversation_id=conversation_id,
                target="assistant",
                mode="collaboration",
                text="检查项目",
            )
        )
        await _wait_until(
            lambda: (
                _metric_for(service, conversation_id, result["turn_id"]) is not None
            ),
            message="失败回合终态应写入指标",
        )
        metric = _metric_for(service, conversation_id, result["turn_id"])
        assert metric is not None
        assert metric.status == "failed"
        assert metric.failure_type == "turn_failed"
        assert metric.failure_message
        assert "引擎爆炸" in metric.failure_message
        # 没有流式事件的失败回合：首事件保持 null，不回落到终态时间。
        assert metric.first_event_at is None
        assert metric.first_event_latency_ms is None
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_first_event_at_is_real_first_stream_event(tmp_path: Path) -> None:
    """first_event_at 是首个真实流式事件的时间，早于完成时间，latency 非空。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        original_stream = service.dialogue_model.stream_reply

        async def delayed_stream(request):
            first = True
            async for event in original_stream(request):
                yield event
                if first:
                    first = False
                    # 首个 delta 与终态之间制造可测间隔，证明指标取的是
                    # 首事件时间而不是终态时间。
                    await asyncio.sleep(0.05)

        service.dialogue_model.stream_reply = delayed_stream  # type: ignore[method-assign]

        conversation_id = service.current_conversation_id
        result = await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="今天有点累",
            )
        )
        metric = await _completed_metric(service, conversation_id, result["turn_id"])
        assert metric.first_event_at is not None
        assert metric.completed_at is not None
        assert metric.first_event_at < metric.completed_at
        assert metric.first_event_latency_ms is not None
        assert metric.duration_ms is not None
        # 首事件在回合开始后不久到达，与完成之间隔着注入的 50ms；
        # 若指标回落到终态时间，这个差值会接近 0。
        assert metric.first_event_latency_ms <= metric.duration_ms
        assert metric.duration_ms - metric.first_event_latency_ms >= 40
        assert metric.source_message_id == result["message_id"]
    finally:
        await service.shutdown()
