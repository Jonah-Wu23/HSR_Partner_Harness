"""V0.3.9 自动压缩触发：消息流接入、阈值、防重入、失败与恢复。

契约出处：归档正文 ``.archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md``
§2（摘要触发阈值与保留最近原文）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pair_harness.core.contracts import (
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    MessageTarget,
)
from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


def make_message(conversation_id: str, text: str, index: int) -> Message:
    return Message(
        conversation_id=conversation_id,
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text=text,
        origin=MessageOrigin.USER,
        status=MessageStatus.DONE,
        message_id=f"m-{index}",
    )


async def _wait_until(
    predicate, *, message: str, timeout: float = 5.0
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


# ------------------------------------------------------------------ 阈值触发


async def test_auto_summary_triggers_on_message_count_threshold(tmp_path: Path) -> None:
    """未压缩角色消息达到 80 条时自动触发 summary.started/completed。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        for index in range(80):
            service.orchestrator._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=f"消息 {index}",
                origin=MessageOrigin.USER,
            )
        await _wait_until(
            lambda: any(e["event"] == "summary.started" for e in events),
            message="80 条消息应触发自动压缩 started",
        )
        await _wait_until(
            lambda: any(e["event"] == "summary.completed" for e in events),
            message="自动压缩应广播 completed",
        )
        summaries = service.store.list_summaries(conversation_id)
        assert any(s.status == "completed" for s in summaries)
        # 覆盖终点推进：投影侧以最近消息为覆盖终点。
        cover = service.orchestrator.summary_coverage(conversation_id)
        assert cover is not None
    finally:
        await service.shutdown()


async def test_auto_summary_triggers_on_utf8_bytes_threshold(tmp_path: Path) -> None:
    """未压缩正文达到 256KiB 时自动触发（字节阈值独立于条数）。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        # 单条消息约 4KiB，60 条即 240KiB 不够；用长文本逼近 256KiB。
        big_text = "字" * 4096  # UTF-8 约 12KiB（含 BOM 外全是 3 字节）
        for index in range(24):
            service.orchestrator._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=f"{index}:{big_text}",
                origin=MessageOrigin.USER,
            )
        await _wait_until(
            lambda: any(e["event"] == "summary.started" for e in events),
            message="字节阈值应触发自动压缩",
        )
        await _wait_until(
            lambda: any(e["event"] == "summary.completed" for e in events),
            message="字节阈值触发后应 broadcast completed",
        )
    finally:
        await service.shutdown()


# ------------------------------------------------------------------ 防重入


async def test_auto_summary_does_not_reenter_while_in_flight(tmp_path: Path) -> None:
    """同会话已有自动压缩任务在跑时不得重复触发。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        for index in range(81):
            service.orchestrator._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=f"消息 {index}",
                origin=MessageOrigin.USER,
            )
        # 第 81 条在任务仍在途时不应再次触发 started（防重入靠
        # _auto_summary_in_flight 标记）。
        started_count = [e for e in events if e["event"] == "summary.started"]
        await _wait_until(
            lambda: len(started_count) >= 1,
            message="至少一次 started",
        )
        await _wait_until(
            lambda: any(e["event"] == "summary.completed" for e in events),
            message="完成后任务清除",
        )
        final_started = [e for e in events if e["event"] == "summary.started"]
        assert len(final_started) == 1  # 同一轮压缩只触发一次
    finally:
        await service.shutdown()


# ------------------------------------------------------------------ 失败与状态


async def test_auto_summary_failure_preserves_real_error(tmp_path: Path) -> None:
    """自动压缩失败保留真实失败状态并广播 summary.failed（不伪造成功）。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        # 让生成模型返回 None（模拟生成失败）：换掉 dialogue_model。
        class _FailModel:
            async def generate_summary(self, **kwargs):  # type: ignore[no-untyped-def]
                return None

            async def generate_title(self, **kwargs):  # type: ignore[no-untyped-def]
                return None

        service.dialogue_model = _FailModel()  # type: ignore[assignment]
        for index in range(80):
            service.orchestrator._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=f"消息 {index}",
                origin=MessageOrigin.USER,
            )
        await _wait_until(
            lambda: any(e["event"] == "summary.failed" for e in events),
            message="生成失败应广播 summary.failed",
        )
        failed_events = [e for e in events if e["event"] == "summary.failed"]
        assert failed_events
        assert failed_events[0]["payload"]["error_code"] == "summary_provider_error"
        assert "未返回 JSON 对象" in failed_events[0]["payload"]["error"]
    finally:
        await service.shutdown()


async def test_auto_summary_state_recovers_after_restart(tmp_path: Path) -> None:
    """重启后已完成摘要的覆盖终点从存储恢复（投影不重算已覆盖消息）。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        for index in range(80):
            service.orchestrator._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=f"消息 {index}",
                origin=MessageOrigin.USER,
            )
        await _wait_until(
            lambda: any(e["event"] == "summary.completed" for e in events),
            message="摘要完成",
        )
        cover_before = service.orchestrator.summary_coverage(conversation_id)
        assert cover_before is not None
        await service.shutdown()

        # 重启：新服务实例从同一数据库恢复，覆盖终点仍在。
        events2: list[dict] = []
        service2 = build_demo_service(
            database=tmp_path / "data" / "pair_harness.db",
            project_root=tmp_path,
            event_sink=events2.append,
        )
        try:
            restored = service2.orchestrator.summary_coverage(conversation_id)
            assert restored == cover_before
        finally:
            await service2.shutdown()
    finally:
        await service.shutdown()


# ------------------------------------------------------------------ 装配消费


async def test_assembly_consumes_completed_summary(tmp_path: Path) -> None:
    """自动压缩完成后：recent_completed_summary 返回可用摘要，装配备齐模块。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        for index in range(80):
            service.orchestrator._message(
                conversation_id=conversation_id,
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=f"消息 {index}",
                origin=MessageOrigin.USER,
            )
        await _wait_until(
            lambda: any(e["event"] == "summary.completed" for e in events),
            message="摘要完成",
        )
        # 摘要产出被装配消费：recent_completed_summary 返回 core 形状。
        latest = service._recent_completed_summary(conversation_id)
        assert latest is not None
        assert latest["status"] == "completed"
        assert isinstance(latest["content"], dict)
        # 装配器接受的 core ConversationSummary 校验通过（content=dict 形状）。
        from pair_harness.core.summary import ConversationSummary

        core_summary = ConversationSummary.model_validate(latest)
        assert core_summary.status == "completed"
        assert core_summary.content is not None
    finally:
        await service.shutdown()
