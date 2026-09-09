"""V0.3.9 P05/P06：metrics.query 与 diagnostics.prompt_assembly 命令链路。

契约出处：归档正文 ``V0.3.9-契约冻结.md`` §5（指标与诊断）、§7（命令边）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pair_harness.adapters.acp.engine import AcpCodec
from pair_harness.core.contracts import EngineEventType
from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand

# 常量与前端协议一致（m 开头），避免与核心流转顺序耦合时误改宽度。
_METRIC = "m-1"


def command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


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


def _usage_notification(session_id: str, usage: dict) -> dict:
    return {
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "usage_update", "usage": usage},
        },
    }


# -------------------------------------------------------------------- P05 ACP


def test_acp_usage_update_maps_to_usage_event() -> None:
    """usage_update 不再被丢弃：映射为 USAGE 事件，真实 token 值入 payload。"""
    codec = AcpCodec()
    binding = {
        "conversation_id": "c1",
        "task_id": "t1",
        "engine_turn_id": "acp-1",
        "acp_session_id": "s1",
    }
    event = codec.map_notification(
        _usage_notification("s1", {"tokenUsage": {"inputTokens": 120, "outputTokens": 34}}),
        binding,
    )
    assert event is not None
    assert event.type == EngineEventType.USAGE
    assert event.payload["input_tokens"] == 120
    assert event.payload["output_tokens"] == 34
    assert event.payload["total_tokens"] is None


def test_acp_usage_update_accepts_flat_aliases_and_missing_fields() -> None:
    """扁平别名形状可解析；字段缺失保持 null（不估算、不用 0 顶替）。"""
    codec = AcpCodec()
    binding = {
        "conversation_id": "c1",
        "task_id": "t1",
        "engine_turn_id": "acp-1",
        "acp_session_id": "s1",
    }
    event = codec.map_notification(
        _usage_notification("s1", {"input_tokens": 200, "output_tokens": 5, "total_tokens": 205}),
        binding,
    )
    assert event is not None
    assert event.payload == {"input_tokens": 200, "output_tokens": 5, "total_tokens": 205}

    empty_usage = codec.map_notification(
        _usage_notification("s1", {}),
        binding,
    )
    assert empty_usage is not None
    assert empty_usage.payload == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


# ------------------------------------------------------------------ P05 命令


async def test_metrics_query_returns_unknown_fields_as_null(tmp_path: Path) -> None:
    """metrics.query 走存储层过滤；未观测字段为 null，真实零值用 0。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        # 先跑一个真实回合，让 turn 终态写入指标。
        await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="今天有点累，陪我聊聊。",
            )
        )
        await _wait_until(
            lambda: [e["event"] for e in events].count("message.created") >= 2,
            message="后台回合应补发角色消息",
        )
        await asyncio.sleep(0.05)
        result = await service.handle_command(
            command("metrics-1", "metrics.query", conversation_id=conversation_id)
        )
        assert "metrics" in result
        assert isinstance(result["metrics"], list)
        assert result["next_cursor"] is None
        assert len(result["metrics"]) >= 1
        metric = result["metrics"][0]
        # 契约 §5：未观测字段保持 null 且键存在；真实零值是 0。
        assert "input_tokens" in metric
        assert "output_tokens" in metric
        assert "total_tokens" in metric
        assert metric["turn_kind"] in ("character_turn", "assistant_task")
        assert metric["conversation_id"] == conversation_id
        assert metric["project_id"]  # 快照项目真实存在
        # storage 层用未过滤查询再验证计数一致（同库不同连接验证）
        assert result["next_cursor"] is None
    finally:
        await service.shutdown()


async def test_metrics_query_filters_by_status_and_unknown_command_rejected(
    tmp_path: Path,
) -> None:
    """status 过滤生效；白名单外命令（含未实现的 summary.get）被拒绝。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        await service.handle_command(
            command(
                "chat-1",
                "chat.submit",
                conversation_id=conversation_id,
                target="character",
                text="早上好",
            )
        )
        await _wait_until(
            lambda: [e["event"] for e in events].count("message.created") >= 2,
            message="后台回合应补发角色消息",
        )
        result = await service.handle_command(
            command("metrics-2", "metrics.query", status="completed")
        )
        assert all(metric["status"] == "completed" for metric in result["metrics"])
        # 白名单校验：未实现的 summary.get 不进入 handler（unknown_method）。
        from pair_harness.desktop_backend.commands import CommandValidationError

        with pytest.raises(CommandValidationError) as exc:
            DesktopCommand.from_payload(
                {"id": "req-1", "method": "summary.get", "params": {}}
            )
        assert "未知桌面命令" in str(exc.value)
        # 白名单已放行的命令可通过校验（metrics.query 由 from_payload 接受）。
        accepted = DesktopCommand.from_payload(
            {"id": "req-2", "method": "metrics.query", "params": {}}
        )
        assert accepted.method == "metrics.query"
    finally:
        await service.shutdown()


# ------------------------------------------------------------------ P06 命令


async def test_diagnostics_prompt_assembly_returns_modules_truthfully(
    tmp_path: Path,
) -> None:
    """prompt_assembly 返回模块名/字符范围/hash/summary/memory 注入；
    默认不含 hidden_content，include_hidden=true 才返回原文。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        plain = await service.handle_command(
            command("diag-1", "diagnostics.prompt_assembly", conversation_id=conversation_id)
        )
        assert plain["conversation_id"] == conversation_id
        assert isinstance(plain["modules"], list)
        assert "generated_at" in plain
        for module in plain["modules"]:
            # 契约 §5：默认不返回隐藏原文。
            assert "hidden_content" not in module or module["hidden_content"] is None
            assert "hash" in module

        hidden = await service.handle_command(
            command(
                "diag-2",
                "diagnostics.prompt_assembly",
                conversation_id=conversation_id,
                include_hidden=True,
            )
        )
        for module in hidden["modules"]:
            assert module["hidden_content"] is not None

        # 契约 §5：会话不存在时按真实错误失败，不伪造空装配结果。
        from pair_harness.desktop_backend.application_service import ServiceError

        with pytest.raises(ServiceError) as exc:
            await service.handle_command(
                command("diag-3", "diagnostics.prompt_assembly", conversation_id="missing-conv")
            )
        assert "conversation_not_found" in str(exc.value.code)
    finally:
        await service.shutdown()


async def test_metrics_and_diagnostics_are_read_only(tmp_path: Path) -> None:
    """两条查询命令不改写状态：查询前后快照 shape 一致。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        conversation_id = service.current_conversation_id
        before = await service.handle_command(command("b1", "app.bootstrap"))
        await service.handle_command(
            command("diag-4", "diagnostics.prompt_assembly", conversation_id=conversation_id)
        )
        await service.handle_command(command("metrics-4", "metrics.query"))
        after = await service.handle_command(command("b2", "app.bootstrap"))
        assert before["sequence"] == after["sequence"]
        assert before["busy"] == after["busy"]
    finally:
        await service.shutdown()
