from __future__ import annotations

import asyncio
import sys

from pair_harness.desktop_backend import power
from pair_harness.desktop_backend.power import PowerStatusError
from pair_harness.desktop_backend.ws_server import RemoteServe
from tests.service_helpers import call, expect_service_error, wait_until

# 电源方案只能经 powrprof 读取本机设置，测试不得修改本机电源方案；需要指定读数或
# 读取失败的用例替换 power._read_sleep_settings 这一 ctypes 平台边界。
_ACCESS_DENIED = "PowerReadACValueIndex 失败（错误码 5）：拒绝访问。"


def _status_events(service) -> list[dict]:
    return service.event_log.payloads("power.status_changed")


async def test_power_get_status_reports_remote_serve_flag(service) -> None:
    before = await call(service, "p1", "power.get_status")
    assert before["supported"] is (sys.platform == "win32")
    assert before["remote_serve_enabled"] is False

    service.attach_remote_serve(RemoteServe(port=8765, lan=False, host="127.0.0.1"))
    after = await call(service, "p2", "power.get_status")
    assert after["remote_serve_enabled"] is True


async def test_power_get_status_failure_preserves_original(service, monkeypatch) -> None:
    def denied() -> tuple[str, int, int]:
        raise PowerStatusError(_ACCESS_DENIED)

    monkeypatch.setattr(power.sys, "platform", "win32")
    monkeypatch.setattr(power, "_read_sleep_settings", denied)
    await expect_service_error(
        lambda: call(service, "p1", "power.get_status"),
        "power_status_unavailable",
        contains=_ACCESS_DENIED,
    )


async def test_power_monitor_emits_initial_and_change_only(service, monkeypatch) -> None:
    """启动时发一次，读数不变不再发，读数变化再发一次。"""
    state = {"ac": 1800}
    monkeypatch.setattr(power.sys, "platform", "win32")
    monkeypatch.setattr(power, "_read_sleep_settings", lambda: ("平衡", state["ac"], 1800))
    service.start_power_monitor(interval_seconds=0.05)

    await wait_until(lambda: len(_status_events(service)) == 1)
    await asyncio.sleep(0.16)
    assert len(_status_events(service)) == 1

    state["ac"] = 600
    await wait_until(lambda: len(_status_events(service)) == 2)
    assert _status_events(service)[-1]["ac_sleep_timeout_seconds"] == 600


async def test_power_monitor_read_failure_emits_nothing_and_logs(
    service, caplog, monkeypatch
) -> None:
    """读取失败不合成事件，保留上次状态并把原始错误写入日志。"""
    calls = {"n": 0}

    def flaky_read() -> tuple[str, int, int]:
        calls["n"] += 1
        if calls["n"] == 1:
            return "平衡", 1800, 1800
        raise PowerStatusError(_ACCESS_DENIED)

    monkeypatch.setattr(power.sys, "platform", "win32")
    monkeypatch.setattr(power, "_read_sleep_settings", flaky_read)
    service.start_power_monitor(interval_seconds=0.05)

    await wait_until(lambda: calls["n"] >= 3)
    assert len(_status_events(service)) == 1
    assert any(_ACCESS_DENIED in rec.getMessage() for rec in caplog.records)


async def test_shutdown_cancels_power_monitor(service) -> None:
    service.start_power_monitor(interval_seconds=0.05)
    task = service._power_monitor_task
    await call(service, "s-1", "app.shutdown")
    assert task.done()
    assert service._power_monitor_task is None
