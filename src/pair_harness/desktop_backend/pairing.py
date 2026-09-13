"""配对码与 token 鉴权纯逻辑模块。

实现 RemoteAuthenticator Protocol，处理配对码生成/验证、token 签发/鉴权/撤销，
以及设备管理与审计日志。纯逻辑，不碰网络、SQLite 与其他文件。
"""

from __future__ import annotations

import datetime
import hmac
import secrets
import time as _time
from typing import Callable, TypedDict

from .ws_server import AuthDecision, RemoteAuthenticator, UNAUTHENTICATED_METHODS

# 控制面方法列表（D6：仅允许桌面回环 / origin=desktop 访问）
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
MAX_PAIRING_FAILURES: int = 5                     # 触发封锁的连续失败次数
INITIAL_BACKOFF_SECONDS: float = 60.0             # 初始封锁 60 秒
MAX_BACKOFF_SECONDS: float = 1800.0               # 最大退避 30 分钟 (1800 秒)


class PairingError(RuntimeError):
    """配对码操作错误。

    code 取值：
    - "invalid_code"：配对码不存在或已被使用
    - "expired_code"：配对码已过期
    - "rate_limited"：来源封锁中
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retry_after_s: int | float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after_s = retry_after_s


class DeviceInfo(TypedDict):
    """已签发 token 的设备元数据（不含 token 明文）。"""
    device_name: str
    issued_at: str
    last_used_at: str
    expires_at: str
    revoked: bool


class _CodeEntry:
    """内部配对码条目。"""

    __slots__ = ("issued_at", "ttl_seconds", "claimed")

    def __init__(self, issued_at: float, ttl_seconds: int) -> None:
        self.issued_at = issued_at
        self.ttl_seconds = ttl_seconds
        self.claimed = False


class _RateLimitEntry:
    """内部来源限流条目。"""

    __slots__ = ("fail_count", "blocked_until", "backoff_seconds")

    def __init__(
        self,
        fail_count: int = 0,
        blocked_until: float = 0.0,
        backoff_seconds: float = INITIAL_BACKOFF_SECONDS,
    ) -> None:
        self.fail_count = fail_count
        self.blocked_until = blocked_until
        self.backoff_seconds = backoff_seconds


class _TokenEntry:
    """内部 token 条目。"""

    __slots__ = (
        "token",
        "device_name",
        "issued_at",
        "last_used_at",
        "expires_at",
        "revoked",
    )

    def __init__(
        self,
        token: str,
        device_name: str,
        issued_at: float,
        last_used_at: float | None = None,
        expires_at: float | None = None,
    ) -> None:
        self.token = token
        self.device_name = device_name
        self.issued_at = issued_at
        self.last_used_at = issued_at if last_used_at is None else last_used_at
        if expires_at is None:
            self.expires_at = min(
                self.issued_at + TOKEN_ABSOLUTE_TTL_SECONDS,
                self.last_used_at + TOKEN_IDLE_TTL_SECONDS,
            )
        else:
            self.expires_at = expires_at
        self.revoked = False


class PairingService:
    """配对与鉴权服务。

    实现 RemoteAuthenticator Protocol，供 WSServerMode 鉴权门调用。
    纯逻辑：不碰网络、SQLite 与其他文件。

    Parameters
    ----------
    ttl_seconds : int
        配对码有效期（秒），默认 300。
    clock : Callable[[], float] | None
        可注入时钟，默认 ``time.time``。测试用假时钟推进时间。
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock or _time.time
        # 配对码存储
        self._codes: dict[str, _CodeEntry] = {}
        # token 存储（按 token 原文索引）
        self._tokens: dict[str, _TokenEntry] = {}
        # 来源限流存储（按 source 索引）
        self._rate_limits: dict[str, _RateLimitEntry] = {}
        # 已撤销 token 集合（恒定时间比较用原文，但禁止已撤销 token 再次验证）
        self._revoked_hashes: set[str] = set()
        # 审计日志
        self._audit: list[dict] = []
        # R1-003：配对状态随写随持久化钩子。应用服务注入 _persist_pairing_state：
        # 每条审计写入当刻触发；authorize 成功的令牌空闲刷新按
        # TOKEN_REFRESH_PERSIST_INTERVAL 节流触发（写回 last_used_at/expires_at，
        # 崩溃不回退空闲期）。纯逻辑场景（独立构造、测试）保持 None，不碰存储。
        self.state_persist_hook: Callable[[], None] | None = None
        self._refresh_persisted_at: float = 0.0
        # 撤销监听器：revoke 成功后以 (token, device_name) 回调，
        # 供 WS 服务器立即断开仍持有该 token 的已建立连接（V0.3.4 缺陷 7）。
        self._revoke_listeners: list[Callable[[str, str], None]] = []

    # ── 审计 ────────────────────────────────────────────────

    def _audit_log(self, event: str, detail: str) -> None:
        """记录一条审计条目，并按注入的钩子当刻持久化。"""
        now = datetime.datetime.fromtimestamp(
            self._clock(), tz=datetime.timezone.utc
        ).isoformat()
        self._audit.append({
            "at": now,
            "event": event,
            "detail": detail,
        })
        if self.state_persist_hook is not None:
            self.state_persist_hook()

    def record_audit(self, event: str, detail: str) -> None:
        """供应用服务或外部模块写入审计日志。"""
        self._audit_log(event, detail)

    def audit_entries(self) -> list[dict]:
        """返回所有审计条目。

        条目格式：{"at": iso时间, "event": "connect|auth_failed|command|...", "detail": ...}
        不含消息正文与密钥。
        """
        return list(self._audit)

    # ── 配对码 ──────────────────────────────────────────────

    def issue_code(self) -> str:
        """生成一个 6 位数字配对码（000000–999999 均匀分布）。

        单码有效（D4）：生成新码即作废全部旧码。一次性，TTL 默认 300 秒。
        """
        now = self._clock()
        # D4：同时只有一枚有效，清空全部旧码
        self._codes.clear()
        # secrets.randbelow 保证均匀分布，禁止 random
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._codes[code] = _CodeEntry(issued_at=now, ttl_seconds=self._ttl_seconds)
        self._audit_log("pairing_code_issued", f"ttl_seconds={self._ttl_seconds}")
        return code

    def _record_failure(
        self, source: str, rate_entry: _RateLimitEntry, now: float
    ) -> None:
        """记录一次失败并按需触发指数退避封锁（D3）。"""
        rate_entry.fail_count += 1
        if rate_entry.fail_count >= MAX_PAIRING_FAILURES:
            if rate_entry.fail_count == MAX_PAIRING_FAILURES:
                rate_entry.backoff_seconds = INITIAL_BACKOFF_SECONDS
            else:
                # 继续失败退避翻倍，上限 30 分钟
                rate_entry.backoff_seconds = min(
                    rate_entry.backoff_seconds * 2.0, MAX_BACKOFF_SECONDS
                )
            rate_entry.blocked_until = now + rate_entry.backoff_seconds
            retry_after_s = int(round(rate_entry.backoff_seconds))
            self._audit_log(
                "pairing_rate_limited",
                f"source={source} retry_after_s={retry_after_s}",
            )
            raise PairingError(
                f"连续配对失败次数过多，来源已封锁，请在 {retry_after_s} 秒后重试",
                code="rate_limited",
                retry_after_s=retry_after_s,
            )

    def claim(
        self,
        code: str,
        device_name: str = "",
        *,
        source: str = "default",
        connection_key: str | None = None,
    ) -> str:
        """使用配对码换取 token。

        Parameters
        ----------
        code : str
            配对码。
        device_name : str
            设备名称。
        source : str
            来源标识（以连接为单位），默认 "default"。
        connection_key : str | None
            连接标识，若提供则作为来源标识。

        Returns
        -------
        str
            secrets.token_urlsafe(32) 生成的 token，并立刻作废该码。

        Raises
        ------
        PairingError
            code="rate_limited"：来源封锁中
            code="invalid_code"：配对码不存在或已被使用
            code="expired_code"：配对码已过期
        """
        now = self._clock()
        if connection_key is not None:
            source = connection_key
        if not device_name:
            device_name = "unknown"
        rate_entry = self._rate_limits.setdefault(source, _RateLimitEntry())

        # 1. 检查来源是否处于封锁期
        if now < rate_entry.blocked_until:
            retry_after_s = max(1, int(round(rate_entry.blocked_until - now)))
            self._audit_log(
                "pairing_rate_limited",
                f"source={source} retry_after_s={retry_after_s}",
            )
            raise PairingError(
                f"来源封锁中，请在 {retry_after_s} 秒后重试",
                code="rate_limited",
                retry_after_s=retry_after_s,
            )

        if rate_entry.blocked_until > 0.0 and now >= rate_entry.blocked_until:
            rate_entry.blocked_until = 0.0

        # 2. 检查配对码
        entry = self._codes.get(code)
        if entry is None or entry.claimed:
            self._record_failure(source, rate_entry, now)
            raise PairingError("配对码无效", code="invalid_code")

        if now - entry.issued_at > entry.ttl_seconds:
            del self._codes[code]
            self._record_failure(source, rate_entry, now)
            raise PairingError("配对码已过期", code="expired_code")

        # 成功：清除失败计数与封锁
        rate_entry.fail_count = 0
        rate_entry.blocked_until = 0.0
        rate_entry.backoff_seconds = INITIAL_BACKOFF_SECONDS

        entry.claimed = True

        token = secrets.token_urlsafe(32)
        self._tokens[token] = _TokenEntry(
            token=token,
            device_name=device_name,
            issued_at=now,
        )
        self._audit_log("connect", f"device={device_name}")
        return token

    # ── token 鉴权（RemoteAuthenticator Protocol） ──────────

    def authorize(
        self, token: str | None, method: str, *, origin: str = "remote"
    ) -> AuthDecision:
        """鉴权单条请求。

        token 有效且未撤销且未过期 → allowed=True；
        控制面方法仅限桌面回环（origin="desktop"），远程调用拒绝 forbidden_scope 并记审计；
        method 在 ``UNAUTHENTICATED_METHODS`` 白名单内 → 无 token 也放行；
        其余拒绝路径记审计条目。
        """
        now = self._clock()

        # D6: 控制面方法仅限桌面回环
        if method in CONTROL_PLANE_METHODS:
            if origin != "desktop":
                self._audit_log("scope_denied", f"method={method} origin={origin}")
                return AuthDecision(allowed=False, reason="forbidden_scope")
            return AuthDecision(allowed=True, reason="", device_name="desktop")

        # 白名单方法：无 token 也放行
        if method in UNAUTHENTICATED_METHODS:
            # 如果提供了 token 且有效，仍正常鉴权并记录
            if token is not None and self._lookup_token(token) is not None:
                entry = self._tokens[token]
                if not entry.revoked and now <= entry.expires_at:
                    self._touch_token_entry(entry, now)
                    return AuthDecision(
                        allowed=True,
                        reason="",
                        device_name=entry.device_name,
                    )
            return AuthDecision(allowed=True, reason="", device_name="")

        # 无 token
        if token is None:
            self._audit_log("auth_failed", f"method={method}: missing_token")
            return AuthDecision(allowed=False, reason="missing_token")

        # 查找 token
        entry = self._lookup_token(token)
        if entry is None:
            self._audit_log("auth_failed", f"method={method}: invalid_token")
            return AuthDecision(allowed=False, reason="invalid_token")

        # 已撤销
        if entry.revoked:
            self._audit_log("auth_failed", f"method={method}: revoked_token")
            return AuthDecision(allowed=False, reason="revoked_token")

        # 过期（D5）
        if now > entry.expires_at:
            self._audit_log("auth_failed", f"method={method}: expired_token")
            return AuthDecision(allowed=False, reason="expired_token")

        # 有效：刷新空闲计时与过期时间
        self._touch_token_entry(entry, now)
        return AuthDecision(
            allowed=True,
            reason="",
            device_name=entry.device_name,
        )

    def _touch_token_entry(self, entry: _TokenEntry, now: float) -> None:
        """刷新空闲计时与过期时间，并按节流周期写回状态。

        空闲延期不落盘时，Sidecar 崩溃会让设备在内存里已延期、库里仍按
        旧期限到期，重启即误拒仍活跃的设备；逐帧整表落盘代价又过高，
        取 TOKEN_REFRESH_PERSIST_INTERVAL 节流，崩溃丢失窗口有限。
        """
        entry.last_used_at = now
        entry.expires_at = min(
            entry.issued_at + TOKEN_ABSOLUTE_TTL_SECONDS,
            now + TOKEN_IDLE_TTL_SECONDS,
        )
        if (
            self.state_persist_hook is not None
            and now - self._refresh_persisted_at >= TOKEN_REFRESH_PERSIST_INTERVAL
        ):
            self._refresh_persisted_at = now
            self.state_persist_hook()

    def _lookup_token(self, token: str) -> _TokenEntry | None:
        """恒定时间查找 token（hmac.compare_digest 比较）。"""
        for stored_token, entry in self._tokens.items():
            if hmac.compare_digest(stored_token, token):
                return entry
        return None

    # ── token 撤销 ──────────────────────────────────────────

    def revoke(self, token: str) -> bool:
        """撤销指定 token。

        撤销后 ``authorize`` 立即拒绝，并通知所有撤销监听器（如 WS 服务器
        断开该 token 的已建立连接）。
        返回是否撤销成功（未知 token 返回 False）。
        """
        entry = self._lookup_token(token)
        if entry is None:
            return False
        if entry.revoked:
            return False
        entry.revoked = True
        self._revoked_hashes.add(token)
        self._audit_log("command", f"revoke device={entry.device_name}")
        for listener in list(self._revoke_listeners):
            listener(token, entry.device_name)
        return True

    def add_revoke_listener(self, listener: Callable[[str, str], None]) -> None:
        """注册撤销监听器；revoke 成功后以 (token, device_name) 回调。"""
        self._revoke_listeners.append(listener)

    # ── 设备列表 ────────────────────────────────────────────

    def list_devices(self) -> list[DeviceInfo]:
        """返回所有已签发 token 的设备元数据。

        不含 token 明文。
        """
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
        # 按签发时间排序
        devices.sort(key=lambda d: d["issued_at"])
        return devices

    # ── 状态快照 ────────────────────────────────────────────

    def export_state(self) -> dict:
        """导出可 JSON 序列化的状态快照（版本 2）。

        包含有效 token、设备元数据、撤销集合、来源限流状态。
        不含任何 API Key（本模块根本不接触 API Key）。

        往返后 ``authorize`` 行为一致。
        """
        tokens = []
        for entry in self._tokens.values():
            tokens.append({
                "token": entry.token,
                "device_name": entry.device_name,
                "issued_at": entry.issued_at,
                "last_used_at": entry.last_used_at,
                "expires_at": entry.expires_at,
                "revoked": entry.revoked,
            })
        codes = []
        for code, entry in self._codes.items():
            codes.append({
                "code": code,
                "issued_at": entry.issued_at,
                "ttl_seconds": entry.ttl_seconds,
                "claimed": entry.claimed,
            })
        rate_limits = {}
        for source, r in self._rate_limits.items():
            rate_limits[source] = {
                "fail_count": r.fail_count,
                "blocked_until": r.blocked_until,
                "backoff_seconds": r.backoff_seconds,
            }
        return {
            "version": 2,
            "ttl_seconds": self._ttl_seconds,
            "tokens": tokens,
            "codes": codes,
            "rate_limits": rate_limits,
            "revoked_hashes": list(self._revoked_hashes),
            "audit": list(self._audit),
        }

    def load_state(self, state: dict) -> None:
        """从状态快照恢复。

        兼容版本 1 快照：对缺 expires_at 的旧条目按 issued_at + 30 天
        与 last_used_at + 7 天补算。恢复后 ``authorize`` 行为与导出前一致。
        """
        self._ttl_seconds = state.get("ttl_seconds", self._ttl_seconds)
        self._tokens.clear()
        for t in state.get("tokens", []):
            issued_at = t["issued_at"]
            last_used_at = t.get("last_used_at", issued_at)
            if "expires_at" in t:
                expires_at = t["expires_at"]
            else:
                expires_at = min(
                    issued_at + TOKEN_ABSOLUTE_TTL_SECONDS,
                    last_used_at + TOKEN_IDLE_TTL_SECONDS,
                )
            token = t.get("token") or t.get("token_hash", "")
            entry = _TokenEntry(
                token=token,
                device_name=t.get("device_name", ""),
                issued_at=issued_at,
                last_used_at=last_used_at,
                expires_at=expires_at,
            )
            entry.revoked = t.get("revoked", False)
            self._tokens[entry.token] = entry
        self._codes.clear()
        for c in state.get("codes", []):
            entry = _CodeEntry(
                issued_at=c["issued_at"],
                ttl_seconds=c["ttl_seconds"],
            )
            entry.claimed = c.get("claimed", False)
            self._codes[c["code"]] = entry
        self._rate_limits.clear()
        for source, r in state.get("rate_limits", {}).items():
            self._rate_limits[source] = _RateLimitEntry(
                fail_count=r.get("fail_count", 0),
                blocked_until=r.get("blocked_until", 0.0),
                backoff_seconds=r.get("backoff_seconds", INITIAL_BACKOFF_SECONDS),
            )
        self._revoked_hashes = set(state.get("revoked_hashes", []))
        self._audit = list(state.get("audit", []))