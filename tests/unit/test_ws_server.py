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
from pair_harness.desktop_backend.router import JsonlWriter
from pair_harness.desktop_backend.ws_server import (
    UNAUTHENTICATED_METHODS,
    AuthDecision,
    WSServerMode,
)


class StubAuthenticator:
    """测试用桩鉴权：实现 RemoteAuthenticator Protocol。"""

    def __init__(self, valid_tokens: str | set[str] = "phone-token") -> None:
        self.valid_tokens = (
            {valid_tokens} if isinstance(valid_tokens, str) else set(valid_tokens)
        )
        self.calls: list[tuple[str | None, Any]] = []

    def authorize(self, token: str | None, method: str) -> AuthDecision:
        self.calls.append((token, method))
        if method in UNAUTHENTICATED_METHODS:
            return AuthDecision(allowed=True, reason="", device_name="pairing")
        if token in self.valid_tokens:
            return AuthDecision(allowed=True, reason="", device_name="my-phone")
        return AuthDecision(allowed=False, reason="missing_or_invalid_token")


class FakeDispatch:
    """假 dispatch：记录调用，并经 reply_sink 回写 response（与批 3 扩展签名一致）。"""

    def __init__(self, auto_reply: bool = True) -> None:
        self.auto_reply = auto_reply
        self.invoked: list[dict[str, Any]] = []

    def __call__(self, line: str, reply_sink: Any) -> None:
        payload = json.loads(line)
        self.invoked.append(payload)
        if self.auto_reply and reply_sink is not None and payload.get("id"):
            self._reply(reply_sink, payload["id"], {"echo": payload["method"]})

    @staticmethod
    def _reply(reply_sink: Any, rid: str, result: Any) -> None:
        reply_sink({"kind": "response", "id": rid, "ok": True, "result": result})


class Harness:
    def __init__(
        self,
        server: WSServerMode,
        base: str,
        fanout: EventFanout,
        fake: FakeDispatch,
        auth: StubAuthenticator,
    ) -> None:
        self.server = server
        self.base = base
        self.fanout = fanout
        self.fake = fake
        self.auth = auth


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _start(
    static_root: Any, *, authenticator: StubAuthenticator | None = None
) -> Harness:
    stdout = io.StringIO()
    fanout = EventFanout(JsonlWriter(stdout))
    fake = FakeDispatch()
    auth = authenticator or StubAuthenticator()
    port = _free_port()
    server = WSServerMode(
        dispatch=fake,
        authenticator=auth,
        fanout=fanout,
        static_root=static_root,
        port=port,
    )
    await server.start()
    return Harness(server, f"http://127.0.0.1:{port}", fanout, fake, auth)


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


async def _auth_ws(session: aiohttp.ClientSession, base: str, rid: str) -> aiohttp.ClientWebSocketResponse:
    """建立连接并完成一次带 token 鉴权请求，返回已订阅的连接。"""
    ws = await session.ws_connect(base + "/ws")
    await ws.send_str(json.dumps(_req("chat.submit", rid, token="phone-token")))
    await _recv_text(ws, rid)
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


@pytest.mark.asyncio
async def test_unauthenticated_command_rejected() -> None:
    h = await _start(None)
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps(_req("chat.submit", "r1")))
                resp = await _recv_text(ws, "r1")
        assert resp["ok"] is False
        assert resp["error"]["code"] == "unauthorized"
        assert resp["id"] == "r1"
        assert h.fake.invoked == []  # 鉴权步已拦截，未进入 dispatch
    finally:
        await h.server.stop()


@pytest.mark.asyncio
async def test_remote_pair_passes_to_dispatch() -> None:
    h = await _start(None)
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps(_req("remote.pair", "r2")))  # 无 token
                resp = await _recv_text(ws, "r2")
        assert resp["ok"] is True
        assert h.fake.invoked and h.fake.invoked[-1]["method"] == "remote.pair"
    finally:
        await h.server.stop()


@pytest.mark.asyncio
async def test_authenticated_command_dispatched_and_response_back_on_same_connection() -> None:
    h = await _start(None)
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps(_req("chat.submit", "r3", token="phone-token")))
                resp = await _recv_text(ws, "r3")
        assert resp["ok"] is True
        assert h.fake.invoked and h.fake.invoked[-1]["method"] == "chat.submit"
        assert resp["result"] == {"echo": "chat.submit"}
    finally:
        await h.server.stop()


@pytest.mark.asyncio
async def test_authenticated_connection_cannot_switch_token() -> None:
    auth = StubAuthenticator({"phone-token", "other-token"})
    h = await _start(None, authenticator=auth)
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(
                    json.dumps(_req("chat.submit", "first", token="phone-token"))
                )
                assert (await _recv_text(ws, "first"))["ok"] is True

                await ws.send_str(
                    json.dumps(_req("chat.submit", "second", token="other-token"))
                )
                switched = await _recv_text(ws, "second")

        assert switched["ok"] is False
        assert switched["error"]["code"] == "connection_identity_mismatch"
        assert [frame["id"] for frame in h.fake.invoked] == ["first"]
    finally:
        await h.server.stop()


@pytest.mark.asyncio
async def test_invalid_json_frame_returns_protocol_error() -> None:
    h = await _start(None)
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str("this is not json {")
                msg = await ws.receive(timeout=8)
                assert msg.type == WSMsgType.TEXT
                obj = json.loads(msg.data)
                assert obj["kind"] == "error"
                assert obj["error"]["code"] == "invalid_json"
        assert h.fake.invoked == []
    finally:
        await h.server.stop()


@pytest.mark.asyncio
async def test_non_object_frame_returns_protocol_error() -> None:
    h = await _start(None)
    try:
        async with aiohttp.ClientSession() as session:
            async with await session.ws_connect(h.base + "/ws") as ws:
                await ws.send_str(json.dumps([1, 2, 3]))
                msg = await ws.receive(timeout=8)
                assert msg.type == WSMsgType.TEXT
                obj = json.loads(msg.data)
                assert obj["kind"] == "error"
                assert obj["error"]["code"] == "invalid_message"
        assert h.fake.invoked == []
    finally:
        await h.server.stop()


# ------------------------------------------------------------------ 事件扇出


@pytest.mark.asyncio
async def test_events_fanout_and_continuity_after_client_disconnect() -> None:
    """冒烟：两台已鉴权客户端收到同一序号事件；断一台后另一台继续收后续事件。"""
    h = await _start(None)
    try:
        async with aiohttp.ClientSession() as session:
            ws_a = await _auth_ws(session, h.base, "auth-a")
            ws_b = await _auth_ws(session, h.base, "auth-b")

            h.fanout.publish(_event(0))
            ev_a = await _recv_text(ws_a)
            ev_b = await _recv_text(ws_b)
            assert ev_a["kind"] == "event" and ev_a["sequence"] == 0
            assert ev_b == ev_a  # 同一序号事件流

            # 主动断开 A，B 继续收后续事件
            await ws_a.close()
            h.fanout.publish(_event(1))
            ev_b1 = await _recv_text(ws_b)
            assert ev_b1["kind"] == "event" and ev_b1["sequence"] == 1
            await ws_b.close()
    finally:
        await h.server.stop()


@pytest.mark.asyncio
async def test_disconnect_unsubscribes_connection() -> None:
    h = await _start(None)
    try:
        async with aiohttp.ClientSession() as session:
            ws_a = await _auth_ws(session, h.base, "auth-a")
            await ws_a.close()
            await asyncio.sleep(0.2)
            assert len(h.fanout._subscriptions) == 0
    finally:
        await h.server.stop()


# ------------------------------------------------------------------ 静态资源


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_no_static_root_returns_404() -> None:
    h = await _start(None)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(h.base + "/") as r:
                assert r.status == 404
    finally:
        await h.server.stop()