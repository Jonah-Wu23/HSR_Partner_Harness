"""V0.3.8 D2：桌面与手机播放设备互斥与控制权链路测试。

覆盖：
1. remote.claim_control 登记活跃控制器；
2. 手机处于远程控制状态时，角色消息到达后桌面本地播放器保持静音（不入队）；
3. 手机端 voice.mobile_tts_stop 联动停止桌面端本地播放；
4. 意外断线保持静音，重连后显式释放或撤销设备才恢复桌面播放资格。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from pair_harness.core.contracts import Message, MessageKind, MessageSource
from pair_harness.desktop_backend.commands import DesktopCommand
from test_v035_wiring import command, service  # noqa: F401


@pytest.mark.asyncio
async def test_device_mutex_claim_and_release(service) -> None:
    """remote.claim_control 和 release_control 正确切换控制器活跃状态。"""
    assert not service.has_active_remote_controller()

    # 认领控制
    cmd_claim = DesktopCommand(
        request_id="1",
        method="remote.claim_control",
        params={},
        origin="remote",
        connection_key="conn-phone-1",
        remote_device_key="device-1",
    )
    res_claim = await service.handle_command(cmd_claim)
    assert res_claim["claimed"] is True
    assert service.has_active_remote_controller()

    # 释放控制
    cmd_release = DesktopCommand(
        request_id="2",
        method="remote.release_control",
        params={},
        origin="remote",
        connection_key="conn-phone-1",
        remote_device_key="device-1",
    )
    res_release = await service.handle_command(cmd_release)
    assert res_release["released"] is True
    assert not service.has_active_remote_controller()


@pytest.mark.asyncio
async def test_desktop_muted_when_remote_controller_active(service) -> None:
    """手机处于控制状态时，新消息到达不会送入桌面本地 VoiceRuntime。"""
    mock_runtime = MagicMock()
    mock_runtime.on_message = MagicMock()
    mock_runtime.stop_speaking = MagicMock()
    mock_runtime.stop_speaking_async = AsyncMock()
    service.attach_voice_runtime(mock_runtime)

    # 未认领控制前，消息会通知 runtime.on_message
    msg1 = Message(
        message_id="msg-1",
        conversation_id=service.current_conversation_id,
        pair_id=service.pair_config.pair_id,
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text="第一句台词",
    )
    service.orchestrator._message_listeners[0](msg1)
    assert mock_runtime.on_message.call_count == 1

    # 手机认领控制
    cmd_claim = DesktopCommand(
        request_id="10",
        method="remote.claim_control",
        params={},
        origin="remote",
        connection_key="conn-phone-1",
        remote_device_key="device-1",
    )
    await service.handle_command(cmd_claim)
    # 认领瞬间停止桌面残留声音
    mock_runtime.stop_speaking_async.assert_awaited_once()

    # 手机控制期间，新消息到达桌面端必须完全保持静音！
    msg2 = Message(
        message_id="msg-2",
        conversation_id=service.current_conversation_id,
        pair_id=service.pair_config.pair_id,
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text="手机控制期间的消息",
    )
    service.orchestrator._message_listeners[0](msg2)
    # 调用计数依然是 1（第二句被拦截静音）
    assert mock_runtime.on_message.call_count == 1

    # 手机断开连接
    service.handle_remote_disconnect("conn-phone-1")
    assert service.has_active_remote_controller()
    service.orchestrator._message_listeners[0](msg2)
    assert mock_runtime.on_message.call_count == 1

    # 重连的新连接可释放同一设备此前取得的控制；通知连接断开没有影响。
    service.handle_remote_disconnect("native-notifications")
    await service.handle_command(DesktopCommand(
        request_id="release-after-reconnect",
        method="remote.release_control",
        params={},
        origin="remote",
        connection_key="conn-phone-reconnected",
        remote_device_key="device-1",
    ))
    assert not service.has_active_remote_controller()

    # 断开后桌面恢复播放资格
    msg3 = Message(
        message_id="msg-3",
        conversation_id=service.current_conversation_id,
        pair_id=service.pair_config.pair_id,
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text="恢复后的消息",
    )
    service.orchestrator._message_listeners[0](msg3)
    assert mock_runtime.on_message.call_count == 2


@pytest.mark.asyncio
async def test_mobile_tts_stop_also_stops_desktop_player(service) -> None:
    """手机端发起的 voice.mobile_tts_stop 联动停止桌面本地播放器。"""
    mock_runtime = MagicMock()
    mock_runtime.stop_speaking_async = AsyncMock()
    service.voice_runtime = mock_runtime
    await service.handle_command(DesktopCommand(
        request_id="claim", method="remote.claim_control", params={},
        origin="remote", connection_key="phone", remote_device_key="device",
    ))
    mock_runtime.stop_speaking_async.reset_mock()

    await service.handle_command(
        command("1", "voice.mobile_tts_stop", message_id="m-test-stop")
    )
    mock_runtime.stop_speaking_async.assert_awaited_once()

    await service.handle_command(DesktopCommand(
        request_id="release", method="remote.release_control", params={},
        origin="remote", connection_key="phone", remote_device_key="device",
    ))
    mock_runtime.stop_speaking_async.reset_mock()
    await service.handle_command(command("late", "voice.mobile_tts_stop", message_id="old"))
    mock_runtime.stop_speaking_async.assert_not_called()
    mock_runtime.stop_speaking.assert_not_called()


@pytest.mark.asyncio
async def test_voice_rebuild_removes_old_listener(service) -> None:
    runtime = MagicMock()
    runtime.shutdown = AsyncMock()
    service.attach_voice_runtime(runtime)
    assert len(service.orchestrator._message_listeners) == 1

    await service._rebuild_voice_runtime_locked()
    assert service.voice_runtime is None
    assert service.orchestrator._message_listeners == []
    runtime.shutdown.assert_awaited_once()

    replacement = MagicMock()
    service.attach_voice_runtime(replacement)
    message = Message(
        conversation_id=service.current_conversation_id,
        pair_id=service.pair_config.pair_id,
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text="重建后只交给当前语音运行时",
    )
    for listener in service.orchestrator._message_listeners:
        listener(message)
    runtime.on_message.assert_not_called()
    replacement.on_message.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_remote_control_release_preserves_other_device(service) -> None:
    for device in ("phone-a", "phone-b"):
        await service.handle_command(DesktopCommand(
            request_id=device, method="remote.claim_control", params={},
            origin="remote", connection_key=device, remote_device_key=device,
        ))
    await service.handle_command(DesktopCommand(
        request_id="release", method="remote.release_control", params={},
        origin="remote", connection_key="new-a", remote_device_key="phone-a",
    ))
    assert set(service._control_leases) == {"phone-b"}


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,device_key", [("desktop", "forged"), ("remote", None)])
async def test_remote_control_requires_transport_identity(service, origin, device_key) -> None:
    from pair_harness.desktop_backend.application_service import ServiceError

    with pytest.raises(ServiceError) as exc:
        await service.handle_command(DesktopCommand(
            request_id="invalid", method="remote.claim_control",
            params={"remote_device_key": "forged"}, origin=origin,
            remote_device_key=device_key,
        ))
    assert exc.value.code == "remote_identity_required"
    assert not service.has_active_remote_controller()


@pytest.mark.asyncio
async def test_revoke_device_releases_its_disconnected_control(service) -> None:
    import hashlib

    code = service.pairing_service.issue_code()
    token = service.pairing_service.claim(code, device_name="phone")
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    await service.handle_command(DesktopCommand(
        request_id="claim", method="remote.claim_control", params={},
        origin="remote", connection_key="disconnected", remote_device_key=key,
    ))
    service.handle_remote_disconnect("disconnected")
    assert service.has_active_remote_controller()
    await service.handle_command(command("revoke", "remote.revoke", device_name="phone"))
    assert not service.has_active_remote_controller()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["voice.tts_play", "voice.preview", "voice.card_preview"])
async def test_remote_control_blocks_explicit_desktop_audio(service, method) -> None:
    from pair_harness.desktop_backend.application_service import ServiceError

    service.voice_runtime = MagicMock()
    service.voice_runtime.stop_speaking_async = AsyncMock()
    await service.handle_command(DesktopCommand(
        request_id="claim", method="remote.claim_control", params={},
        origin="remote", connection_key="phone", remote_device_key="device",
    ))
    with pytest.raises(ServiceError) as exc:
        await service.handle_command(command("play", method))
    assert exc.value.code == "remote_playback_active"
    service.voice_runtime.replay_message.assert_not_called()
    service.voice_runtime.enqueue_text.assert_not_called()


@pytest.mark.asyncio
async def test_ws_authenticated_identity_survives_reconnect(service) -> None:
    import asyncio
    import io
    import json

    import aiohttp

    from pair_harness.desktop_backend.event_fanout import EventFanout
    from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter
    from pair_harness.desktop_backend.ws_server import WSServerMode
    from test_ws_server import _free_port, _recv_text

    stdout = io.StringIO()
    writer = JsonlWriter(stdout)
    router = SidecarRouter(service, writer)
    port = _free_port()
    server = WSServerMode(
        dispatch=router.dispatch, authenticator=service.pairing_service,
        fanout=EventFanout(writer), static_root=None, port=port,
        on_disconnect=service.handle_remote_disconnect,
    )
    token = service.pairing_service.claim(
        service.pairing_service.issue_code(), device_name="phone",
    )

    def request(method, rid, auth_token=token):
        return {"kind": "request", "id": rid, "method": method,
                "params": {}, "auth": {"token": auth_token},
                "remote_device_key": "forged", "origin": "remote"}

    # JSON 中伪造来源和身份不能使桌面输入取得控制。
    await router.handle_line(json.dumps(request("remote.claim_control", "stdin")))
    assert not service.has_active_remote_controller()
    assert json.loads(stdout.getvalue().splitlines()[-1])["error"]["code"] == "remote_identity_required"

    await server.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as first:
                await first.send_json(request("remote.claim_control", "invalid", "invalid"))
                denied = await _recv_text(first, "invalid")
                assert denied["error"]["code"] == "unauthorized"
                assert not service.has_active_remote_controller()
                await first.send_json(request("remote.claim_control", "claim"))
                assert (await _recv_text(first, "claim"))["ok"] is True
            # 等服务端实际走完断开清理，再验证播放归属仍保留。
            async def wait_disconnected():
                while server._connections:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(wait_disconnected(), timeout=2)
            assert service.has_active_remote_controller()
            async with session.ws_connect(f"http://127.0.0.1:{port}/ws") as second:
                await second.send_json(request("remote.claim_control", "reclaim"))
                assert (await _recv_text(second, "reclaim"))["result"]["active_controllers"] == 1
                await second.send_json(request("remote.release_control", "release"))
                assert (await _recv_text(second, "release"))["result"]["active_controllers"] == 0
                assert not service.has_active_remote_controller()
    finally:
        await server.stop()
        await router.wait_for_tasks()
