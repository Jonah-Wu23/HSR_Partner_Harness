"""V0.3.9 R2 复测批次：服务商探测失败原因不得为空。

V039-R2-001：``config.test_connection`` 在连接层失败时曾显示「连接失败：」，
冒号后为空——本机 ``httpx.ConnectError`` 的 ``str(exc)`` 为空字符串时
（证据 ``repr(exc) == ConnectError('')``）必现，用户无从定位。回合失败路径
（V039-S4-015）已有 ``_failure_reason`` 回落，本文件验证探测路径接入同一回落：
异常自述非空时原样呈现，自述为空时回落到真实类型名。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand


def command(request_id: str, method: str, **params: Any) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


async def _start_probe_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
):
    """构造真实模式探测场景：账号配置指向本机不可达端点，HTTP 层如实失败。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    await service.handle_command(
        command(
            "cfg-1",
            "config.set",
            updates={
                "dialogue.provider": "openai_compatible",
                "dialogue.base_url": "https://127.0.0.1:1/v1",
                "dialogue.model": "compat-model",
                "dialogue.api_key": "sk-probe",
            },
        )
    )
    service._demo = False

    async def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(httpx.AsyncClient, "post", refuse)
    return service


async def test_test_connection_failure_reason_is_never_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V039-R2-001：自述为空的连接失败必须回落出真实原因，不能只剩「连接失败：」。"""
    failure = httpx.ConnectError("")
    assert str(failure) == "", "夹具必须复刻自述为空的连接失败"
    service = await _start_probe_service(tmp_path, monkeypatch, failure)
    try:
        result = await service.handle_command(
            command("probe-1", "config.test_connection")
        )
        # 失败状态如实保留，只是原因不能是空壳。
        assert result["ok"] is False
        assert result["message"].startswith("连接失败：")
        reason = result["message"][len("连接失败：") :]
        assert reason, "前端必须拿到非空失败原因"
        assert reason == "ConnectError", "回落出真实异常类型名，不编造未观测信息"
    finally:
        service._demo = True
        await service.shutdown()


async def test_test_connection_keeps_existing_failure_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V039-R2-001：自述非空的失败原因原样呈现，回落只补空壳、不改写内容。"""
    failure = httpx.ConnectError("All connection attempts failed")
    service = await _start_probe_service(tmp_path, monkeypatch, failure)
    try:
        result = await service.handle_command(
            command("probe-2", "config.test_connection")
        )
        assert result["ok"] is False
        assert result["message"] == "连接失败：All connection attempts failed"
    finally:
        service._demo = True
        await service.shutdown()
