from __future__ import annotations

import time

import pair_harness.desktop_backend.application_service as app_service_module
from pair_harness.desktop_backend.commands import CommandContext, DesktopCommand
from pair_harness.desktop_backend.pairing import token_key
from tests.service_helpers import call

# 租约时间按 time.monotonic 计算；用例回拨 last_refresh_at 模拟时间流逝。
TTL = app_service_module.CONTROL_LEASE_TTL_S
GRACE = app_service_module.CONTROL_LEASE_GRACE_S


def _remote_command(method: str, device_key: str) -> DesktopCommand:
    """传输层为已鉴权远程连接注入身份后的命令。"""
    return DesktopCommand(
        request_id=method,
        method=method,
        params={},
        origin="remote",
        connection_key=f"conn-{device_key}",
        remote_device_key=device_key,
    )


async def claim(service, device_key: str) -> dict:
    return await service.handle_command(_remote_command("remote.claim_control", device_key))


async def release(service, device_key: str) -> dict:
    return await service.handle_command(_remote_command("remote.release_control", device_key))


async def ping(service, device_key: str) -> dict:
    return await service.handle_command(_remote_command("ping", device_key))


async def test_claim_records_lease_and_snapshot(service) -> None:
    free = {
        "state": "free",
        "device_key": None,
        "expires_at": None,
        "grace_expires_at": None,
        "reason": None,
    }
    assert await call(service, "status-free", "remote.control_status") == free
    assert service.bootstrap()["remote_control"] == free

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


async def test_non_holder_ping_does_not_renew(service) -> None:
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    lease.last_refresh_at = time.monotonic() - TTL + 5
    before = lease.expires_at

    await ping(service, "device-2")
    assert lease.expires_at == before
    assert lease.reason == "claimed"
    assert set(service._control_leases) == {"device-1"}


async def test_repeat_claim_renews_without_event(service) -> None:
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    lease.last_refresh_at = time.monotonic() - TTL + 1
    before = lease.expires_at

    result = await claim(service, "device-1")
    assert result == {"claimed": True, "active_controllers": 1}
    assert lease.expires_at > before
    assert len(service.event_log.payloads("remote.control_changed")) == 1


async def test_lease_expiry_reclaims_and_restores_desktop(service) -> None:
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    lease.last_refresh_at = time.monotonic() - TTL - 0.01

    assert not service.has_active_remote_controller()
    assert service._control_leases == {}
    # 没有租约时桌面调用方恢复播放资格
    service._require_playback_control(CommandContext())

    events = service.event_log.payloads("remote.control_changed")
    assert [item["reason"] for item in events] == ["claimed", "expired"]
    assert events[-1]["state"] == "free"
    assert events[-1]["device_key"] == "device-1"
    assert service.bootstrap()["remote_control"]["state"] == "free"


def _changes(service, reason: str) -> list[dict]:
    return [
        item
        for item in service.event_log.payloads("remote.control_changed")
        if item["reason"] == reason
    ]


async def test_disconnect_grace_then_expiry(service) -> None:
    """断连不立即释放：宽限内保持控制，超过 TTL 加宽限才回收。"""
    await claim(service, "device-1")
    lease = service._control_leases["device-1"]

    service.handle_remote_disconnect("conn-device-1")
    assert service.has_active_remote_controller()
    assert lease.grace_expires_at is not None
    assert lease.grace_expires_at > lease.expires_at

    # 距最后一次续租 TTL+1s：超出 TTL 但在宽限内，仍持有。
    lease.last_refresh_at = time.monotonic() - TTL - 1
    assert service.has_active_remote_controller()
    assert _changes(service, "expired") == []

    lease.last_refresh_at = time.monotonic() - TTL - GRACE - 0.01
    assert not service.has_active_remote_controller()
    expired = _changes(service, "expired")
    assert len(expired) == 1
    assert expired[0]["grace_expires_at"] is not None


async def test_reconnect_claim_clears_grace(service) -> None:
    await claim(service, "device-1")
    service.handle_remote_disconnect("conn-device-1")
    assert service._control_leases["device-1"].grace_expires_at is not None

    await claim(service, "device-1")
    lease = service._control_leases["device-1"]
    assert lease.grace_expires_at is None
    assert service.has_active_remote_controller()


async def test_release_only_reclaims_own_device(service) -> None:
    await claim(service, "device-1")
    await claim(service, "device-2")

    assert await release(service, "device-1") == {"released": True, "active_controllers": 1}
    assert set(service._control_leases) == {"device-2"}
    assert service.has_active_remote_controller()
    assert [item["device_key"] for item in _changes(service, "released")] == ["device-1"]


async def test_release_unknown_device_is_idempotent(service) -> None:
    assert await release(service, "device-x") == {"released": True, "active_controllers": 0}
    assert service.event_log.payloads("remote.control_changed") == []


async def test_revoke_reclaims_matching_lease(service) -> None:
    token = service.pairing_service.claim(
        service.pairing_service.issue_code(), device_name="phone"
    )
    device_key = token_key(token)
    await claim(service, device_key)
    assert service.has_active_remote_controller()

    await call(service, "revoke", "remote.revoke", device_name="phone")
    assert not service.has_active_remote_controller()
    assert [item["device_key"] for item in _changes(service, "revoked")] == [device_key]
