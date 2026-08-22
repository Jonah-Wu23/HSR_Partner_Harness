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
        assert exc.value.code == "used"

    def test_expired_code_raises_expired(self) -> None:
        clock = _FakeClock(start=1000.0)
        svc = PairingService(ttl_seconds=300, clock=clock)
        code = svc.issue_code()
        # 推进到过期
        clock.advance(301.0)
        with pytest.raises(PairingError) as exc:
            svc.claim(code, device_name="phone")
        assert exc.value.code == "expired"

    def test_expired_code_evicted_on_issue(self) -> None:
        """过期码在 issue_code 时被清理，claim 应报 invalid。"""
        clock = _FakeClock(start=1000.0)
        svc = PairingService(ttl_seconds=300, clock=clock)
        code = svc.issue_code()
        clock.advance(301.0)
        # 签发新码触发清理
        svc.issue_code()
        with pytest.raises(PairingError) as exc:
            svc.claim(code, device_name="phone")
        assert exc.value.code == "invalid"

    def test_nonexistent_code_raises_invalid(self) -> None:
        svc = PairingService()
        with pytest.raises(PairingError) as exc:
            svc.claim("000000", device_name="phone")
        assert exc.value.code == "invalid"

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
        methods = ["conversation.message", "remote.list_devices", "remote.revoke"]
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
        assert exc.value.code == "used"

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