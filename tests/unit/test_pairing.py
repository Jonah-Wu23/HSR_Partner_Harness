from __future__ import annotations

import json
import time

import pytest

from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.pairing import (
    TOKEN_IDLE_TTL_SECONDS,
    PairingError,
    PairingService,
    token_key,
)
from pair_harness.storage.sqlite_store import SQLiteStore
from tests.service_helpers import call, expect_service_error


class _FakeClock:
    """可手动推进的时钟，经构造参数注入 PairingService。"""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _paired(svc: PairingService, device_name: str = "phone") -> str:
    return svc.claim(svc.issue_code(), device_name=device_name)


# ============================================================
# 配对码
# ============================================================


class TestClaim:
    def test_issue_code_returns_6_digits(self) -> None:
        code = PairingService().issue_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_code_is_single_use(self) -> None:
        svc = PairingService()
        code = svc.issue_code()
        svc.claim(code, device_name="phone-a")
        with pytest.raises(PairingError) as exc:
            svc.claim(code, device_name="phone-b")
        assert exc.value.code == "invalid_code"

    @pytest.mark.parametrize(
        ("ttl_seconds", "elapsed", "error_code"),
        [
            (300, 300.0, None),
            (300, 301.0, "expired_code"),
            (10, 11.0, "expired_code"),
        ],
    )
    def test_code_ttl_boundary(
        self, ttl_seconds: int, elapsed: float, error_code: str | None
    ) -> None:
        clock = _FakeClock()
        svc = PairingService(ttl_seconds=ttl_seconds, clock=clock)
        code = svc.issue_code()
        clock.advance(elapsed)
        if error_code is None:
            assert svc.claim(code, device_name="phone")
            return
        with pytest.raises(PairingError) as exc:
            svc.claim(code, device_name="phone")
        assert exc.value.code == error_code


# ============================================================
# token 鉴权
# ============================================================


class TestAuthorize:
    def test_valid_token_allowed_with_device_identity(self) -> None:
        svc = PairingService()
        token = _paired(svc, "my-phone")
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is True
        assert decision.device_name == "my-phone"
        assert decision.device_key == token_key(token)

    @pytest.mark.parametrize(
        ("token", "reason"),
        [
            (None, "missing_token"),
            ("", "invalid_token"),
            ("forged-token", "invalid_token"),
        ],
    )
    def test_business_method_rejects_unknown_token(
        self, token: str | None, reason: str
    ) -> None:
        decision = PairingService().authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == reason

    def test_remote_pair_allowed_without_token(self) -> None:
        decision = PairingService().authorize(None, "remote.pair")
        assert decision.allowed is True
        assert decision.device_name == ""
        assert decision.device_key is None

    def test_remote_pair_with_valid_token_reports_device(self) -> None:
        svc = PairingService()
        token = _paired(svc, "my-phone")
        decision = svc.authorize(token, "remote.pair")
        assert decision.allowed is True
        assert decision.device_name == "my-phone"

    @pytest.mark.parametrize(
        "method",
        [
            "remote.issue_code",
            "remote.list_devices",
            "remote.revoke",
            "remote.tunnel_start",
            "remote.tunnel_stop",
            "remote.tunnel_status",
        ],
    )
    def test_control_plane_method_rejected_with_forbidden_scope(self, method: str) -> None:
        svc = PairingService()
        decision = svc.authorize(_paired(svc), method)
        assert decision.allowed is False
        assert decision.reason == "forbidden_scope"


# ============================================================
# 撤销
# ============================================================


class TestRevoke:
    def test_revoke_device_returns_token_keys(self) -> None:
        svc = PairingService()
        token = _paired(svc)
        assert svc.revoke_device("phone") == [token_key(token)]

    def test_authorize_after_revoke_rejected(self) -> None:
        svc = PairingService()
        token = _paired(svc)
        svc.revoke_device("phone")
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "revoked_token"

    def test_revoke_notifies_listeners_with_token_key_and_device(self) -> None:
        svc = PairingService()
        token = _paired(svc)
        notified: list[tuple[str, str]] = []
        svc.add_revoke_listener(lambda t, d: notified.append((t, d)))
        svc.revoke_device("phone")
        assert notified == [(token_key(token), "phone")]

    def test_revoke_without_live_token_returns_empty_and_skips_listeners(self) -> None:
        svc = PairingService()
        notified: list[tuple[str, str]] = []
        svc.add_revoke_listener(lambda t, d: notified.append((t, d)))
        assert svc.revoke_device("nonexistent") == []
        _paired(svc)
        svc.revoke_device("phone")
        assert svc.revoke_device("phone") == []
        assert len(notified) == 1


# ============================================================
# 设备列表
# ============================================================


class TestListDevices:
    def test_devices_sorted_by_issued_at_without_token(self) -> None:
        clock = _FakeClock()
        svc = PairingService(clock=clock)
        _paired(svc, "phone-a")
        clock.advance(1.0)
        _paired(svc, "phone-b")
        svc.revoke_device("phone-a")
        devices = svc.list_devices()
        assert [d["device_name"] for d in devices] == ["phone-a", "phone-b"]
        assert [d["revoked"] for d in devices] == [True, False]
        assert set(devices[0]) == {
            "device_name",
            "issued_at",
            "last_used_at",
            "expires_at",
            "revoked",
        }


# ============================================================
# 状态快照往返
# ============================================================


class TestStateRoundtrip:
    def test_export_state_stores_only_token_hashes(self) -> None:
        svc = PairingService()
        token = _paired(svc)
        state = svc.export_state()
        assert token not in json.dumps(state)
        assert state["tokens"][0]["token_sha256"] == token_key(token)

    def test_load_state_v2_converts_plaintext_tokens(self) -> None:
        """版本 2 快照保存令牌原文：载入时转成哈希，配对码不恢复。"""
        v2_state = {
            "version": 2,
            "ttl_seconds": 300,
            "tokens": [
                {
                    "token": "legacy-token",
                    "device_name": "old-phone",
                    "issued_at": 1000.0,
                    "last_used_at": 1000.0,
                    "expires_at": 1000.0 + 7 * 86400,
                    "revoked": False,
                }
            ],
            "codes": [{"code": "123456", "issued_at": 1000.0, "ttl_seconds": 300, "claimed": False}],
            "rate_limits": {},
            "revoked_hashes": [],
            "audit": [],
        }
        svc = PairingService(clock=lambda: 2000.0)
        svc.load_state(v2_state)
        assert svc.authorize("legacy-token", "conversation.message").allowed is True
        state = svc.export_state()
        assert state["version"] == 3
        assert "legacy-token" not in json.dumps(state)
        assert state["code"] is None

    def test_roundtrip_keeps_revoked_and_valid_tokens(self) -> None:
        svc = PairingService()
        token_a = _paired(svc, "phone-a")
        token_b = _paired(svc, "phone-b")
        svc.revoke_device("phone-a")

        svc2 = PairingService()
        svc2.load_state(svc.export_state())

        assert len(svc2.list_devices()) == 2
        assert svc2.authorize(token_a, "app.bootstrap").reason == "revoked_token"
        assert svc2.authorize(token_b, "app.bootstrap").allowed is True

    def test_roundtrip_keeps_code_failure_budget(self) -> None:
        clock = _FakeClock()
        svc = PairingService(clock=clock)
        valid_code = svc.issue_code()
        for _ in range(4):
            with pytest.raises(PairingError):
                svc.claim("bad")
        state = svc.export_state()
        assert state["version"] == 3
        assert state["code"]["failures"] == 4

        svc2 = PairingService(clock=clock)
        svc2.load_state(state)
        with pytest.raises(PairingError) as exc:
            svc2.claim("bad")
        assert exc.value.code == "code_exhausted"
        with pytest.raises(PairingError) as exc:
            svc2.claim(valid_code)
        assert exc.value.code == "invalid_code"

    def test_load_state_rejects_unreleased_versions(self) -> None:
        with pytest.raises(ValueError):
            PairingService().load_state({"version": 1, "tokens": []})


# ============================================================
# 单码有效与错误次数预算
# ============================================================


class TestCodeFailureBudget:
    def test_new_code_replaces_previous(self) -> None:
        svc = PairingService()
        code1 = svc.issue_code()
        code2 = svc.issue_code()
        with pytest.raises(PairingError) as exc:
            svc.claim(code1, device_name="phone-1")
        assert exc.value.code == "invalid_code"
        assert svc.claim(code2, device_name="phone-2")

    def test_code_exhausted_after_5_failures(self) -> None:
        """当前配对码累计 5 次错误即作废，之后正确码也无法配对。"""
        svc = PairingService()
        valid_code = svc.issue_code()
        wrong_code = "000000" if valid_code != "000000" else "111111"

        for _ in range(4):
            with pytest.raises(PairingError) as exc:
                svc.claim(wrong_code, device_name="bad-actor")
            assert exc.value.code == "invalid_code"

        with pytest.raises(PairingError) as exc:
            svc.claim(wrong_code, device_name="bad-actor")
        assert exc.value.code == "code_exhausted"

        with pytest.raises(PairingError) as exc:
            svc.claim(valid_code, device_name="phone")
        assert exc.value.code == "invalid_code"

    def test_new_code_has_fresh_failure_budget(self) -> None:
        svc = PairingService()
        svc.issue_code()
        for _ in range(5):
            with pytest.raises(PairingError):
                svc.claim("wrong", device_name="bad")

        valid_code = svc.issue_code()
        for _ in range(4):
            with pytest.raises(PairingError):
                svc.claim("wrong", device_name="bad")
        assert svc.claim(valid_code, device_name="good")

    def test_non_ascii_code_counts_as_failure(self) -> None:
        svc = PairingService()
        svc.issue_code()
        with pytest.raises(PairingError) as exc:
            svc.claim("一二三四五六", device_name="bad")
        assert exc.value.code == "invalid_code"
        assert svc.export_state()["code"]["failures"] == 1


# ============================================================
# 令牌生命周期
# ============================================================


class TestTokenLifecycle:
    def test_idle_token_expires_after_7_days(self) -> None:
        clock = _FakeClock()
        svc = PairingService(clock=clock)
        token = _paired(svc)
        clock.advance(7 * 86400 + 1)
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "expired_token"

    def test_authorize_refreshes_idle_timeout_up_to_30_days(self) -> None:
        """每次成功鉴权延长 7 天空闲期，但不超过 30 天绝对有效期。"""
        clock = _FakeClock()
        svc = PairingService(clock=clock)
        token = _paired(svc)

        clock.advance(6 * 86400)
        assert svc.authorize(token, "conversation.message").allowed is True
        # 第 12 天：上次鉴权已把空闲期延到第 13 天
        clock.advance(6 * 86400)
        assert svc.authorize(token, "conversation.message").allowed is True
        # 第 32 天：超过 30 天绝对有效期
        clock.advance(20 * 86400)
        decision = svc.authorize(token, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "expired_token"


# ============================================================
# 持久化钩子
# ============================================================


class TestPersistHook:
    def test_issue_code_persists(self) -> None:
        svc = PairingService()
        writes: list[int] = []
        svc.state_persist_hook = lambda: writes.append(1)
        svc.issue_code()
        assert writes == [1]

    def test_claim_without_active_code_does_not_persist(self) -> None:
        svc = PairingService()
        writes: list[int] = []
        svc.state_persist_hook = lambda: writes.append(1)
        for _ in range(10):
            with pytest.raises(PairingError):
                svc.claim("000000", device_name="bad")
        assert writes == []

    @pytest.mark.parametrize(
        ("method", "elapsed", "reason"),
        [
            ("remote.issue_code", 0.0, "forbidden_scope"),
            ("app.bootstrap", 31 * 86400.0, "expired_token"),
        ],
    )
    def test_authorize_denial_does_not_persist(
        self, method: str, elapsed: float, reason: str
    ) -> None:
        clock = _FakeClock()
        svc = PairingService(clock=clock)
        token = _paired(svc)
        persisted: list[int] = []
        svc.state_persist_hook = lambda: persisted.append(1)
        clock.advance(elapsed)
        decision = svc.authorize(token, method)
        assert decision.allowed is False
        assert decision.reason == reason
        assert persisted == []

    @pytest.mark.parametrize("method", ["remote.pair", "app.bootstrap"])
    def test_authorize_refresh_persists_throttled(self, method: str) -> None:
        """令牌空闲刷新按节流周期写回，不逐帧整表落库。"""
        clock = _FakeClock()
        svc = PairingService(clock=clock)
        token = _paired(svc)
        calls: list[int] = []
        svc.state_persist_hook = lambda: calls.append(1)

        svc.authorize(token, method)
        assert len(calls) == 1
        clock.advance(60)
        svc.authorize(token, method)
        assert len(calls) == 1
        clock.advance(241)
        svc.authorize(token, method)
        assert len(calls) == 2


# ============================================================
# 应用服务的配对命令与状态恢复
# ============================================================


async def test_remote_pairing_commands(service) -> None:
    issued = await call(service, "issue", "remote.issue_code")
    assert issued["ttl_seconds"] == 300
    paired = await call(
        service, "pair", "remote.pair", code=issued["code"], device_name="我的手机"
    )
    assert service.event_log.payloads("remote.paired") == [{"device_name": "我的手机"}]
    await expect_service_error(
        lambda: call(
            service, "again", "remote.pair", code=issued["code"], device_name="第二台"
        ),
        "pairing_invalid_code",
    )

    devices = await call(service, "list", "remote.list_devices")
    assert [d["device_name"] for d in devices["devices"]] == ["我的手机"]

    revoked = await call(service, "revoke", "remote.revoke", device_name="我的手机")
    assert revoked == {"device_name": "我的手机", "revoked_tokens": 1}
    assert service.pairing_service.authorize(paired["token"], "app.bootstrap").reason == (
        "revoked_token"
    )
    await expect_service_error(
        lambda: call(service, "revoke-2", "remote.revoke", device_name="我的手机"),
        "device_not_found",
    )


async def test_paired_device_survives_service_restart(service) -> None:
    issued = await call(service, "issue", "remote.issue_code")
    paired = await call(
        service, "pair", "remote.pair", code=issued["code"], device_name="手机A"
    )
    await service.shutdown()

    restarted = build_demo_service(
        database=service.store.database, project_root=service.tmp_path
    )
    try:
        assert restarted.pairing_service.authorize(paired["token"], "app.bootstrap").allowed
    finally:
        await restarted.shutdown()


async def test_service_upgrades_v2_pairing_state_on_startup(tmp_path) -> None:
    """启动时载入 v0.4.x 的版本 2 配对状态，原令牌继续可用，库中立即改存哈希。"""
    database = tmp_path / "data" / "pair_harness.db"
    token = "v2-app-test-token-abcdef1234567890"
    now = time.time()
    store = SQLiteStore(database)
    store.set_app_state(
        "remote.pairing_state",
        json.dumps(
            {
                "version": 2,
                "ttl_seconds": 300,
                "tokens": [
                    {
                        "token": token,
                        "device_name": "Honor-Magic-6",
                        "issued_at": now,
                        "last_used_at": now,
                        "expires_at": now + TOKEN_IDLE_TTL_SECONDS,
                        "revoked": False,
                    }
                ],
                "codes": [],
                "rate_limits": {},
                "revoked_hashes": [],
                "audit": [],
            }
        ),
    )
    store.close()

    service = build_demo_service(database=database, project_root=tmp_path)
    try:
        decision = service.pairing_service.authorize(token, "app.bootstrap")
        assert decision.allowed is True
        assert decision.device_name == "Honor-Magic-6"
        persisted = service.store.get_app_state("remote.pairing_state")
        assert json.loads(persisted)["version"] == 3
        assert token not in persisted
    finally:
        await service.shutdown()
