# 电源状态只读探测：经 powrprof 读取活动电源方案名称与 AC/DC 睡眠超时，永不修改电源设置。
# power.get_status 的结果与 power.status_changed 的载荷同形。

from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime

# AC/DC 睡眠超时低于该秒数（0 表示从不睡眠）且远程服务开启时判为有风险。
SLEEP_RISK_THRESHOLD_SECONDS = 900

# 睡眠子组 SUB_SLEEP 下的「在此时间后睡眠」设置 STANDBYIDLE。
_SUB_SLEEP = uuid.UUID("238c9fa8-0aad-41ed-83f4-97be242c8f20")
_STANDBY_IDLE = uuid.UUID("29f6c1db-86da-48c5-9fdb-f2b67b1f44da")


class PowerStatusError(RuntimeError):
    """powrprof 读取失败；消息携带调用名、Win32 错误码与系统错误文本。"""


@dataclass(frozen=True)
class PowerStatus:
    supported: bool
    platform: str
    plan_name: str
    ac_sleep_timeout_seconds: int | None
    dc_sleep_timeout_seconds: int | None
    remote_serve_enabled: bool
    threshold_seconds: int
    at_risk: bool
    reason: str
    checked_at: str  # ISO8601 本地时间
    warnings: list[str] = field(default_factory=list)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(value: uuid.UUID) -> _GUID:
    return _GUID.from_buffer_copy(value.bytes_le)


def _check(call: str, code: int) -> None:
    if code != 0:
        raise PowerStatusError(
            f"{call} 失败（错误码 {code}）：{ctypes.FormatError(code)}"
        )


def _read_sleep_settings() -> tuple[str, int, int]:
    """返回活动电源方案的名称与 AC/DC 睡眠超时（秒）。"""
    powrprof = ctypes.windll.powrprof
    scheme = ctypes.POINTER(_GUID)()
    _check(
        "PowerGetActiveScheme",
        powrprof.PowerGetActiveScheme(None, ctypes.byref(scheme)),
    )
    try:
        size = wintypes.DWORD(0)
        _check(
            "PowerReadFriendlyName",
            powrprof.PowerReadFriendlyName(
                None, scheme, None, None, None, ctypes.byref(size)
            ),
        )
        name = ctypes.create_string_buffer(size.value)
        _check(
            "PowerReadFriendlyName",
            powrprof.PowerReadFriendlyName(
                None, scheme, None, None, name, ctypes.byref(size)
            ),
        )
        sub_sleep = _guid(_SUB_SLEEP)
        standby_idle = _guid(_STANDBY_IDLE)
        ac = wintypes.DWORD()
        dc = wintypes.DWORD()
        _check(
            "PowerReadACValueIndex",
            powrprof.PowerReadACValueIndex(
                None,
                scheme,
                ctypes.byref(sub_sleep),
                ctypes.byref(standby_idle),
                ctypes.byref(ac),
            ),
        )
        _check(
            "PowerReadDCValueIndex",
            powrprof.PowerReadDCValueIndex(
                None,
                scheme,
                ctypes.byref(sub_sleep),
                ctypes.byref(standby_idle),
                ctypes.byref(dc),
            ),
        )
    finally:
        # PowerGetActiveScheme 用 LocalAlloc 分配 GUID，由调用方释放。
        ctypes.windll.kernel32.LocalFree(scheme)
    return ctypes.wstring_at(name), ac.value, dc.value


def _build_reason(*, ac: int, dc: int, remote_serve_enabled: bool) -> str:
    # 远程服务未开启时不会有风险，理由一律报「远程服务未开启」。
    if not remote_serve_enabled:
        return "远程服务未开启"
    threshold = SLEEP_RISK_THRESHOLD_SECONDS
    hits = []
    for label, t in (("AC", ac), ("DC", dc)):
        if t != 0 and t < threshold:
            hits.append(f"{label} 睡眠超时 {t} 秒低于阈值 {threshold} 秒")
    if hits:
        return "、".join(hits)
    return "AC/DC 睡眠超时均不低于阈值"


def read_power_status(*, remote_serve_enabled: bool) -> PowerStatus:
    """读取电源状态。非 Windows 返回 supported=False 的形状；读取失败抛 PowerStatusError。"""
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    threshold = SLEEP_RISK_THRESHOLD_SECONDS

    if sys.platform != "win32":
        return PowerStatus(
            supported=False,
            platform=sys.platform,
            plan_name="",
            ac_sleep_timeout_seconds=None,
            dc_sleep_timeout_seconds=None,
            remote_serve_enabled=remote_serve_enabled,
            threshold_seconds=threshold,
            at_risk=False,
            reason="当前平台不支持电源状态检测",
            checked_at=checked_at,
        )

    plan_name, ac, dc = _read_sleep_settings()
    at_risk = remote_serve_enabled and any(t != 0 and t < threshold for t in (ac, dc))
    return PowerStatus(
        supported=True,
        platform=sys.platform,
        plan_name=plan_name,
        ac_sleep_timeout_seconds=ac,
        dc_sleep_timeout_seconds=dc,
        remote_serve_enabled=remote_serve_enabled,
        threshold_seconds=threshold,
        at_risk=at_risk,
        reason=_build_reason(ac=ac, dc=dc, remote_serve_enabled=remote_serve_enabled),
        checked_at=checked_at,
    )
