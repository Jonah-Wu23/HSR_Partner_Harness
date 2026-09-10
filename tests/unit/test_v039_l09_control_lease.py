"""V0.3.9 L09：远程控制租约（契约归档正文 .archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md §6）。

覆盖：
1. 冻结阈值：TTL 45s、断连宽限 15s、最晚 60s 回收；
2. 认领按 device_key 独立记录，快照 remote_control 与 remote.control_status 同形；
3. 已鉴权持有者的 ping/claim 续租（不发事件），非持有者不续租不夺权；
4. TTL 到期自动回收并广播 remote.control_changed(expired)，桌面播放资格恢复；
5. 断连不立即释放：宽限内仍持有，超过宽限回收；
6. release/撤销只回收对应设备，不误释放其他设备。

离线夹具只证明协议与状态逻辑，不构成真机或真实网络链路证据。
"""

from __future__ import annotations

import time

import pytest

import pair_harness.desktop_backend.application_service as app_service_module
from pair_harness.desktop_backend.commands import DesktopCommand
from test_v035_wiring import call, service  # noqa: F401 - fixture 复用

TTL = app_service_module.CONTROL_LEASE_TTL_S
GRACE = app_service_module.CONTROL_LEASE_GRACE_S


def claim_command(device_key: str, *, request_id: str = "claim") -> DesktopCommand:
    return DesktopCommand(
        request_id=request_id,
        method="remote.claim_control",
        params={},
        origin="remote",
        connection_key=f"conn-{device_key}",
        remote_device_key=device_key,
    )


def release_command(device_key: str) -> DesktopCommand:
    return DesktopCommand(
        request_id="release",
        method="remote.release_control",
        params={},
        origin="remote",
        connection_key=f"conn-{device_key}",
        remote_device_key=device_key,
    )


def ping_command(device_key: str | None) -> DesktopCommand:
    return DesktopCommand(
        request_id="ping",
        method="ping",
        params={},
        origin="remote" if device_key is not None else "desktop",
        connection_key=None,
        remote_device_key=device_key,
    )


async def claim(service, device_key: str) -> dict:
    return await service.handle_command(claim_command(device_key))


async def ping(service, device_key: str | None) -> dict:
    return await service.handle_command(ping_command(device_key))


@pytest.fixture(autouse=True)
async def _cancel_sweeper(service):
    """用例结束后停掉周期回收任务，避免留下悬挂 task。"""
    yield
    task = service._control_sweeper
    if task is not None and not task.done():
        task.cancel()
        await __import__("asyncio").gather(task, return_exceptions=True)
    service._control_sweeper = None


def test_lease_thresholds_match_frozen_contract() -> None:
    """契约 §6 冻结：TTL 45s、宽限 15s、最晚 60s 回收。"""
    assert TTL == 45.0
    assert GRACE == 15.0
    assert TTL + GRACE == 60.0


@pytest.mark.asyncio
async def test_claim_records_lease_and_snapshot(service) -> None:
    assert service.bootstrap()["remote_control"] == {
        "state": "free",
        "device_key": None,
        "expires_at": None,
        "grace_expires_at": None,
        "reason": None,
    }

    result = await claim(service, "device-1")
    assert result == {"claimed": True, "active_controllers": 1}

    status = await call(service, "status", "remote.control_status")
    assert status["state"] == "held"
    assert status["device_key"] == "device-1"
    assert status["expires_at"]
    assert status["grace_expires_at"] is None  # 未断连时没有宽限截止
    assert status["reason"] == "claimed"
    assert service.bootstrap()["remote_control"] == status

    events = service.event_log.payloads("remote.control_changed")
    assert len(events) == 1
    assert events[0]["state"] == "held"
    assert events[0]["reason"] == "claimed"
    assert events[0]["device_key"] == "device-1"


@pytest.mark.asyncio
async def test_holder_ping_renews_without_event(service) -> None:
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    lease.last_refresh_at = time.monotonic() - TTL + 5  # 距到期仅剩 5s
    before = lease.expires_at

    pong = await ping(service, "device-1")
    assert pong["server_time"]
    assert lease.expires_at > before
    assert lease.reason == "renewed"
    # 续租不发事件：只有认领那一条
    assert len(service.event_log.payloads("remote.control_changed")) == 1


@pytest.mark.asyncio
async def test_non_holder_ping_does_not_renew(service) -> None:
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    lease.last_refresh_at = time.monotonic() - TTL + 5
    before = lease.expires_at

    await ping(service, "device-2")
    assert lease.expires_at == before
    assert lease.reason == "claimed"
    assert set(service._control_leases) == {"device-1"}


@pytest.mark.asyncio
async def test_repeat_claim_renews_without_event(service) -> None:
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    lease.last_refresh_at = time.monotonic() - TTL + 1
    before = lease.expires_at

    result = await claim(service, "device-1")
    assert result == {"claimed": True, "active_controllers": 1}
    assert lease.expires_at > before
    assert len(service.event_log.payloads("remote.control_changed")) == 1


@pytest.mark.asyncio
async def test_lease_expiry_reclaims_and_restores_desktop(service) -> None:
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    lease.last_refresh_at = time.monotonic() - TTL - 0.01

    assert not service.has_active_remote_controller()
    assert service._control_leases == {}
    # V039-S4-016：守卫改按调用方身份判定，桌面调用方在无租约时放行。
    service._require_playback_control(origin="desktop")

    events = service.event_log.payloads("remote.control_changed")
    assert [item["reason"] for item in events] == ["claimed", "expired"]
    assert events[-1]["state"] == "free"
    assert events[-1]["device_key"] == "device-1"
    assert service.bootstrap()["remote_control"]["state"] == "free"


@pytest.mark.asyncio
async def test_disconnect_grace_then_expiry(service) -> None:
    """断连不立即释放：宽限内保持控制，超过 TTL+宽限才回收。"""
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]

    service.handle_remote_disconnect("conn-device-1")
    assert service.has_active_remote_controller()
    assert lease.grace_expires_at is not None
    assert lease.grace_expires_at > lease.expires_at

    # 距最后一次续租 TTL+1s：超出 TTL 但在 15s 宽限内，仍持有。
    lease.last_refresh_at = time.monotonic() - TTL - 1
    assert service.has_active_remote_controller()
    assert not [item for item in service.event_log.payloads("remote.control_changed") if item["reason"] == "expired"]

    # 超过 TTL+宽限：回收并发过期事件。
    lease.last_refresh_at = time.monotonic() - TTL - GRACE - 0.01
    assert not service.has_active_remote_controller()
    expired = [
        item
        for item in service.event_log.payloads("remote.control_changed")
        if item["reason"] == "expired"
    ]
    assert len(expired) == 1
    assert expired[0]["grace_expires_at"] is not None


@pytest.mark.asyncio
async def test_reconnect_claim_clears_grace(service) -> None:
    await claim(service, "device-1")
    service.handle_remote_disconnect("conn-device-1")
    assert service._control_leases["device-1"].grace_expires_at is not None

    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    assert lease.grace_expires_at is None
    assert service.has_active_remote_controller()


@pytest.mark.asyncio
async def test_release_only_reclaims_own_device(service) -> None:
    await claim(service, "device-1")
    await claim(service, "device-2")
    assert service.has_active_remote_controller()

    result = await service.handle_command(release_command("device-1"))
    assert result == {"released": True, "active_controllers": 1}
    assert set(service._control_leases) == {"device-2"}
    assert service.has_active_remote_controller()

    released = [
        item
        for item in service.event_log.payloads("remote.control_changed")
        if item["reason"] == "released"
    ]
    assert len(released) == 1
    assert released[0]["device_key"] == "device-1"


@pytest.mark.asyncio
async def test_release_unknown_device_is_idempotent(service) -> None:
    result = await service.handle_command(release_command("device-x"))
    assert result == {"released": True, "active_controllers": 0}
    assert service.event_log.payloads("remote.control_changed") == []


@pytest.mark.asyncio
async def test_revoke_reclaims_matching_lease(service) -> None:
    import hashlib

    token = service.pairing_service.claim(
        service.pairing_service.issue_code(), device_name="phone"
    )
    device_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    await claim(service, device_key)
    assert service.has_active_remote_controller()

    await call(service, "revoke", "remote.revoke", device_name="phone")
    assert not service.has_active_remote_controller()
    revoked = [
        item
        for item in service.event_log.payloads("remote.control_changed")
        if item["reason"] == "revoked"
    ]
    assert len(revoked) == 1
    assert revoked[0]["device_key"] == device_key


@pytest.mark.asyncio
async def test_control_status_free_payload_uses_nulls(service) -> None:
    status = await call(service, "status", "remote.control_status")
    assert status == {
        "state": "free",
        "device_key": None,
        "expires_at": None,
        "grace_expires_at": None,
        "reason": None,
    }
