"""power 模块单元测试（V0.3.7 契约 §1.5 / §8）。

覆盖：真实形状样例解析（中文标签 + 8 位十六进制索引，GUID 行原样）、
16 位十六进制（冻结正则分支）、全角括号方案名、方案名缺失警告、
解析失败（索引不足 / 非零退出码 / 超时 / OSError / 缺 GUID）、
at_risk 判定矩阵、threshold 恒 900、非 Windows unsupported 形状
（runner 不被调用）、本机 Windows 真实只读读取。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime

import pytest

from pair_harness.desktop_backend import power

# 真实 powercfg /getactivescheme 输出（GUID 行原样，中文标签）。
SCHEME_OUT = "电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (平衡)\r\n"

# 命令常量（与生产代码两步调用保持一致）。
GETACTIVE = ("powercfg", "/getactivescheme")
QUERY = ("powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE")


def _cp(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _FakeRunner:
    """命令 → 预置 CompletedProcess 的假 runner；记录调用。"""

    def __init__(self, outputs: dict[tuple[str, ...], subprocess.CompletedProcess]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        key = tuple(args)
        self.calls.append(key)
        if key not in self.outputs:
            raise AssertionError(f"未预置的命令：{key}")
        return self.outputs[key]


def _query_out(ac: int, dc: int) -> str:
    """构造贴近本机真实输出的 STANDBYIDLE 查询文本（8 位十六进制索引）。"""
    return (
        "电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (平衡)\r\n"
        "  GUID 别名: SCHEME_BALANCED\r\n"
        "  子组 GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (睡眠)\r\n"
        "    GUID 别名: SUB_SLEEP\r\n"
        "    电源设置 GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (在此时间后睡眠)\r\n"
        "      GUID 别名: STANDBYIDLE\r\n"
        "      最小可能的设置: 0x00000000\r\n"
        "      最大可能的设置: 0xffffffff\r\n"
        "      可能的设置增量: 0x00000001\r\n"
        "      可能的设置单位: 秒\r\n"
        f"    当前交流电源设置索引: 0x{ac:08x}\r\n"
        f"    当前直流电源设置索引: 0x{dc:08x}\r\n"
        "\r\n"
    )


def _runner_for(ac: int, dc: int) -> _FakeRunner:
    return _FakeRunner({GETACTIVE: _cp(0, SCHEME_OUT), QUERY: _cp(0, _query_out(ac, dc))})


# ============================================================
# 解析成功
# ============================================================


class TestParseSuccess:
    def test_parses_real_shaped_output(self, monkeypatch) -> None:
        monkeypatch.setattr(power.sys, "platform", "win32")
        runner = _runner_for(ac=0x708, dc=0x78)  # 1800 / 120
        st = power.read_power_status(
            remote_serve_enabled=True,
            runner=runner,
            now=datetime(2026, 1, 2, 3, 4, 5),
        )
        assert st.supported is True
        assert st.platform == "win32"
        assert st.plan_name == "平衡"
        assert st.ac_sleep_timeout_seconds == 1800
        assert st.dc_sleep_timeout_seconds == 120
        assert st.remote_serve_enabled is True
        assert st.threshold_seconds == 900
        assert st.checked_at == datetime(2026, 1, 2, 3, 4, 5).astimezone().isoformat(
            timespec="seconds"
        )
        assert st.warnings == []
        # 两步调用的命令顺序与生产一致。
        assert runner.calls == [GETACTIVE, QUERY]

    def test_parses_16_digit_strict_branch(self, monkeypatch) -> None:
        # 契约冻结的 16 位十六进制索引形态：strict 分支按出现次序 第1=AC 第2=DC。
        query = (
            "Current AC Power Setting Index: 0x0000000000000384\r\n"
            "Current DC Power Setting Index: 0x0000000000000078\r\n"
        )
        runner = _FakeRunner({GETACTIVE: _cp(0, SCHEME_OUT), QUERY: _cp(0, query)})
        st = power.read_power_status(remote_serve_enabled=True, runner=runner)
        assert st.ac_sleep_timeout_seconds == 0x384  # 900
        assert st.dc_sleep_timeout_seconds == 0x78   # 120
        assert st.at_risk is True
        assert "DC" in st.reason

    def test_plan_name_fullwidth_parens(self, monkeypatch) -> None:
        # 全角括号「（…）」同样算方案名。
        scheme = "电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  （平衡）\r\n"
        runner = _FakeRunner({GETACTIVE: _cp(0, scheme), QUERY: _cp(0, _query_out(600, 600))})
        st = power.read_power_status(remote_serve_enabled=True, runner=runner)
        assert st.plan_name == "平衡"

    def test_missing_plan_name_records_warning(self, monkeypatch) -> None:
        scheme = "Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e\r\n"
        runner = _FakeRunner({GETACTIVE: _cp(0, scheme), QUERY: _cp(0, _query_out(600, 600))})
        st = power.read_power_status(remote_serve_enabled=True, runner=runner)
        assert st.plan_name == ""
        assert any("方案名称" in w for w in st.warnings)


# ============================================================
# 解析失败（Let It Fail：如实抛 PowerStatusError）
# ============================================================


class TestParseFailures:
    def test_single_index_line_raises(self, monkeypatch) -> None:
        query = "Current AC Power Setting Index: 0x0000000000000384\r\n"
        runner = _FakeRunner({GETACTIVE: _cp(0, SCHEME_OUT), QUERY: _cp(0, query)})
        with pytest.raises(power.PowerStatusError) as exc:
            power.read_power_status(remote_serve_enabled=True, runner=runner)
        assert "未找到" in str(exc.value)

    def test_nonzero_returncode_raises_with_stderr(self, monkeypatch) -> None:
        runner = _FakeRunner({GETACTIVE: _cp(1, stderr="没有权限访问电源方案")})
        with pytest.raises(power.PowerStatusError) as exc:
            power.read_power_status(remote_serve_enabled=True, runner=runner)
        assert "没有权限访问电源方案" in str(exc.value)

    def test_timeout_raises(self, monkeypatch) -> None:
        def runner(args: list[str]) -> subprocess.CompletedProcess:
            raise subprocess.TimeoutExpired(cmd=args, timeout=10)

        with pytest.raises(power.PowerStatusError) as exc:
            power.read_power_status(remote_serve_enabled=True, runner=runner)
        assert "超时" in str(exc.value)

    def test_oserror_raises(self, monkeypatch) -> None:
        def runner(args: list[str]) -> subprocess.CompletedProcess:
            raise FileNotFoundError("powercfg 不存在")

        with pytest.raises(power.PowerStatusError) as exc:
            power.read_power_status(remote_serve_enabled=True, runner=runner)
        assert "失败" in str(exc.value)

    def test_missing_guid_raises(self, monkeypatch) -> None:
        scheme = "电源方案名称: (平衡)\r\n"  # 无 36 位 GUID
        runner = _FakeRunner({GETACTIVE: _cp(0, scheme), QUERY: _cp(0, _query_out(600, 600))})
        with pytest.raises(power.PowerStatusError) as exc:
            power.read_power_status(remote_serve_enabled=True, runner=runner)
        assert "GUID" in str(exc.value)


# ============================================================
# at_risk 判定矩阵（确定性推导）
# ============================================================


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
    runner = _runner_for(ac=ac, dc=dc)
    st = power.read_power_status(remote_serve_enabled=serve, runner=runner)
    assert st.at_risk is expected_at_risk
    assert reason_assert(st.reason)
    assert st.threshold_seconds == 900


# ============================================================
# 非 Windows unsupported 形状
# ============================================================


def test_non_windows_returns_unsupported_without_calling_runner(monkeypatch) -> None:
    monkeypatch.setattr(power.sys, "platform", "linux")
    calls: list[list[str]] = []

    def runner(args: list[str]) -> subprocess.CompletedProcess:
        calls.append(args)
        raise AssertionError("runner 不应被调用")

    st = power.read_power_status(remote_serve_enabled=True, runner=runner)
    assert calls == []
    assert st.supported is False
    assert st.platform == "linux"
    assert st.plan_name == ""
    assert st.ac_sleep_timeout_seconds is None
    assert st.dc_sleep_timeout_seconds is None
    assert st.at_risk is False
    assert st.reason == "当前平台不支持电源状态检测"


# ============================================================
# 本机 Windows 真实只读读取（不修改任何电源设置）
# ============================================================


@pytest.mark.skipif(sys.platform != "win32", reason="需要本机 Windows powercfg")
def test_real_powercfg_read_only() -> None:
    st = power.read_power_status(remote_serve_enabled=False)
    assert st.supported is True
    assert st.platform == "win32"
    assert st.ac_sleep_timeout_seconds is not None
    assert st.ac_sleep_timeout_seconds >= 0
    assert st.dc_sleep_timeout_seconds is not None
    assert st.dc_sleep_timeout_seconds >= 0
