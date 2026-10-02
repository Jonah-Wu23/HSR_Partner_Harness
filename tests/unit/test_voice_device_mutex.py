from __future__ import annotations

import asyncio
import io
import json
import socket

import aiohttp
import pytest

from pair_harness.core.audio import SpeechQueue
from pair_harness.desktop_backend.application_service import ServiceError
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter
from pair_harness.desktop_backend.ws_server import WSServerMode
from tests.service_helpers import call, expect_service_error
from tests.voice_helpers import FakePlayer, attach_desktop_runtime, character_reply


def remote(
    method: str,
    device_key: str | None,
    *,
    connection_key: str | None = None,
    **params,
) -> DesktopCommand:
    """经已鉴权远程连接到达的命令；身份由传输层注入。"""
    return DesktopCommand(
        request_id=f"{method}-{device_key}",
        method=method,
        params=params,
        origin="remote",
        connection_key=connection_key or f"conn-{device_key}",
        remote_device_key=device_key,
    )


async def test_remote_control_mutes_desktop_until_device_releases(service) -> None:
    queue = SpeechQueue()
    attach_desktop_runtime(service, queue=queue)

    first = await character_reply(service, "first", "第一句")
    assert queue.pending_message_id == first

    await service.handle_command(
        remote("remote.claim_control", "device-1", connection_key="conn-phone")
    )
    assert queue.pending == 0  # 认领时停掉桌面残留朗读

    await character_reply(service, "second", "控制期间的消息")
    assert queue.pending == 0

    # 意外断线进入宽限期，桌面仍然静音
    service.handle_remote_disconnect("conn-phone")
    assert service.has_active_remote_controller()
    await character_reply(service, "third", "断线期间的消息")
    assert queue.pending == 0

    # 其他连接断开不影响控制，重连后的新连接可以释放同一设备的控制
    service.handle_remote_disconnect("native-notifications")
    assert service.has_active_remote_controller()
    await service.handle_command(
        remote("remote.release_control", "device-1", connection_key="conn-phone-reconnected")
    )
    assert not service.has_active_remote_controller()

    fourth = await character_reply(service, "fourth", "恢复后的消息")
    assert queue.pending_message_id == fourth


async def test_mobile_tts_stop_stops_desktop_speech_only_while_controlled(
    service, monkeypatch
) -> None:
    # 开发机 Key 让作者音色生效，桌面重播才会真正入队
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-dashscope-key")
    runtime = attach_desktop_runtime(service)
    reply_id = await character_reply(service, "first", "你好")
    await service.handle_command(remote("remote.claim_control", "device-1"))

    # 控制设备让桌面重播一条回复，随后在手机上停止朗读
    await service.handle_command(remote("voice.tts_play", "device-1", message_id=reply_id))
    assert runtime.speech_queue_len == 1
    await call(service, "stop", "voice.mobile_tts_stop", message_id="m-phone")
    assert runtime.speech_queue_len == 0

    # 退出控制后迟到的手机停止请求不打断桌面朗读
    await service.handle_command(remote("remote.release_control", "device-1"))
    await character_reply(service, "second", "再说一句")
    assert runtime.speech_queue_len == 1
    await call(service, "late", "voice.mobile_tts_stop", message_id="m-phone")
    assert runtime.speech_queue_len == 1


async def test_voice_credentials_change_detaches_old_runtime(service) -> None:
    """保存语音凭据会重建语音运行时，旧运行时关闭后不再接收消息。"""
    old_queue, old_player = SpeechQueue(), FakePlayer()
    attach_desktop_runtime(service, queue=old_queue, player=old_player)

    await call(service, "config", "config.set", updates={"voice.api_key": "test-dashscope-key"})
    assert service.voice_runtime is None  # 演示服务不构建真实语音运行时
    assert old_player.closed == 1

    new_queue = SpeechQueue()
    interrupted: list[tuple[str, str | None, str]] = []
    attach_desktop_runtime(service, queue=new_queue, interrupted=interrupted)
    reply_id = await character_reply(service, "after-rebuild", "重建后的消息")

    assert old_queue.pending == 0
    assert new_queue.pending_message_id == reply_id
    assert interrupted == []  # 同一条消息只送达一次，没有自我抢占


@pytest.mark.parametrize("origin,device_key", [("desktop", "forged"), ("remote", None)])
async def test_remote_control_requires_transport_identity(service, origin, device_key) -> None:
    await expect_service_error(
        lambda: service.handle_command(
            DesktopCommand(
                request_id="invalid",
                method="remote.claim_control",
                params={"remote_device_key": "forged"},
                origin=origin,
                remote_device_key=device_key,
            )
        ),
        "remote_identity_required",
    )
    assert not service.has_active_remote_controller()


def _playback_command(method: str, *, origin: str, device_key: str | None) -> DesktopCommand:
    params = {"message_id": "m-1"} if method == "voice.tts_play" else {"text": "试听一句话。"}
    return DesktopCommand(
        request_id=f"play-{method}",
        method=method,
        params=params,
        origin=origin,
        connection_key=f"conn-{device_key}" if device_key else None,
        remote_device_key=device_key,
    )


@pytest.mark.parametrize("method", ["voice.tts_play", "voice.preview", "voice.card_preview"])
async def test_playback_guard_follows_control_lease(service, method) -> None:
    """租约有效期内只有持有设备能起播；释放租约后桌面恢复。"""
    claimed = await service.handle_command(remote("remote.claim_control", "device-holder"))
    assert claimed == {"claimed": True, "active_controllers": 1}

    held = await expect_service_error(
        lambda: service.handle_command(
            _playback_command(method, origin="desktop", device_key=None)
        ),
        "remote_playback_active",
    )
    assert "手机" not in str(held)  # 远程端不一律称作手机
    await expect_service_error(
        lambda: service.handle_command(
            _playback_command(method, origin="remote", device_key="device-other")
        ),
        "remote_playback_active",
        contains="另一台远程设备",
    )

    # 守卫放行持有设备与释放后的桌面；演示服务没有语音运行时，随后的失败是真实原因
    for origin, device_key in (("remote", "device-holder"), ("desktop", None)):
        if origin == "desktop":
            await service.handle_command(remote("remote.release_control", "device-holder"))
        with pytest.raises(ServiceError) as passed_guard:
            await service.handle_command(
                _playback_command(method, origin=origin, device_key=device_key)
            )
        assert passed_guard.value.code != "remote_playback_active"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _response(ws: aiohttp.ClientWebSocketResponse, request_id: str) -> dict:
    """读到 id 匹配的响应帧，跳过事件帧。"""
    while True:
        frame = await ws.receive(timeout=8)
        assert frame.type == aiohttp.WSMsgType.TEXT, frame
        message = json.loads(frame.data)
        if message.get("id") == request_id:
            return message


async def test_ws_authenticated_identity_survives_reconnect(service) -> None:
    stdout = io.StringIO()
    writer = JsonlWriter(stdout)
    router = SidecarRouter(service, writer)
    port = _free_port()
    disconnected = asyncio.Event()

    def on_disconnect(connection_key: str) -> None:
        service.handle_remote_disconnect(connection_key)
        disconnected.set()

    server = WSServerMode(
        dispatch=router.dispatch,
        authenticator=service.pairing_service,
        fanout=EventFanout(writer),
        static_root=None,
        port=port,
        on_disconnect=on_disconnect,
    )
    token = service.pairing_service.claim(
        service.pairing_service.issue_code(), device_name="phone"
    )

    def request(method: str, request_id: str, auth_token: str = token) -> dict:
        return {
            "kind": "request",
            "id": request_id,
            "method": method,
            "params": {},
            "auth": {"token": auth_token},
            "remote_device_key": "forged",
            "origin": "remote",
        }

    # stdin 上 JSON 自称的来源和身份不能取得控制
    await router.handle_line(json.dumps(request("remote.claim_control", "stdin")))
    assert not service.has_active_remote_controller()
    assert json.loads(stdout.getvalue().splitlines()[-1])["error"]["code"] == "remote_identity_required"

    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as first:
                await first.send_json(request("remote.claim_control", "invalid", "invalid"))
                assert (await _response(first, "invalid"))["error"]["code"] == "unauthorized"
                assert not service.has_active_remote_controller()
                await first.send_json(request("remote.claim_control", "claim"))
                assert (await _response(first, "claim"))["ok"] is True
            # 服务端走完断开清理后，控制仍归该设备
            await asyncio.wait_for(disconnected.wait(), timeout=2)
            assert service.has_active_remote_controller()
            async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as second:
                await second.send_json(request("remote.claim_control", "reclaim"))
                assert (await _response(second, "reclaim"))["result"]["active_controllers"] == 1
                await second.send_json(request("remote.release_control", "release"))
                assert (await _response(second, "release"))["result"]["active_controllers"] == 0
                assert not service.has_active_remote_controller()
    finally:
        await server.stop()
        await router.wait_for_tasks()
