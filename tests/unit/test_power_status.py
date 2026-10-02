from __future__ import annotations

import sys

import pytest

from pair_harness.desktop_backend import power

# 指定读数的用例替换 power._read_sleep_settings 这一 powrprof 平台边界：
# 测试不得修改本机电源方案。


@pytest.mark.parametrize(
    "ac,dc,serve,expected_at_risk,reason_assert",
    [
        # 600 < 900 且 ≠ 0 → 命中 AC
        (600, 0, True, True, lambda r: "AC" in r and "600 秒低于阈值 900 秒" in r),
        # 0 是从不；7200 ≥ 900 → 不命中
        (0, 7200, True, False, lambda r: r == "AC/DC 睡眠超时均不低于阈值"),
        # 960 ≥ 900 → 不命中
        (960, 0, True, False, lambda r: r == "AC/DC 睡眠超时均不低于阈值"),
        # 双 0（从不）→ 不命中
        (0, 0, True, False, lambda r: r == "AC/DC 睡眠超时均不低于阈值"),
        # 远程服务未开启 → 无论数值一律 False
        (600, 300, False, False, lambda r: r == "远程服务未开启"),
    ],
)
def test_at_risk_matrix(
    monkeypatch,
    ac: int,
    dc: int,
    serve: bool,
    expected_at_risk: bool,
    reason_assert,
) -> None:
    monkeypatch.setattr(power.sys, "platform", "win32")
    monkeypatch.setattr(power, "_read_sleep_settings", lambda: ("平衡", ac, dc))
    st = power.read_power_status(remote_serve_enabled=serve)
    assert st.at_risk is expected_at_risk
    assert reason_assert(st.reason)


def test_non_windows_returns_unsupported_without_reading(monkeypatch) -> None:
    monkeypatch.setattr(power.sys, "platform", "linux")

    def unexpected_read() -> tuple[str, int, int]:
        raise AssertionError("非 Windows 不应读取 powrprof")

    monkeypatch.setattr(power, "_read_sleep_settings", unexpected_read)
    st = power.read_power_status(remote_serve_enabled=True)
    assert st.supported is False
    assert st.platform == "linux"
    assert st.plan_name == ""
    assert st.ac_sleep_timeout_seconds is None
    assert st.dc_sleep_timeout_seconds is None
    assert st.at_risk is False
    assert st.reason == "当前平台不支持电源状态检测"


@pytest.mark.skipif(sys.platform != "win32", reason="需要本机 Windows powrprof")
def test_real_powrprof_read_only() -> None:
    st = power.read_power_status(remote_serve_enabled=False)
    assert st.supported is True
    assert st.platform == "win32"
    assert st.ac_sleep_timeout_seconds is not None
    assert st.ac_sleep_timeout_seconds >= 0
    assert st.dc_sleep_timeout_seconds is not None
    assert st.dc_sleep_timeout_seconds >= 0
