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


class PairingError(RuntimeError):
    """配对码操作错误。

    code 取值：
    - "expired"：配对码已过期
    - "used"：配对码已被使用
    - "invalid"：配对码不存在或格式错误
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class DeviceInfo(TypedDict):
    """已签发 token 的设备元数据（不含 token 明文）。"""
    device_name: str
    issued_at: str
    last_used_at: str
    revoked: bool


class _CodeEntry:
    """内部配对码条目。"""

    __slots__ = ("issued_at", "ttl_seconds", "claimed")

    def __init__(self, issued_at: float, ttl_seconds: int) -> None:
        self.issued_at = issued_at
        self.ttl_seconds = ttl_seconds
        self.claimed = False


class _TokenEntry:
    """内部 token 条目。"""

    __slots__ = ("token", "device_name", "issued_at", "last_used_at", "revoked")

    def __init__(self, token: str, device_name: str, issued_at: float) -> None:
        self.token = token
        self.device_name = device_name
        self.issued_at = issued_at
        self.last_used_at = issued_at
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
        # 已撤销 token 集合（恒定时间比较用原文，但禁止已撤销 token 再次验证）
        self._revoked_hashes: set[str] = set()
        # 审计日志
        self._audit: list[dict] = []

    # ── 审计 ────────────────────────────────────────────────

    def _audit_log(self, event: str, detail: str) -> None:
        """记录一条审计条目。"""
        now = datetime.datetime.fromtimestamp(
            self._clock(), tz=datetime.timezone.utc
        ).isoformat()
        self._audit.append({
            "at": now,
            "event": event,
            "detail": detail,
        })

    def audit_entries(self) -> list[dict]:
        """返回所有审计条目。

        条目格式：{"at": iso时间, "event": "connect|auth_failed|command", "detail": ...}
        不含消息正文与密钥。
        """
        return list(self._audit)

    # ── 配对码 ──────────────────────────────────────────────

    def issue_code(self) -> str:
        """生成一个 6 位数字配对码（000000–999999 均匀分布）。

        一次性，TTL 默认 300 秒。
        """
        now = self._clock()
        # 清理过期配对码
        self._evict_expired_codes(now)
        # secrets.randbelow 保证均匀分布，禁止 random
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._codes[code] = _CodeEntry(issued_at=now, ttl_seconds=self._ttl_seconds)
        return code

    def _evict_expired_codes(self, now: float) -> None:
        """移除所有已过期的配对码。"""
        expired_keys = [
            code
            for code, entry in self._codes.items()
            if now - entry.issued_at > entry.ttl_seconds
        ]
        for code in expired_keys:
            del self._codes[code]

    def claim(self, code: str, *, device_name: str) -> str:
        """使用配对码换取 token。

        Parameters
        ----------
        code : str
            配对码。
        device_name : str
            设备名称。

        Returns
        -------
        str
            secrets.token_urlsafe(32) 生成的 token，并立刻作废该码。

        Raises
        ------
        PairingError
            code="expired"：配对码已过期
            code="used"：配对码已被使用
            code="invalid"：配对码不存在
        """
        now = self._clock()

        entry = self._codes.get(code)
        if entry is None:
            raise PairingError("配对码无效", code="invalid")

        if now - entry.issued_at > entry.ttl_seconds:
            del self._codes[code]
            raise PairingError("配对码已过期", code="expired")

        if entry.claimed:
            raise PairingError("配对码已被使用", code="used")

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

    def authorize(self, token: str | None, method: str) -> AuthDecision:
        """鉴权单条请求。

        token 有效且未撤销 → allowed=True；
        method 在 ``UNAUTHENTICATED_METHODS`` 白名单内 → 无 token 也放行；
        其余拒绝路径记审计条目。

        Parameters
        ----------
        token : str | None
            请求携带的 token 原文或 None。
        method : str
            请求方法名。

        Returns
        -------
        AuthDecision
        """
        # 白名单方法：无 token 也放行
        if method in UNAUTHENTICATED_METHODS:
            # 如果提供了 token 且有效，仍正常鉴权并记录
            if token is not None and self._lookup_token(token) is not None:
                entry = self._tokens[token]
                entry.last_used_at = self._clock()
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

        # 有效
        entry.last_used_at = self._clock()
        return AuthDecision(
            allowed=True,
            reason="",
            device_name=entry.device_name,
        )

    def _lookup_token(self, token: str) -> _TokenEntry | None:
        """恒定时间查找 token（hmac.compare_digest 比较）。"""
        for stored_token, entry in self._tokens.items():
            if hmac.compare_digest(stored_token, token):
                return entry
        return None

    # ── token 撤销 ──────────────────────────────────────────

    def revoke(self, token: str) -> bool:
        """撤销指定 token。

        撤销后 ``authorize`` 立即拒绝。
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
        return True

    # ── 设备列表 ────────────────────────────────────────────

    def list_devices(self) -> list[DeviceInfo]:
        """返回所有已签发 token 的设备元数据。

        不含 token 明文。
        """
        now = self._clock()
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
                revoked=entry.revoked,
            ))
        # 按签发时间排序
        devices.sort(key=lambda d: d["issued_at"])
        return devices

    # ── 状态快照 ────────────────────────────────────────────

    def export_state(self) -> dict:
        """导出可 JSON 序列化的状态快照。

        包含有效 token、设备元数据、撤销集合。
        不含任何 API Key（本模块根本不接触 API Key）。

        往返后 ``authorize`` 行为一致。
        """
        now = self._clock()
        tokens = []
        for entry in self._tokens.values():
            tokens.append({
                "token": entry.token,
                "device_name": entry.device_name,
                "issued_at": entry.issued_at,
                "last_used_at": entry.last_used_at,
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
        return {
            "version": 1,
            "ttl_seconds": self._ttl_seconds,
            "tokens": tokens,
            "codes": codes,
            "revoked_hashes": list(self._revoked_hashes),
            "audit": list(self._audit),
        }

    def load_state(self, state: dict) -> None:
        """从状态快照恢复。

        替换当前全部状态。恢复后 ``authorize`` 行为与导出前一致。
        """
        self._ttl_seconds = state.get("ttl_seconds", self._ttl_seconds)
        self._tokens.clear()
        for t in state.get("tokens", []):
            entry = _TokenEntry(
                token=t["token"],
                device_name=t["device_name"],
                issued_at=t["issued_at"],
            )
            entry.last_used_at = t["last_used_at"]
            entry.revoked = t["revoked"]
            self._tokens[entry.token] = entry
        self._codes.clear()
        for c in state.get("codes", []):
            entry = _CodeEntry(
                issued_at=c["issued_at"],
                ttl_seconds=c["ttl_seconds"],
            )
            entry.claimed = c["claimed"]
            self._codes[c["code"]] = entry
        self._revoked_hashes = set(state.get("revoked_hashes", []))
        self._audit = list(state.get("audit", []))