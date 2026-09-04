"""电源状态读取模块（V0.3.7 `power.get_status` / `power.status_changed` 数据源）。

只做只读探测：调用 `powercfg` 读取当前活动电源方案与 AC/DC 睡眠超时，
据此做确定性 `at_risk` 判定（见 docs/plans/V0.3.7-契约冻结.md §1.5 / §8）。
本模块永不修改电源设置（不调用 `powercfg /change` 等写操作）。

失败路径遵循 Let It Fail：真实失败统一抛 `PowerStatusError`，只携带原始
stderr / 输出摘要 / 异常原文，不猜数值、不降级伪造。
"""

from __future__ import annotations

import locale
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

# 冻结阈值：AC/DC 睡眠超时低于 900 秒视为「有风险」（契约 §8）。
SLEEP_RISK_THRESHOLD_SECONDS = 900

# 36 位电源方案 GUID（契约 §8：`([0-9a-fA-F-]{36})`）。
_SCHEME_GUID_RE = re.compile(r"([0-9a-fA-F-]{36})")
# 括号内方案名称，全角「（）」与半角「()」都算。
_SCHEME_NAME_RE = re.compile(r"[（(]\s*([^（()）]*?)\s*[）)]")
# 契约冻结的 16 位十六进制索引正则（部分系统的 powercfg 输出以 16 位补零展示）。
_INDEX_16_RE = re.compile(r"0x([0-9a-fA-F]{16})")
# 本机真实 powercfg（中文 Windows）输出以 8 位十六进制展示（如 0x00000708），
# 16 位正则匹配不到；用 1-16 位宽松形态按出现次序收集，见 `_parse_ac_dc`。
_INDEX_ANY_RE = re.compile(r"0x([0-9a-fA-F]{1,16})")


class PowerStatusError(RuntimeError):
    """powercfg 读取或解析失败（命令层转 `power_status_unavailable`）。

    只携带原始 stderr / 输出摘要 / 异常原文，不猜数值、不降级伪造。
    """


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
    checked_at: str          # ISO8601 本地时间
    warnings: list[str] = field(default_factory=list)   # 非致命提示（如计划名缺失）


def _decode_bytes(data: bytes) -> str:
    """按真实编码解码 powercfg 字节输出。

    powercfg 输出使用系统 ANSI 代码页（中文 Windows 为 GBK/cp936）。运行/测试环境
    若被强制 UTF-8 模式（PYTHONUTF8=1），`subprocess` 的 text 模式会按 UTF-8 解 GBK
    而失败并静默得到空输出，因此这里手工按「首选编码 → gbk」顺序解码；取到的都是
    真实输出，不做任何猜测；全部失败则如实抛错。
    """
    if not data:
        return ""
    preferred = locale.getpreferredencoding(False)
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
        if preferred.lower().replace("-", "") != "gbk":
            candidates.append("gbk")
    for enc in candidates:
        try:
            return data.decode(enc).replace("\r\n", "\n")
        except (UnicodeDecodeError, LookupError):
            continue
    raise PowerStatusError(
        f"powercfg 输出无法解码（尝试 {candidates} 均失败）：{data[:120]!r}"
    )


def _summarize(text: str, limit: int = 200) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:limit] + ("…" if len(collapsed) > limit else "")


def _run_real(args: list[str]) -> subprocess.CompletedProcess:
    """真实调用 powercfg（只读）。timeout 10s；超时/OSError 由调用方统一转 PowerStatusError。"""
    completed = subprocess.run(args, timeout=10, capture_output=True)
    return subprocess.CompletedProcess(
        args=args,
        returncode=completed.returncode,
        stdout=_decode_bytes(completed.stdout) if completed.stdout is not None else "",
        stderr=_decode_bytes(completed.stderr) if completed.stderr is not None else "",
    )


def _capture(
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None,
    args: list[str],
    what: str,
) -> str:
    completed = runner(args) if runner is not None else _run_real(args)
    if completed.returncode != 0:
        detail = (getattr(completed, "stderr", None) or "").strip()
        if not detail:
            detail = f"stdout：{_summarize(getattr(completed, 'stdout', None) or '')}"
        raise PowerStatusError(f"{what} 退出码 {completed.returncode}：{detail}")
    stdout = getattr(completed, "stdout", None)
    if not isinstance(stdout, str):
        raise PowerStatusError(f"{what} 输出不是文本，无法解析")
    return stdout


def _parse_plan_name(scheme_out: str, warnings: list[str]) -> str:
    if not _SCHEME_GUID_RE.search(scheme_out):
        raise PowerStatusError(
            f"powercfg /getactivescheme 输出中未找到活动电源方案 GUID；"
            f"输出摘要：{_summarize(scheme_out)}"
        )
    name_match = _SCHEME_NAME_RE.search(scheme_out)
    if name_match and name_match.group(1).strip():
        return name_match.group(1).strip()
    warnings.append("powercfg /getactivescheme 输出未包含可解析的方案名称")
    return ""


def _parse_ac_dc(query_out: str, what: str) -> tuple[int, int]:
    strict = _INDEX_16_RE.findall(query_out)
    if len(strict) >= 2:
        # 契约 §8：按出现次序，第 1 个 = AC、第 2 个 = DC。
        return int(strict[0], 16), int(strict[1], 16)
    tokens = _INDEX_ANY_RE.findall(query_out)
    if len(tokens) < 2:
        raise PowerStatusError(
            f"{what} 输出中未找到 AC/DC 睡眠超时索引（需两个 0x 十六进制值）；"
            f"输出摘要：{_summarize(query_out)}"
        )
    # 真实输出为 8 位十六进制，且 min/max/增量在前、AC/DC 索引在后，
    # 取最后两个即 AC 与 DC（标签本地化不影响：只按出现次序与行内十六进制值，契约 §8）。
    return int(tokens[-2], 16), int(tokens[-1], 16)


def _build_reason(*, ac: int, dc: int, remote_serve_enabled: bool) -> str:
    # at_risk 判定本身要求 remote_serve_enabled=True；服务未开启时无论数值一律
    # 报「远程服务未开启」（优先级高于逐条命中项，见测试 at_risk 矩阵）。
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


def read_power_status(
    *,
    remote_serve_enabled: bool,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
    now: datetime | None = None,
) -> PowerStatus:
    """读取电源状态（只读，永不修改电源设置）。

    - 非 Windows（`sys.platform != "win32"`）：返回 unsupported 形状（§1.5），
      不调用 powercfg、不抛错。
    - Windows：真实调用 powercfg 两步（getactivescheme / query SUB_SLEEP STANDBYIDLE），
      失败统一抛 `PowerStatusError`（命令层转 `power_status_unavailable`）。
    - `runner` 仅用于测试与将来监视线程复用；`None` = 真实调用。
    """
    warnings: list[str] = []
    checked_at = (now or datetime.now()).astimezone().isoformat(timespec="seconds")
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
            warnings=warnings,
        )

    try:
        scheme_out = _capture(
            runner, ["powercfg", "/getactivescheme"], "powercfg /getactivescheme"
        )
        plan_name = _parse_plan_name(scheme_out, warnings)
        query_args = ["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"]
        query_out = _capture(runner, query_args, "powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE")
        ac, dc = _parse_ac_dc(query_out, "powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE")
    except PowerStatusError:
        raise
    except subprocess.TimeoutExpired as exc:
        raise PowerStatusError(f"powercfg 调用超时（>10s）：{exc}") from exc
    except OSError as exc:
        # OSError 含 FileNotFoundError（powercfg 不存在）。
        raise PowerStatusError(f"调用 powercfg 失败：{exc}") from exc

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
        warnings=warnings,
    )
