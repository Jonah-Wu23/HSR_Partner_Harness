from __future__ import annotations

import asyncio

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.storage.records import TurnMetric, TurnMetricQuery
from tests.service_helpers import call, wait_until


class _CrashingEngine(ScriptedCodingEngine):
    """run_turn 一开始就抛错的编程助手。"""

    async def run_turn(self, session_ref, request):
        raise RuntimeError("引擎爆炸")
        yield  # pragma: no cover - 保持 async generator 形态


class _PauseAfterFirstEventModel(ScriptedDialogueModel):
    """首个流式事件之后停顿 50ms 再给出终态。"""

    async def stream_reply(self, request):
        first = True
        async for event in super().stream_reply(request):
            yield event
            if first:
                first = False
                await asyncio.sleep(0.05)


def _metric_for(service, conversation_id: str, turn_id: str) -> TurnMetric | None:
    page = service.store.query_turn_metrics(
        TurnMetricQuery(conversation_id=conversation_id, limit=50)
    )
    return next((metric for metric in page.items if metric.turn_id == turn_id), None)


async def _recorded_metric(service, conversation_id: str, turn_id: str) -> TurnMetric:
    await wait_until(
        lambda: _metric_for(service, conversation_id, turn_id) is not None,
        message="回合终态应写入指标",
    )
    return _metric_for(service, conversation_id, turn_id)


@pytest.mark.parametrize(
    ("origin", "device_key", "device_name"),
    [
        pytest.param("remote", "device-key-abc", "测试手机", id="remote"),
        pytest.param("desktop", None, None, id="desktop"),
    ],
)
async def test_submit_metric_keeps_origin_and_device(
    service, origin: str, device_key: str | None, device_name: str | None
) -> None:
    """传输层注入的来源与设备身份随提交写进回合指标。"""
    conversation_id = service.current_conversation_id
    result = await service.handle_command(
        DesktopCommand(
            request_id="chat-1",
            method="chat.submit",
            params={
                "conversation_id": conversation_id,
                "target": "character",
                "text": "发来的消息",
            },
            origin=origin,
            connection_key="phone-conn" if device_key else None,
            remote_device_key=device_key,
            remote_device_name=device_name,
        )
    )
    metric = await _recorded_metric(service, conversation_id, result["turn_id"])
    assert metric.origin == origin
    assert metric.remote_device_key == device_key
    assert metric.remote_device_name == device_name
    assert metric.source_message_id == result["message_id"]


async def test_failed_turn_metric_carries_real_failure_reason(service) -> None:
    service.orchestrator.coding_engine = _CrashingEngine()
    conversation_id = service.current_conversation_id
    result = await call(
        service,
        "chat-fail",
        "chat.submit",
        conversation_id=conversation_id,
        target="assistant",
        mode="collaboration",
        text="检查项目",
    )
    metric = await _recorded_metric(service, conversation_id, result["turn_id"])
    assert metric.status == "failed"
    assert metric.failure_type == "turn_failed"
    assert metric.failure_message == "引擎爆炸"
    # 没有任何流式事件的回合，首事件时间保持 null。
    assert metric.first_event_at is None
    assert metric.first_event_latency_ms is None


async def test_failed_receipt_metric_carries_receipt_errors(service) -> None:
    # 引擎以 turn.failed 收尾、不抛异常：失败原因只在回执的 errors 里。
    service.orchestrator.coding_engine = ScriptedCodingEngine(fail_tool=True)
    await call(service, "settings", "project.update_settings", approval_mode="full_auto")
    conversation_id = service.current_conversation_id
    result = await call(
        service,
        "chat-fail",
        "chat.submit",
        conversation_id=conversation_id,
        target="assistant",
        mode="collaboration",
        text="检查项目",
    )
    metric = await _recorded_metric(service, conversation_id, result["turn_id"])
    assert metric.status == "failed"
    assert metric.failure_type == "turn_failed"
    assert metric.failure_message == "模拟工具失败"


async def test_first_event_at_is_real_first_stream_event(service) -> None:
    service.orchestrator.dialogue_model = _PauseAfterFirstEventModel()
    conversation_id = service.current_conversation_id
    result = await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="character",
        text="今天有点累",
    )
    metric = await _recorded_metric(service, conversation_id, result["turn_id"])
    assert metric.first_event_at is not None
    assert metric.first_event_at < metric.completed_at
    # 首事件与完成之间隔着 50ms 停顿；取成终态时间的话两者几乎相等。
    assert metric.duration_ms - metric.first_event_latency_ms >= 40
    assert metric.source_message_id == result["message_id"]


async def test_metrics_query_returns_recorded_turn_and_filters_by_status(service) -> None:
    conversation_id = service.current_conversation_id
    result = await call(
        service,
        "chat-1",
        "chat.submit",
        conversation_id=conversation_id,
        target="character",
        text="今天有点累，陪我聊聊。",
    )
    await _recorded_metric(service, conversation_id, result["turn_id"])

    queried = await call(
        service, "metrics-1", "metrics.query", conversation_id=conversation_id
    )
    assert queried["next_cursor"] is None
    [metric] = queried["metrics"]
    assert metric["turn_id"] == result["turn_id"]
    assert metric["turn_kind"] == "character_turn"
    assert metric["status"] == "completed"
    # 演示模型不上报 usage：未观测的 token 字段保留键，值为 null。
    assert metric["input_tokens"] is None
    assert metric["output_tokens"] is None
    assert metric["total_tokens"] is None

    failed = await call(service, "metrics-2", "metrics.query", status="failed")
    assert failed["metrics"] == []
    completed = await call(service, "metrics-3", "metrics.query", status="completed")
    assert [item["turn_id"] for item in completed["metrics"]] == [result["turn_id"]]
