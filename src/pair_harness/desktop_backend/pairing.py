# 手机远程的配对码与设备令牌鉴权：令牌只以 SHA-256 哈希保存与查找，不碰网络和存储。

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import secrets
import time as _time
from dataclasses import dataclass
from typing import Callable, TypedDict

from .ws_server import AuthDecision, UNAUTHENTICATED_METHODS

logger = logging.getLogger(__name__)

# 只允许桌面 stdin 调用的控制面方法；WS 鉴权门对远程连接一律拒绝。
CONTROL_PLANE_METHODS: frozenset[str] = frozenset(
    {
        "remote.issue_code",
        "remote.list_devices",
        "remote.revoke",
        "remote.tunnel_start",
        "remote.tunnel_stop",
        "remote.tunnel_status",
    }
)

TOKEN_ABSOLUTE_TTL_SECONDS: float = 30 * 86400.0  # 绝对有效期 30 天
TOKEN_IDLE_TTL_SECONDS: float = 7 * 86400.0       # 空闲有效期 7 天

# 令牌空闲刷新（authorize 成功路径）的节流落盘周期：崩溃时最多丢失
# 该窗口内的空闲延期，相对 7 天空闲期可忽略，避免每帧鉴权整表写库。
TOKEN_REFRESH_PERSIST_INTERVAL = 300.0
# 单个配对码允许的错误尝试次数；用尽即作废，需在桌面端重新生成。
MAX_PAIRING_FAILURES: int = 5


class PairingError(RuntimeError):
    """配对码操作错误。

    code 取值：
    - "invalid_code"：配对码不匹配，或当前没有有效配对码
    - "expired_code"：配对码已过期
    - "code_exhausted"：当前配对码错误次数用尽，已作废
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def token_key(token: str) -> str:
    """设备令牌的存储键与设备身份：令牌原文的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expires_at(issued_at: float, last_used_at: float) -> float:
    return min(
        issued_at + TOKEN_ABSOLUTE_TTL_SECONDS,
        last_used_at + TOKEN_IDLE_TTL_SECONDS,
    )


class DeviceInfo(TypedDict):
    """已签发令牌的设备元数据。"""
    device_name: str
    issued_at: str
    last_used_at: str
    expires_at: str
    revoked: bool


class _CodeEntry:
    """当前有效的配对码及其累计错误次数。"""

    __slots__ = ("code", "issued_at", "ttl_seconds", "failures")

    def __init__(
        self, code: str, issued_at: float, ttl_seconds: int, failures: int = 0
    ) -> None:
        self.code = code
        self.issued_at = issued_at
        self.ttl_seconds = ttl_seconds
        self.failures = failures


@dataclass(slots=True)
class _TokenEntry:
    device_name: str
    issued_at: float
    last_used_at: float
    expires_at: float
    revoked: bool = False


class PairingService:
    """配对与鉴权服务，作为 WSServerMode 的鉴权门。

    ``clock`` 默认 ``time.time``，测试注入假时钟推进时间。
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock or _time.time
        # 同一时刻只有一枚有效配对码
        self._code: _CodeEntry | None = None
        # 按 token_key(令牌) 索引
        self._tokens: dict[str, _TokenEntry] = {}
        # 配对状态持久化钩子，由应用服务注入。配对码、令牌与撤销状态变化时
        # 当刻触发；令牌空闲刷新按 TOKEN_REFRESH_PERSIST_INTERVAL 节流触发。
        self.state_persist_hook: Callable[[], None] | None = None
        self._refresh_persisted_at: float = 0.0
        # 撤销监听器以 (令牌键, 设备名) 回调，WS 服务器据此断开该设备的已建立连接。
        self._revoke_listeners: list[Callable[[str, str], None]] = []

    def _persist(self) -> None:
        if self.state_persist_hook is not None:
            self.state_persist_hook()

    # ── 配对码 ──────────────────────────────────────────────

    def issue_code(self) -> str:
        """生成一个 6 位数字配对码（000000–999999 均匀分布）。

        同一时刻只有一枚有效：生成新码即作废旧码。一次性，TTL 默认 300 秒。
        """
        now = self._clock()
        # secrets.randbelow 保证均匀分布，禁止 random
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._code = _CodeEntry(code, issued_at=now, ttl_seconds=self._ttl_seconds)
        logger.info("已生成配对码 ttl_seconds=%s", self._ttl_seconds)
        self._persist()
        return code

    def claim(self, code: str, device_name: str = "") -> str:
        """使用配对码换取 token，成功后该码作废。

        错误尝试计入当前配对码，累计 ``MAX_PAIRING_FAILURES`` 次即作废，
        与请求来自哪条连接无关。

        Raises
        ------
        PairingError
            code="invalid_code"：配对码不匹配，或当前没有有效配对码
            code="expired_code"：配对码已过期
            code="code_exhausted"：本次错误用尽当前配对码的尝试次数
        """
        now = self._clock()
        entry = self._code
        if entry is None:
            raise PairingError("配对码无效", code="invalid_code")

        if now - entry.issued_at > entry.ttl_seconds:
            self._code = None
            self._persist()
            raise PairingError("配对码已过期", code="expired_code")

        if not hmac.compare_digest(code.encode("utf-8"), entry.code.encode("utf-8")):
            entry.failures += 1
            if entry.failures >= MAX_PAIRING_FAILURES:
                self._code = None
                logger.warning("配对码错误 %d 次，已作废", entry.failures)
                self._persist()
                raise PairingError(
                    "配对码错误次数过多，已作废，请在桌面端重新生成",
                    code="code_exhausted",
                )
            self._persist()
            raise PairingError("配对码无效", code="invalid_code")

        self._code = None
        if not device_name:
            device_name = "unknown"
        token = secrets.token_urlsafe(32)
        self._tokens[token_key(token)] = _TokenEntry(
            device_name=device_name,
            issued_at=now,
            last_used_at=now,
            expires_at=_expires_at(now, now),
        )
        logger.info("设备已配对 device=%r", device_name)
        self._persist()
        return token

    # ── 令牌鉴权 ────────────────────────────────────────────

    def authorize(self, token: str | None, method: str) -> AuthDecision:
        """鉴权一条远程请求。

        控制面方法一律拒绝为 forbidden_scope；``UNAUTHENTICATED_METHODS``
        无令牌也放行；其余方法要求令牌存在、未撤销、未过期。
        """
        now = self._clock()

        if method in CONTROL_PLANE_METHODS:
            return AuthDecision(allowed=False, reason="forbidden_scope")

        key = token_key(token) if token is not None else None
        entry = self._tokens.get(key) if key is not None else None

        if method in UNAUTHENTICATED_METHODS:
            if entry is not None and not entry.revoked and now <= entry.expires_at:
                self._touch_token_entry(entry, now)
                return AuthDecision(
                    allowed=True, device_name=entry.device_name, device_key=key
                )
            return AuthDecision(allowed=True)

        if key is None:
            reason = "missing_token"
        elif entry is None:
            reason = "invalid_token"
        elif entry.revoked:
            reason = "revoked_token"
        elif now > entry.expires_at:
            reason = "expired_token"
        else:
            self._touch_token_entry(entry, now)
            return AuthDecision(
                allowed=True, device_name=entry.device_name, device_key=key
            )
        return AuthDecision(allowed=False, reason=reason)

    def _touch_token_entry(self, entry: _TokenEntry, now: float) -> None:
        """刷新空闲计时与过期时间，并按节流周期落盘。

        空闲延期需要落盘：只留在内存时，Sidecar 崩溃重启后会按旧期限误拒
        仍活跃的设备。逐帧落盘代价过高，因此按 TOKEN_REFRESH_PERSIST_INTERVAL 节流。
        """
        entry.last_used_at = now
        entry.expires_at = _expires_at(entry.issued_at, now)
        if (
            self.state_persist_hook is not None
            and now - self._refresh_persisted_at >= TOKEN_REFRESH_PERSIST_INTERVAL
        ):
            self._refresh_persisted_at = now
            self.state_persist_hook()

    # ── 撤销 ────────────────────────────────────────────────

    def revoke_device(self, device_name: str) -> list[str]:
        """撤销该设备名下全部未撤销的令牌，返回被撤销令牌的键。

        撤销后 ``authorize`` 立即拒绝，并逐个通知撤销监听器。
        """
        revoked = [
            key
            for key, entry in self._tokens.items()
            if entry.device_name == device_name and not entry.revoked
        ]
        if not revoked:
            return revoked
        for key in revoked:
            self._tokens[key].revoked = True
        logger.info("已撤销设备 device=%r tokens=%d", device_name, len(revoked))
        self._persist()
        for key in revoked:
            for listener in list(self._revoke_listeners):
                listener(key, device_name)
        return revoked

    def add_revoke_listener(self, listener: Callable[[str, str], None]) -> None:
        self._revoke_listeners.append(listener)

    # ── 设备列表 ────────────────────────────────────────────

    def list_devices(self) -> list[DeviceInfo]:
        """返回所有已签发令牌的设备元数据，按签发时间排序。"""
        devices: list[DeviceInfo] = []
        for entry in self._tokens.values():
            devices.append(DeviceInfo(
                device_name=entry.device_name,
                issued_at=datetime.datetime.fromtimestamp(
                    entry.issued_at, tz=datetime.timezone.utc
                ).isoformat(),
                last_used_at=datetime.datetime.fromtimestamp(
                    entry.last_used_at, tz=datetime.timezone.utc
                ).isoformat(),
                expires_at=datetime.datetime.fromtimestamp(
                    entry.expires_at, tz=datetime.timezone.utc
                ).isoformat(),
                revoked=entry.revoked,
            ))
        devices.sort(key=lambda d: d["issued_at"])
        return devices

    # ── 状态快照 ────────────────────────────────────────────

    def export_state(self) -> dict:
        """导出可 JSON 序列化的状态快照（版本 3）。

        包含令牌哈希、设备元数据，以及当前配对码和它的累计错误次数；
        不含令牌原文。往返后 ``authorize`` 与 ``claim`` 行为一致。
        """
        tokens = []
        for key, entry in self._tokens.items():
            tokens.append({
                "token_sha256": key,
                "device_name": entry.device_name,
                "issued_at": entry.issued_at,
                "last_used_at": entry.last_used_at,
                "expires_at": entry.expires_at,
                "revoked": entry.revoked,
            })
        code = None
        if self._code is not None:
            code = {
                "code": self._code.code,
                "issued_at": self._code.issued_at,
                "ttl_seconds": self._code.ttl_seconds,
                "failures": self._code.failures,
            }
        return {
            "version": 3,
            "ttl_seconds": self._ttl_seconds,
            "tokens": tokens,
            "code": code,
        }

    def load_state(self, state: dict) -> None:
        """从版本 3 或版本 2（v0.4.x 发布格式）快照恢复。

        版本 2 保存令牌原文，载入时转成哈希；它的配对码不恢复，需要在桌面端重新生成。
        """
        version = state["version"]
        if version not in (2, 3):
            raise ValueError(f"不支持的配对状态版本：{version}")
        self._ttl_seconds = state["ttl_seconds"]
        self._tokens = {
            (t["token_sha256"] if version == 3 else token_key(t["token"])): _TokenEntry(
                device_name=t["device_name"],
                issued_at=t["issued_at"],
                last_used_at=t["last_used_at"],
                expires_at=t["expires_at"],
                revoked=t["revoked"],
            )
            for t in state["tokens"]
        }
        code = state["code"] if version == 3 else None
        self._code = (
            None
            if code is None
            else _CodeEntry(
                code["code"],
                issued_at=code["issued_at"],
                ttl_seconds=code["ttl_seconds"],
                failures=code["failures"],
            )
        )