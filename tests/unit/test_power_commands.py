"""power.get_status 命令与电源监视线程测试（V0.3.7 集成波）。

契约：``docs/plans/V0.3.7-契约冻结.md`` §1.5/§2.1/§8。
- 命令成功/失败路径：monkeypatch 模块内 ``read_power_status``；
- 监视线程：注入返回合法 powercfg 输出的假 ``CompletedProcess`` runner，
  让真实解析跑（不绕解析），用真实时钟断言事件节奏。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

import pair_harness.desktop_backend.application_service as app_service
from pair_harness.desktop_backend.application_service import (
    ServiceError,
    build_demo_service,
)
from pair_harness.desktop_backend.power import PowerStatus, PowerStatusError


@pytest.fixture
def service(tmp_path: Path):
    events: list[dict] = []
    svc = build_demo_service(
        database=tmp_path / "db" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    yield SimpleNamespace(svc=svc, events=events)
    svc.store.close()


def _status(*, remote_serve_enabled: bool, ac: int = 1800, dc: int = 600) -> PowerStatus:
    return PowerStatus(
        supported=True,
        platform="win32",
        plan_name="平衡",
        ac_sleep_timeout_seconds=ac,
        dc_sleep_timeout_seconds=dc,
        remote_serve_enabled=remote_serve_enabled,
        threshold_seconds=900,
        at_risk=False,
        reason="AC/DC 睡眠超时均不低于阈值",
        checked_at="2026-09-02T12:00:00+08:00",
    )


# ---------------------------------------------------------------- 命令成功/失败


async def test_power_get_status_success(service, monkeypatch) -> None:
    """成功路径：返回 dict 字段齐全、threshold_seconds==900。"""

    def fake_read(*, remote_serve_enabled, runner=None, now=None):
        return _status(remote_serve_enabled=remote_serve_enabled)

    monkeypatch.setattr(app_service, "read_power_status", fake_read)
    result = await service.svc._power_get_status({})
    assert result["supported"] is True
    assert result["platform"] == "win32"
    assert result["plan_name"] == "平衡"
    assert result["ac_sleep_timeout_seconds"] == 1800
    assert result["dc_sleep_timeout_seconds"] == 600
    assert result["remote_serve_enabled"] is False
    assert result["threshold_seconds"] == 900
    assert result["at_risk"] is False
    assert result["reason"]
    assert result["checked_at"]


async def test_power_get_status_failure_preserves_original(service, monkeypatch) -> None:
    """失败路径：PowerStatusError → power_status_unavailable，message 含原文。"""

    def boom(*, remote_serve_enabled, runner=None, now=None):
        raise PowerStatusError("powercfg 调用超时（>10s）：timeout expired")

    monkeypatch.setattr(app_service, "read_power_status", boom)
    with pytest.raises(ServiceError) as excinfo:
        await service.svc._power_get_status({})
    assert excinfo.value.code == "power_status_unavailable"
    assert "powercfg 调用超时" in str(excinfo.value)


async def test_power_get_status_serve_enabled_flag(service, monkeypatch) -> None:
    """serve 置位：remote_serve_enabled=True 后返回 remote_serve_enabled==True。"""

    def fake_read(*, remote_serve_enabled, runner=None, now=None):
        return _status(remote_serve_enabled=remote_serve_enabled)

    monkeypatch.setattr(app_service, "read_power_status", fake_read)
    service.svc.remote_serve_enabled = True
    result = await service.svc._power_get_status({})
    assert result["remote_serve_enabled"] is True


# ---------------------------------------------------------------- 监视线程


def _scheme_out(name: str = "平衡") -> str:
    return f"电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  ({name}) *\n"


def _query_out(ac_hex: str = "00000708", dc_hex: str = "00000708") -> str:
    return (
        "电源设置 GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (睡眠)\n"
        "  电源设置 GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (睡眠超时)\n"
        f"    当前交流电源设置索引: 0x{ac_hex}\n"
        f"    当前直流电源设置索引: 0x{dc_hex}\n"
    )


def _runner_for(state: dict) -> Callable[[list[str]], subprocess.CompletedProcess]:
    """返回假 CompletedProcess runner：getactivescheme 固定，query 取 state['ac']。"""

    def runner(args: list[str]) -> subprocess.CompletedProcess:
        if args == ["powercfg", "/getactivescheme"]:
            stdout = _scheme_out()
        else:
            stdout = _query_out(ac_hex=state["ac"])
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=stdout, stderr=""
        )

    return runner


def _wait_until(events: list[dict], target: int, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sum(1 for e in events if e["event"] == "power.status_changed") >= target:
            return
        time.sleep(0.02)
    pytest.fail(f"等待 power.status_changed >= {target} 超时")


def test_power_monitor_emits_initial_and_change_only(service) -> None:
    """事件节奏：初始一次 + 状态变化一次 = 恰好 2 次；状态不变不再 emit。"""
    state = {"ac": "00000708"}  # 1800
    runner = _runner_for(state)
    service.svc.start_power_monitor(runner=runner, interval_seconds=0.05)
    try:
        _wait_until(service.events, 1)
        # 状态不变，跨多个轮询周期不应再有新事件。
        time.sleep(0.16)
        count = sum(
            1 for e in service.events if e["event"] == "power.status_changed"
        )
        assert count == 1
        # 状态变化（AC 1800 → 600）→ 第二次 emit。
        state["ac"] = "00000258"
        _wait_until(service.events, 2)
        count = sum(
            1 for e in service.events if e["event"] == "power.status_changed"
        )
        assert count == 2
        payload = service.events[-1]["payload"]
        assert payload["ac_sleep_timeout_seconds"] == 600
        assert payload["plan_name"] == "平衡"
    finally:
        service.svc.stop_power_monitor()
    assert service.svc._power_monitor_thread is None


def test_power_monitor_stop_and_idempotent_start(service) -> None:
    """重复 start 幂等（同一线程）；stop 后线程退出，可重新 start。"""
    state = {"ac": "00000708"}
    runner = _runner_for(state)
    service.svc.start_power_monitor(runner=runner, interval_seconds=0.05)
    first = service.svc._power_monitor_thread
    service.svc.start_power_monitor(runner=runner, interval_seconds=0.05)
    assert service.svc._power_monitor_thread is first  # 已在跑则跳过
    service.svc.stop_power_monitor()
    assert service.svc._power_monitor_thread is None

    # 未启动时 stop 是 no-op。
    service.svc.stop_power_monitor()
    # 停止后可重新 start。
    service.svc.start_power_monitor(runner=runner, interval_seconds=0.05)
    assert service.svc._power_monitor_thread is not None
    service.svc.stop_power_monitor()
    assert service.svc._power_monitor_thread is None


def test_power_monitor_read_failure_no_synthetic_event(service, caplog) -> None:
    """读取失败不合成事件：保留上次状态、如实写 stderr 日志、下轮重试。"""
    calls = {"n": 0}

    def flaky_runner(args: list[str]) -> subprocess.CompletedProcess:
        calls["n"] += 1
        # 首次完整读取（getactivescheme + query 两调）成功；此后全部失败。
        if calls["n"] <= 2:
            stdout = (
                _scheme_out()
                if args == ["powercfg", "/getactivescheme"]
                else _query_out()
            )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=stdout, stderr=""
            )
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout="", stderr="powercfg: 拒绝访问"
        )

    service.svc.start_power_monitor(runner=flaky_runner, interval_seconds=0.05)
    try:
        _wait_until(service.events, 1)
        time.sleep(0.16)
        # 后续读取全部失败 → 不产生任何新事件（不伪造状态）。
        count = sum(
            1 for e in service.events if e["event"] == "power.status_changed"
        )
        assert count == 1
        # Let It Fail：原始错误如实进入日志（含退出码与 stderr 摘要）。
        assert any("电源状态读取失败" in rec.message for rec in caplog.records)
        assert any("powercfg: 拒绝访问" in rec.message for rec in caplog.records)
    finally:
        service.svc.stop_power_monitor()
