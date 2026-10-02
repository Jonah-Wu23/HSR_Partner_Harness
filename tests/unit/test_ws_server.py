from __future__ import annotations

import asyncio
import io
import json
import socket
from typing import Any

import aiohttp
import pytest
from aiohttp import WSMsgType

from pair_harness.desktop_backend.event_fanout import EventFanout
from pair_harness.desktop_backend.pairing import PairingService, token_key
from pair_harness.desktop_backend.router import JsonlWriter
from pair_harness.desktop_backend.ws_server import WSServerMode


class EchoDispatch:
    """经构造参数注入的 dispatch：记录传输层注入的身份，并经 reply_sink 回写 response。"""

    def __init__(self) -> None:
        self.invoked: list[dict[str, Any]] = []

    def __call__(
        self,
        line: str,
        reply_sink: Any,
        *,
        origin: str,
        connection_key: str | None,
        device_key: str | None,
        device_name: str | None,
    ) -> None:
        payload = json.loads(line)
        payload["_origin"] = origin
        payload["_connection_key"] = connection_key
        payload["_device_key"] = device_key
        payload["_device_name"] = device_name
        self.invoked.append(payload)
        reply_sink(
            {
                "kind": "response",
                "id": payload["id"],
                "ok": True,
                "result": {"echo": payload["method"]},
            }
        )


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Harness:
    def __init__(
        self,
        server: WSServerMode,
        base: str,
        fanout: EventFanout,
        dispatch: EchoDispatch,
        pairing: PairingService,
        clock: _Clock,
    ) -> None:
        self.server = server
        self.base = base
        self.fanout = fanout
        self.dispatch = dispatch
        self.pairing = pairing
        self.clock = clock

    def token(self, device_name: str = "my-phone") -> str:
        return self.pairing.claim(self.pairing.issue_code(), device_name=device_name)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _start(
    static_root: Any = None,
    *,
    on_disconnect: Any = lambda _key: None,
) -> Harness:
    fanout = EventFanout(JsonlWriter(io.StringIO()))
    dispatch = EchoDispatch()
    clock = _Clock()
    pairing = PairingService(clock=clock)
    port = _free_port()
    server = WSServerMode(
        dispatch=dispatch,
        authenticator=pairing,
        fanout=fanout,
        static_root=static_root,
        port=port,
        on_disconnect=on_disconnect,
    )
    await server.start()
    return Harness(server, f"http://127.0.0.1:{port}", fanout, dispatch, pairing, clock)


def _req(method: str, rid: str, token: str | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"kind": "request", "id": rid, "method": method, "params": {}}
    if token:
        frame["auth"] = {"token": token}
    return frame


async def _recv_text(
    ws: aiohttp.ClientWebSocketResponse, rid: str | None = None
) -> dict[str, Any]:
    """读取下一帧；给出 rid 时跳到 id 匹配的帧（跳过事件帧与无关响应）。"""
    while True:
        msg = await ws.receive(timeout=8)
        if msg.type == WSMsgType.ERROR:
            raise RuntimeError(f"WS 连接出错：{ws.exception()}")
        if msg.type != WSMsgType.TEXT:
            continue
        obj = json.loads(msg.data)
        if rid is None or obj.get("id") == rid:
            return obj


async def _auth_ws(
    session: aiohttp.ClientSession, h: Harness, rid: str, token: str
) -> aiohttp.ClientWebSocketResponse:
    """建立连接并完成一次带 token 的请求，返回已订阅事件的连接。"""
    ws = await session.ws_connect(h.base + "/ws")
    await ws.send_str(json.dumps(_req("chat.submit", rid, token=token)))
    assert (await _recv_text(ws, rid))["ok"] is True
    return ws


def _event(sequence: int) -> dict[str, Any]:
    return {
        "kind": "event",
        "event": "remote.test",
        "stream_id": "local",
        "sequence": sequence,
        "payload": {},
    }


# ------------------------------------------------------------------ 鉴权门


@pytest.mark.parametrize("method", ["chat.submit", "ping"])
async def test_command_without_token_rejected(method: str) -> None:
    h = await _start()
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps(_req(method, "r1")))
                resp = await _recv_text(ws, "r1")
        assert resp["ok"] is False
        assert resp["error"] == {"code": "unauthorized", "message": "missing_token"}
        assert h.dispatch.invoked == []
    finally:
        await h.server.stop()


async def test_remote_pair_passes_to_dispatch_without_token() -> None:
    h = await _start()
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps(_req("remote.pair", "r2")))
                resp = await _recv_text(ws, "r2")
        assert resp["ok"] is True
        assert h.dispatch.invoked[-1]["method"] == "remote.pair"
        assert h.dispatch.invoked[-1]["_device_key"] is None
    finally:
        await h.server.stop()


async def test_authenticated_command_dispatched_with_transport_identity() -> None:
    h = await _start()
    token = h.token("my-phone")
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps(_req("chat.submit", "r3", token=token)))
                resp = await _recv_text(ws, "r3")
        assert resp["result"] == {"echo": "chat.submit"}
        dispatched = h.dispatch.invoked[-1]
        assert dispatched["_origin"] == "remote"
        assert dispatched["_device_key"] == token_key(token)
        assert dispatched["_device_name"] == "my-phone"
        assert dispatched["_connection_key"]
    finally:
        await h.server.stop()


async def test_control_plane_method_rejected_with_forbidden_scope() -> None:
    h = await _start()
    token = h.token()
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps(_req("remote.issue_code", "c1", token=token)))
                resp = await _recv_text(ws, "c1")
        assert resp["error"] == {"code": "forbidden_scope", "message": "forbidden_scope"}
        assert h.dispatch.invoked == []
    finally:
        await h.server.stop()


async def test_authenticated_connection_cannot_switch_token() -> None:
    h = await _start()
    first_token = h.token("phone-a")
    other_token = h.token("phone-b")
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps(_req("chat.submit", "first", token=first_token)))
                assert (await _recv_text(ws, "first"))["ok"] is True

                await ws.send_str(json.dumps(_req("chat.submit", "second", token=other_token)))
                switched = await _recv_text(ws, "second")

        assert switched["ok"] is False
        assert switched["error"]["code"] == "connection_identity_mismatch"
        assert [frame["id"] for frame in h.dispatch.invoked] == ["first"]
    finally:
        await h.server.stop()


@pytest.mark.parametrize("reason", ["expired_token", "revoked_token"])
async def test_token_failure_on_authenticated_connection_unsubscribes_and_closes(
    reason: str,
) -> None:
    """已鉴权连接的令牌失效后，先收到带原因的拒绝，随后退订并以 4401 断开。"""
    h = await _start()
    token = h.token("my-phone")
    try:
        async with aiohttp.ClientSession() as session:
            ws = await _auth_ws(session, h, "auth-1", token)
            assert len(h.fanout._subscriptions) == 1

            if reason == "expired_token":
                h.clock.now += 8 * 86400
            else:
                h.pairing.revoke_device("my-phone")
            await ws.send_str(json.dumps(_req("chat.submit", "after", token=token)))
            rejected = await _recv_text(ws, "after")
            assert rejected["error"] == {"code": "unauthorized", "message": reason}

            closing = await ws.receive(timeout=8)
            assert closing.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)
            assert ws.close_code == 4401
            assert len(h.fanout._subscriptions) == 0
    finally:
        await h.server.stop()


@pytest.mark.parametrize(
    ("frame", "code"),
    [
        ("this is not json {", "invalid_json"),
        (json.dumps([1, 2, 3]), "invalid_message"),
        (json.dumps({"kind": "request", "id": "x", "method": 1}), "invalid_message"),
        (
            json.dumps(
                {"kind": "request", "id": "x", "method": "chat.submit", "auth": {"token": 1}}
            ),
            "invalid_message",
        ),
    ],
)
async def test_malformed_frame_returns_protocol_error(frame: str, code: str) -> None:
    h = await _start()
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(frame)
                obj = await _recv_text(ws)
        assert obj["kind"] == "error"
        assert obj["error"]["code"] == code
        assert h.dispatch.invoked == []
    finally:
        await h.server.stop()


# ------------------------------------------------------------------ 事件扇出与断开


async def test_events_fanout_and_continuity_after_client_disconnect() -> None:
    """两台已鉴权客户端收到同一事件；断开一台后另一台继续收后续事件。"""
    h = await _start()
    token_a = h.token("phone-a")
    token_b = h.token("phone-b")
    try:
        async with aiohttp.ClientSession() as session:
            ws_a = await _auth_ws(session, h, "auth-a", token_a)
            ws_b = await _auth_ws(session, h, "auth-b", token_b)

            h.fanout.publish(_event(0))
            ev_a = await _recv_text(ws_a)
            ev_b = await _recv_text(ws_b)
            assert ev_a["sequence"] == 0
            assert ev_b == ev_a

            await ws_a.close()
            h.fanout.publish(_event(1))
            assert (await _recv_text(ws_b))["sequence"] == 1
            await ws_b.close()
    finally:
        await h.server.stop()


async def test_disconnect_unsubscribes_and_reports_connection_key() -> None:
    """连接断开时退订事件，并以 dispatch 时注入的连接 key 调用清理回调。"""
    disconnected: list[str] = []
    h = await _start(on_disconnect=disconnected.append)
    token = h.token()
    try:
        async with aiohttp.ClientSession() as session:
            ws = await _auth_ws(session, h, "dc-1", token)
            key_at_dispatch = h.dispatch.invoked[-1]["_connection_key"]
            await ws.close()
            for _ in range(50):
                if disconnected:
                    break
                await asyncio.sleep(0.1)
        assert disconnected == [key_at_dispatch]
        assert len(h.fanout._subscriptions) == 0
    finally:
        await h.server.stop()


# ------------------------------------------------------------------ 静态资源


async def test_static_traversal_rejected(tmp_path: Any) -> None:
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "index.html").write_text("<html>pwa</html>")
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRETMARKER")

    h = await _start(static_root)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", h.server.port)
        writer.write(b"GET /../secret.txt HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        await writer.drain()
        data = await reader.read(4096)
        writer.close()
        await writer.wait_closed()

        header = data.decode("latin1").split("\r\n")[0]
        # 路径穿越必须被拒绝（4xx），且不泄出目录外文件内容
        assert header.startswith("HTTP/1.1 4"), header
        assert b"SECRETMARKER" not in data
    finally:
        await h.server.stop()


async def test_static_serves_index_and_file(tmp_path: Any) -> None:
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "index.html").write_text("<html>pwa</html>")
    (static_root / "app.js").write_text("console.log('x')")

    h = await _start(static_root)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(h.base + "/") as r:
                assert r.status == 200
                assert "pwa" in await r.text()
            async with session.get(h.base + "/app.js") as r2:
                assert r2.status == 200
                assert (await r2.text()).strip() == "console.log('x')"
    finally:
        await h.server.stop()


async def test_no_static_root_returns_404() -> None:
    h = await _start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(h.base + "/") as r:
                assert r.status == 404
    finally:
        await h.server.stop()
