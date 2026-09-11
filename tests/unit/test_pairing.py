"""配对与鉴权纯逻辑模块测试。

覆盖 workplan 4.3 全部场景：配对码一次性、过期、错误码、
token 撤销后立即拒绝、list_devices 元数据、export/load_state 往返、
审计无密钥字段、remote.pair 白名单放行、其余方法无 token 拒绝、
恒定时间比较。
"""

from __future__ import annotations

import json
import time

import pytest

from pair_harness.desktop_backend.pairing import (
    DeviceInfo,
    PairingError,
    PairingService,
)
from pair_harness.desktop_backend.ws_server import UNAUTHENTICATED_METHODS


class _FakeClock:
    """可手动推进的假时钟，用于测试 TTL 过期。"""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ============================================================
# 配对码
# ============================================================


class TestIssueCode:
    def test_returns_6_digit_string(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        assert isinstance(code, str)
        assert len(code) == 6
        assert code.isdigit()

    def test_codes_are_unique(self) -> None:
        """连续签发多个码不应重复（概率极低，运行多次验证）。"""
        svc = PairingService()
        codes = {svc.issue_code() for _ in range(100)}
        assert len(codes) == 100



class TestClaim:
    def test_valid_code_returns_token(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="test-phone")
        assert isinstance(token, str)
        assert len(token) > 20  # token_urlsafe(32) 约 43 字符

    def test_same_code_twice_raises_used(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        svc.claim(code, device_name="phone-a")
        with pytest.raises(PairingError) as exc:
            svc.claim(code, device_name="phone-b")
        assert exc.value.code == "invalid_code"

    def test_expired_code_raises_expired(self) -> None:
        clock = _FakeClock(start=1000.0)
        svc = PairingService(ttl_seconds=300, clock=clock)
        code = svc.issue_code()
        # 推进到过期
        clock.advance(301.0)
        with pytest.raises(PairingError) as exc:
            svc.claim(code, device_name="phone")
        assert exc.value.code == "expired_code"

    def test_expired_code_evicted_on_issue(self) -> None:
        """过期码在 issue_code 时被清理，claim 应报 invalid_code。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(ttl_seconds=300, clock=clock)
        code = svc.issue_code()
        clock.advance(301.0)
        # 签发新码触发清理
        svc.issue_code()
        with pytest.raises(PairingError) as exc:
            svc.claim(code, device_name="phone")
        assert exc.value.code == "invalid_code"

    def test_nonexistent_code_raises_invalid(self) -> None:
        svc = PairingService()
        with pytest.raises(PairingError) as exc:
            svc.claim("000000", device_name="phone")
        assert exc.value.code == "invalid_code"

    def test_claim_records_connect_audit(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        svc.claim(code, device_name="my-device")
        entries = svc.audit_entries()
        assert any(
            e["event"] == "connect" and "my-device" in e["detail"]
            for e in entries
        )

    def test_ttl_seconds_constructor_parameter(self) -> None:
        """确认 ttl_seconds 参数可调。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(ttl_seconds=10, clock=clock)
        code = svc.issue_code()
        clock.advance(9.0)
        # 未过期
        token = svc.claim(code, device_name="phone")
        assert isinstance(token, str)

    def test_ttl_boundary_not_expired(self) -> None:
        """刚好在 TTL 边界内（≤ TTL）应成功。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(ttl_seconds=300, clock=clock)
        code = svc.issue_code()
        clock.advance(300.0)
        token = svc.claim(code, device_name="phone")
        assert isinstance(token, str)


# ============================================================
# token 鉴权
# ============================================================


class TestAuthorize:
    def test_valid_token_allowed(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="my-phone")
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is True
        assert decision.device_name == "my-phone"

    def test_none_token_rejected(self) -> None:
        svc = PairingService()
        decision = svc.authorize(None, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "missing_token"

    def test_invalid_token_rejected(self) -> None:
        svc = PairingService()
        decision = svc.authorize("nonexistent-token", "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "invalid_token"

    def test_invalid_token_not_in_white_space(self) -> None:
        """空字符串也算无效 token。"""
        svc = PairingService()
        decision = svc.authorize("", "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "invalid_token"

    def test_revoked_token_rejected(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="my-phone")
        svc.revoke(token)
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "revoked_token"

    def test_unauthenticated_method_without_token_allowed(self) -> None:
        """remote.pair 无 token 应放行，device_name 为空。"""
        svc = PairingService()
        method = next(iter(UNAUTHENTICATED_METHODS))
        decision = svc.authorize(None, method)
        assert decision.allowed is True
        assert decision.device_name == ""

    def test_unauthenticated_method_with_token_allowed(self) -> None:
        """remote.pair 带有效 token 应放行并记录设备名。"""
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="my-phone")
        method = next(iter(UNAUTHENTICATED_METHODS))
        decision = svc.authorize(token, method)
        assert decision.allowed is True
        assert decision.device_name == "my-phone"

    def test_other_method_without_token_rejected(self) -> None:
        """非白名单方法无 token 被拒绝。"""
        svc = PairingService()
        methods = ["conversation.message", "conversation.history"]
        for method in methods:
            decision = svc.authorize(None, method)
            assert decision.allowed is False, f"{method} should be rejected"
            assert decision.reason == "missing_token"

    def test_authorize_updates_last_used_at(self) -> None:
        clock = _FakeClock(start=1000.0)
        svc = PairingService(clock=clock)
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        # 初始 last_used_at == issued_at
        clock.advance(10.0)
        svc.authorize(token, "conversation.message")
        info = svc.list_devices()[0]
        # last_used_at 应更新
        assert info["last_used_at"] != info["issued_at"]


# ============================================================
# 撤销
# ============================================================


class TestRevoke:
    def test_revoke_valid_token_returns_true(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        assert svc.revoke(token) is True

    def test_revoke_unknown_token_returns_false(self) -> None:
        svc = PairingService()
        assert svc.revoke("nonexistent") is False

    def test_revoke_already_revoked_returns_false(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        svc.revoke(token)
        assert svc.revoke(token) is False

    def test_authorize_after_revoke_rejected(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        svc.revoke(token)
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "revoked_token"

    def test_revoke_notifies_listeners_with_token_and_device(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        notified: list[tuple[str, str]] = []
        svc.add_revoke_listener(lambda t, d: notified.append((t, d)))
        svc.revoke(token)
        assert notified == [(token, "phone")]

    def test_revoke_skips_listeners_when_nothing_revoked(self) -> None:
        svc = PairingService()
        notified: list[tuple[str, str]] = []
        svc.add_revoke_listener(lambda t, d: notified.append((t, d)))
        assert svc.revoke("nonexistent") is False
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        svc.revoke(token)
        svc.revoke(token)  # 已撤销，二次撤销不再通知
        assert len(notified) == 1


# ============================================================
# 设备列表
# ============================================================


class TestListDevices:
    def test_empty_when_no_tokens(self) -> None:
        svc = PairingService()
        assert svc.list_devices() == []

    def test_returns_device_metadata(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        svc.claim(code, device_name="my-phone")
        devices = svc.list_devices()
        assert len(devices) == 1
        info = devices[0]
        assert info["device_name"] == "my-phone"
        assert isinstance(info["issued_at"], str)
        assert isinstance(info["last_used_at"], str)
        assert info["revoked"] is False

    def test_no_token_plaintext_in_list(self) -> None:
        """list_devices 返回 DeviceInfo，不含 token 明文。"""
        svc = PairingService()
        code = svc.issue_code()
        svc.claim(code, device_name="phone")
        devices = svc.list_devices()
        # DeviceInfo 是 TypedDict，确认没有 token 字段
        assert "token" not in devices[0].keys()
    def test_multiple_devices_sorted_by_issued_at(self) -> None:
        svc = PairingService()
        code1 = svc.issue_code()
        token1 = svc.claim(code1, device_name="phone-a")
        code2 = svc.issue_code()
        token2 = svc.claim(code2, device_name="phone-b")
        # 撤销第一个不影响列表
        svc.revoke(token1)
        devices = svc.list_devices()
        assert len(devices) == 2
        # 按签发时间排序
        assert devices[0]["device_name"] == "phone-a"
        assert devices[1]["device_name"] == "phone-b"
        # 撤销状态正确
        assert devices[0]["revoked"] is True
        assert devices[1]["revoked"] is False


# ============================================================
# 状态快照往返
# ============================================================


class TestStateRoundtrip:
    def test_export_contains_no_api_key(self) -> None:
        """export_state 不含 API Key 相关字段。"""
        svc = PairingService()
        code = svc.issue_code()
        svc.claim(code, device_name="phone")
        state = svc.export_state()
        serialized = json.dumps(state)
        assert "api_key" not in serialized.lower()
        assert "apikey" not in serialized.lower()

    def test_roundtrip_preserves_authorize_behavior(self) -> None:
        """export → load → authorize 行为一致。"""
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        # 做一次鉴权产生审计
        svc.authorize(token, "conversation.message")
        svc.revoke(token)

        state = svc.export_state()
        # 重新加载到新实例
        svc2 = PairingService()
        svc2.load_state(state)

        # 验证授权行为
        assert svc2.authorize(token, "conversation.message").allowed is False
        assert svc2.authorize(token, "conversation.message").reason == "revoked_token"

        # 验证设备列表
        devices = svc2.list_devices()
        assert len(devices) == 1
        assert devices[0]["device_name"] == "phone"
        assert devices[0]["revoked"] is True

        # 验证审计条目
        entries = svc2.audit_entries()
        assert len(entries) >= 1

    def test_roundtrip_serializable(self) -> None:
        """export_state 可 JSON 序列化。"""
        svc = PairingService()
        code = svc.issue_code()
        svc.claim(code, device_name="phone")
        state = svc.export_state()
        # 应可无异常序列化
        json.dumps(state)

    def test_roundtrip_empty_state(self) -> None:
        """空状态往返。"""
        svc = PairingService()
        state = svc.export_state()
        svc2 = PairingService()
        svc2.load_state(state)
        assert svc2.list_devices() == []
        assert svc2.audit_entries() == []

    def test_roundtrip_multiple_devices(self) -> None:
        """多设备往返。"""
        svc = PairingService()
        code1 = svc.issue_code()
        token1 = svc.claim(code1, device_name="phone-a")
        code2 = svc.issue_code()
        token2 = svc.claim(code2, device_name="phone-b")
        svc.revoke(token1)

        state = svc.export_state()
        svc2 = PairingService()
        svc2.load_state(state)

        assert len(svc2.list_devices()) == 2
        # token1 已撤销
        assert svc2.authorize(token1, "x").reason == "revoked_token"
        # token2 有效
        assert svc2.authorize(token2, "x").allowed is True


# ============================================================
# 审计
# ============================================================


class TestAudit:
    def test_audit_records_auth_failures(self) -> None:
        svc = PairingService()
        svc.authorize(None, "conversation.message")
        svc.authorize("bad-token", "conversation.message")
        entries = svc.audit_entries()
        auth_failed = [e for e in entries if e["event"] == "auth_failed"]
        assert len(auth_failed) == 2

    def test_audit_no_message_body_or_secrets(self) -> None:
        """审计条目不含消息正文与密钥（仅含方法名和原因码）。"""
        svc = PairingService()
        svc.authorize(None, "conversation.message")
        entries = svc.audit_entries()
        for entry in entries:
            detail = entry["detail"]
            # 审计详情只有方法名+原因码，不应包含长 token 或消息正文
            assert len(detail) < 200
            # 原因码中的 "token" 字眼（如 missing_token）是原因标识，不是密钥本身
            # 但不应包含实际 token 值（长随机字符串）
            assert "token_urlsafe" not in detail
            assert "missing_token" in detail or "invalid_token" in detail or "revoked_token" in detail
    def test_audit_has_iso_timestamps(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        svc.claim(code, device_name="phone")
        entries = svc.audit_entries()
        assert len(entries) >= 1
        # ISO 格式包含 T 和时区
        assert "T" in entries[0]["at"]
        assert "+" in entries[0]["at"] or "Z" in entries[0]["at"]

    def test_audit_contains_connect_and_command_events(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        svc.revoke(token)
        events = {e["event"] for e in svc.audit_entries()}
        assert "connect" in events
        assert "command" in events


# ============================================================
# 安全规则
# ============================================================


class TestSecurity:
    def test_uses_hmac_compare_digest(self) -> None:
        """验证配对模块使用 hmac.compare_digest 而非 == 比较 token。"""
        import inspect

        source = inspect.getsource(PairingService._lookup_token)
        assert "hmac.compare_digest" in source
        # 确认没有用 == 比较 token
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            # 允许 dict 索引等非比较用途的 ==
            if "==" in stripped and "token" in stripped.lower():
                # 断言不是 _lookup_token 内的 token 比较
                assert "if entry.revoked" in stripped or "if entry is None" in stripped

    def test_uses_secrets_not_random(self) -> None:
        """验证整个模块使用 secrets 而非 random。"""
        import inspect

        source = inspect.getsource(PairingService)
        assert "secrets.randbelow" in source
        assert "secrets.token_urlsafe" in source
        # 不应使用 random 模块
        assert "import random" not in source

    def test_authorize_is_real_failure(self) -> None:
        """鉴权失败是真实失败，不降级放行。"""
        svc = PairingService()
        # 各种失败路径都不应返回 allowed=True
        assert svc.authorize(None, "x").allowed is False
        assert svc.authorize("", "x").allowed is False
        assert svc.authorize("invalid", "x").allowed is False


# ============================================================
# 集成场景
# ============================================================


class TestIntegration:
    def test_full_pair_and_authorize_flow(self) -> None:
        """完整配对→鉴权→撤销→拒绝流程。"""
        svc = PairingService()

        # 1. 签发配对码
        code = svc.issue_code()
        assert len(code) == 6

        # 2. 配对成功获取 token
        token = svc.claim(code, device_name="android-phone")
        assert isinstance(token, str)

        # 3. 用 token 鉴权成功
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is True
        assert decision.device_name == "android-phone"

        # 4. 同码再次 claim 失败
        with pytest.raises(PairingError) as exc:
            svc.claim(code, device_name="another-phone")
        assert exc.value.code == "invalid_code"

        # 5. 撤销 token
        assert svc.revoke(token) is True

        # 6. 撤销后鉴权拒绝
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "revoked_token"

        # 7. 设备列表正确
        devices = svc.list_devices()
        assert len(devices) == 1
        assert devices[0]["device_name"] == "android-phone"
        assert devices[0]["revoked"] is True

        # 8. 审计记录完整
        entries = svc.audit_entries()
        assert len(entries) >= 3  # connect + command(revoke) + auth_failed

    def test_concurrent_sessions(self) -> None:
        """两个独立设备可同时配对并使用。"""
        svc = PairingService()

        code_a = svc.issue_code()
        token_a = svc.claim(code_a, device_name="phone-a")
        code_b = svc.issue_code()
        token_b = svc.claim(code_b, device_name="phone-b")

        assert svc.authorize(token_a, "x").allowed is True
        assert svc.authorize(token_b, "x").allowed is True
        assert len(svc.list_devices()) == 2

        # 撤销一个不影响另一个
        svc.revoke(token_a)
        assert svc.authorize(token_a, "x").allowed is False
        assert svc.authorize(token_b, "x").allowed is True


# ============================================================
# T2: 单码有效与配对频控
# ============================================================


class TestRateLimitingAndSingleCode:
    def test_single_code_validity_revokes_previous(self) -> None:
        """签发新码时，未过期的旧码自动作废。"""
        svc = PairingService()
        code1 = svc.issue_code()
        code2 = svc.issue_code()
        assert code1 != code2

        with pytest.raises(PairingError) as exc:
            svc.claim(code1, device_name="phone-1")
        assert exc.value.code == "invalid_code"

        token = svc.claim(code2, device_name="phone-2")
        assert isinstance(token, str)

    def test_issue_code_records_audit(self) -> None:
        """签发配对码记录 pairing_code_issued 审计日志（不含配对码明文）。"""
        svc = PairingService()
        code = svc.issue_code()
        entries = svc.audit_entries()
        issued_events = [e for e in entries if e["event"] == "pairing_code_issued"]
        assert len(issued_events) == 1
        assert code not in issued_events[0]["detail"]

    def test_rate_limit_triggered_after_5_failures(self) -> None:
        """连续 5 次配对失败后进入封锁，封锁时间 60s。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(clock=clock)
        svc.issue_code()

        for _ in range(4):
            with pytest.raises(PairingError) as exc:
                svc.claim("999999", device_name="bad-actor", connection_key="ip-1.2.3.4")
            assert exc.value.code == "invalid_code"

        # 第 5 次失败触发封锁
        with pytest.raises(PairingError) as exc:
            svc.claim("999999", device_name="bad-actor", connection_key="ip-1.2.3.4")
        assert exc.value.code == "rate_limited"
        assert exc.value.retry_after_s == 60

        entries = svc.audit_entries()
        rate_events = [e for e in entries if e["event"] == "pairing_rate_limited"]
        assert len(rate_events) == 1
        assert "ip-1.2.3.4" in rate_events[0]["detail"]

    def test_rate_limit_blocks_valid_code_during_window(self) -> None:
        """在封锁窗口内，即使使用正确配对码也报错 rate_limited。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(clock=clock)
        valid_code = svc.issue_code()

        # 触发 5 次失败
        for _ in range(5):
            with pytest.raises(PairingError):
                svc.claim("wrong", device_name="phone", connection_key="client-1")

        # 尝试使用正确配对码
        clock.advance(10.0)
        with pytest.raises(PairingError) as exc:
            svc.claim(valid_code, device_name="phone", connection_key="client-1")
        assert exc.value.code == "rate_limited"
        assert exc.value.retry_after_s == 50  # 60 - 10

    def test_rate_limit_isolated_by_connection_key(self) -> None:
        """不同 connection_key 的限流互相隔离。"""
        svc = PairingService()
        valid_code = svc.issue_code()

        for _ in range(5):
            with pytest.raises(PairingError):
                svc.claim("wrong", device_name="bad", connection_key="attacker")

        # 另一个客户端使用同一个码可以成功配对
        token = svc.claim(valid_code, device_name="good", connection_key="innocent")
        assert isinstance(token, str)

    def test_exponential_backoff_up_to_30_minutes(self) -> None:
        """封锁期满后再失败，封锁时间指数退避翻倍，上限 1800s。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(clock=clock)
        svc.issue_code()

        for _ in range(5):
            with pytest.raises(PairingError):
                svc.claim("wrong", connection_key="actor")

        # 当前封锁 60s，等待 61s
        clock.advance(61.0)
        # 再次尝试失败 -> 封锁 120s
        with pytest.raises(PairingError) as exc:
            svc.claim("wrong", connection_key="actor")
        assert exc.value.code == "rate_limited"
        assert exc.value.retry_after_s == 120

        # 等待 121s -> 封锁 240s
        clock.advance(121.0)
        with pytest.raises(PairingError) as exc:
            svc.claim("wrong", connection_key="actor")
        assert exc.value.code == "rate_limited"
        assert exc.value.retry_after_s == 240

        # 模拟多次失败直到达到 1800s 上限
        last_exc: PairingError | None = None
        for _ in range(10):
            clock.advance(2000.0)
            try:
                svc.claim("wrong", connection_key="actor")
            except PairingError as exc:
                last_exc = exc
        assert last_exc is not None
        assert last_exc.code == "rate_limited"
        assert last_exc.retry_after_s == 1800

    def test_successful_claim_resets_rate_limit(self) -> None:
        """封锁期满后成功配对，失败计数与退避重置。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(clock=clock)
        valid_code = svc.issue_code()

        for _ in range(5):
            with pytest.raises(PairingError):
                svc.claim("wrong", connection_key="actor")

        # 封锁期满后
        clock.advance(61.0)
        token = svc.claim(valid_code, connection_key="actor")
        assert isinstance(token, str)

        # 再次失败，应从第 1 次重新计数（不会立即 rate_limited）
        svc.issue_code()
        with pytest.raises(PairingError) as exc:
            svc.claim("wrong", connection_key="actor")
        assert exc.value.code == "invalid_code"


# ============================================================
# T3: 令牌生命周期与版本 2 快照
# ============================================================


class TestTokenLifecycle:
    def test_token_has_expires_at_30_days(self) -> None:
        """令牌初始 expires_at 默认为 7 天（闲置超时），上限不超过 30 天。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(clock=clock)
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")
        devices = svc.list_devices()
        assert len(devices) == 1
        assert "expires_at" in devices[0]

        # 闲置超过 7 天鉴权失败 (expired_token)
        clock.advance(7 * 86400 + 1)
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "expired_token"

    def test_authorize_refreshes_idle_timeout_up_to_30_days(self) -> None:
        """每次成功鉴权延长 7 天闲置超时，但不超过 30 天绝对生命周期。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(clock=clock)
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")

        # 在第 6 天（未过 7 天）访问，延长 7 天
        clock.advance(6 * 86400)
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is True

        # 再过 6 天（总共 12 天），如果未刷新原本会过期，但已刷新所以仍然有效
        clock.advance(6 * 86400)
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is True

        # 持续刷新直到第 31 天（超过 30 天绝对生命周期），必须过期
        clock.advance(20 * 86400)
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "expired_token"

    def test_export_state_v2_includes_expires_at_and_rate_limits(self) -> None:
        """快照为版本 2，包含 expires_at 和 rate_limits。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(clock=clock)
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")

        # 触发一次封锁
        svc.issue_code()
        for _ in range(5):
            with pytest.raises(PairingError):
                svc.claim("bad", connection_key="attacker")

        state = svc.export_state()
        assert state["version"] == 2
        assert len(state["tokens"]) == 1
        assert "expires_at" in state["tokens"][0]
        assert "rate_limits" in state
        assert "attacker" in state["rate_limits"]

        # load_state 恢复
        svc2 = PairingService(clock=clock)
        svc2.load_state(state)
        # 验证封锁恢复
        with pytest.raises(PairingError) as exc:
            svc2.claim("wrong", connection_key="attacker")
        assert exc.value.code == "rate_limited"

        # 验证 token 有效
        assert svc2.authorize(token, "conversation.message").allowed is True

    def test_load_state_v1_compatibility(self) -> None:
        """向前兼容版本 1 快照：自动推导 expires_at。"""
        v1_state = {
            "version": 1,
            "tokens": [
                {
                    "token_hash": "dummyhash",
                    "device_name": "old-phone",
                    "issued_at": 1000.0,
                    "last_used_at": 1000.0,
                    "revoked": False,
                }
            ],
            "audit": [],
        }
        svc = PairingService()
        svc.load_state(v1_state)
        devices = svc.list_devices()
        assert len(devices) == 1
        assert "expires_at" in devices[0]
        # 导出后自动升级为 version 2
        assert svc.export_state()["version"] == 2


# ============================================================
# T4: 控制面鉴权与审计
# ============================================================


class TestControlPlaneScope:
    def test_remote_origin_rejects_control_plane_methods(self) -> None:
        """来自 remote origin 的控制面方法被拒绝，返回 forbidden_scope。"""
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="phone")

        control_methods = [
            "remote.issue_code",
            "remote.list_devices",
            "remote.revoke",
            "remote.tunnel_start",
            "remote.tunnel_stop",
            "remote.tunnel_status",
        ]
        for method in control_methods:
            decision = svc.authorize(token, method, origin="remote")
            assert decision.allowed is False
            assert decision.reason == "forbidden_scope"

        entries = svc.audit_entries()
        for method in control_methods:
            matching = [
                e
                for e in entries
                if e["event"] == "scope_denied" and f"method={method}" in e["detail"]
            ]
            assert len(matching) == 1, f"{method} 的 scope_denied 审计缺失或重复"
            assert "origin=remote" in matching[0]["detail"]

    def test_desktop_origin_allows_control_plane_methods(self) -> None:
        """来自 desktop origin 的控制面方法鉴权通过。"""
        svc = PairingService()
        code = svc.issue_code()
        token = svc.claim(code, device_name="desktop-ui")

        control_methods = [
            "remote.issue_code",
            "remote.list_devices",
            "remote.revoke",
            "remote.tunnel_start",
            "remote.tunnel_stop",
            "remote.tunnel_status",
        ]
        for method in control_methods:
            decision = svc.authorize(token, method, origin="desktop")
            assert decision.allowed is True
            assert decision.device_name == "desktop"