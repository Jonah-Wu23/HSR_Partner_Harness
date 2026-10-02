from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from aiohttp import WSMsgType, web

from .event_fanout import EventFanout
from .protocol import encode_message, protocol_error, response_error
from .pwa_static import add_static_routes

logger = logging.getLogger(__name__)

# 不需要令牌即可调用的命令（配对握手）。
UNAUTHENTICATED_METHODS: frozenset[str] = frozenset({"remote.pair"})


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    reason: str = ""  # 拒绝原因，原样作为 unauthorized 回执的 message
    device_name: str = ""
    # 令牌键（令牌的 SHA-256 摘要），作为设备身份随命令下传；无令牌时为 None。
    device_key: str | None = None


class RemoteAuthenticator(Protocol):
    def authorize(self, token: str | None, method: str) -> AuthDecision: ...


@dataclass(frozen=True)
class RemoteServe:
    """WS 服务器监听成功后的接入信息，随 serve.started 与 app.bootstrap 下发。"""

    port: int
    lan: bool
    # 局域网模式下探测不到本机局域网地址时为 None
    host: str | None

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "mode": "lan" if self.lan else "loopback",
            "tls": False,
        }
        if self.host is None:
            payload["reason"] = "no_lan_address"
        return payload


def _frame_id(payload: dict[str, Any]) -> str | None:
    candidate = payload.get("id")
    if isinstance(candidate, str) and candidate:
        return candidate
    return None


class _RemoteConnection:
    """一条远端 WS 连接：下行队列、事件扇出订阅与写任务。"""

    def __init__(self, fanout: EventFanout, ws: web.WebSocketResponse) -> None:
        self._fanout = fanout
        self._ws = ws
        # 连接唯一 key；手机语音会话与控制租约绑定它，断开时按 key 清理。
        self.key = uuid.uuid4().hex
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscription: Any = None
        self._closed = False
        # 首次业务鉴权后固定的设备身份（令牌键）；None 表示尚未鉴权。
        self.device_key: str | None = None
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def _writer_loop(self) -> None:
        while True:
            envelope = await self._queue.get()
            try:
                await self._ws.send_str(encode_message(envelope))
            except ConnectionError:
                # 对端已断开，只停掉本条连接。
                self._teardown()
                return

    def send(self, envelope: dict) -> None:
        """同步入队，供 dispatch 回写与事件扇出共用。"""
        if self._closed:
            return
        self._queue.put_nowait(envelope)

    def subscribe(self) -> None:
        if self._subscription is None:
            self._subscription = self._fanout.subscribe(self.send)

    def _teardown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._subscription is not None:
            self._subscription.unsubscribe()
            self._subscription = None

    def detach(self) -> None:
        """同步退订并停写（幂等），撤销时立即切断事件下发。"""
        self._teardown()

    async def close(self, *, code: int = 1000, message: bytes = b"") -> None:
        self._teardown()
        if not self._writer_task.done():
            self._writer_task.cancel()
            await asyncio.wait({self._writer_task})
        # 关闭前发出已入队的帧：鉴权失败断开时，客户端要先收到带原因的
        # 错误回执，才能区分令牌过期与撤销。
        while not self._queue.empty():
            try:
                await self._ws.send_str(encode_message(self._queue.get_nowait()))
            except ConnectionError:
                break
        await self._ws.close(code=code, message=message)


class WSServerMode:
    """同一 aiohttp 应用承载 PWA 静态路由与 GET /ws 升级。"""

    def __init__(
        self,
        *,
        dispatch: Callable[..., None],
        authenticator: RemoteAuthenticator,
        fanout: EventFanout,
        static_root: Path | None,
        port: int,
        on_disconnect: Callable[[str], None],
        host: str = "127.0.0.1",
    ) -> None:
        self.dispatch = dispatch
        self.authenticator = authenticator
        self.fanout = fanout
        self.static_root = static_root
        self.port = port
        # 连接断开回调，按连接 key 清理手机语音会话与控制租约。
        self.on_disconnect = on_disconnect
        # 默认只监听回环；局域网直连时传入 0.0.0.0。
        self._host = host
        self._runner: web.AppRunner | None = None
        self._connections: set[_RemoteConnection] = set()

    def _build_app(self) -> web.Application:
        app = web.Application()
        # /ws 必须在静态前缀路由之前注册，避免被静态 / 路由截获。
        app.router.add_get("/ws", self._handle_ws)
        add_static_routes(app, self.static_root)
        return app

    async def start(self) -> None:
        runner = web.AppRunner(self._build_app())
        await runner.setup()
        try:
            await web.TCPSite(runner, self._host, self.port).start()
        except BaseException:
            await runner.cleanup()
            raise
        self._runner = runner

    async def stop(self) -> None:
        for conn in set(self._connections):
            await conn.close()
        self._connections.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def close_connections_for_device(self, device_key: str, device_name: str) -> int:
        """断开以该令牌键鉴权的已建立连接，返回断开数。必须在事件循环线程内调用。"""
        matched = [conn for conn in self._connections if conn.device_key == device_key]
        for conn in matched:
            self._disconnect_unauthorized(conn, b"token revoked")
        if matched:
            logger.info(
                "设备已撤销，断开 %d 条已建立连接 device=%r", len(matched), device_name
            )
        return len(matched)

    def _disconnect_unauthorized(self, conn: _RemoteConnection, message: bytes) -> None:
        """令牌失效的连接：同步退订（事件扇出立即停止），再调度 4401 关闭。"""
        self._connections.discard(conn)
        conn.detach()
        asyncio.get_running_loop().create_task(conn.close(code=4401, message=message))

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        # 服务端每 30 秒 ping 一次，客户端自动回 pong；对端断网不回 RST 的
        # 半开连接在两个心跳周期内暴露并按断连流程清理。
        ws = web.WebSocketResponse(heartbeat=30.0, receive_timeout=75.0)
        await ws.prepare(request)
        conn = _RemoteConnection(self.fanout, ws)
        self._connections.add(conn)
        try:
            async for raw in ws:
                if raw.type == WSMsgType.TEXT:
                    self._handle_frame(conn, raw.data)
                elif raw.type == WSMsgType.ERROR:
                    logger.warning("远程 WS 连接出错：%s", ws.exception())
                    break
        finally:
            self._connections.discard(conn)
            await conn.close()
            self.on_disconnect(conn.key)
        return ws

    def _handle_frame(self, conn: _RemoteConnection, text: str) -> None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            conn.send(protocol_error("invalid_json", f"JSON 解析失败：{exc.msg}"))
            return
        if not isinstance(payload, dict):
            conn.send(protocol_error("invalid_message", "协议消息必须是 JSON 对象"))
            return
        request_id = _frame_id(payload)
        method = payload.get("method")
        if not isinstance(method, str):
            conn.send(
                protocol_error(
                    "invalid_message", "request.method 必须是字符串", request_id=request_id
                )
            )
            return
        auth = payload.get("auth")
        if auth is None:
            token = None
        elif isinstance(auth, dict) and isinstance(auth.get("token"), str):
            token = auth["token"]
        else:
            conn.send(
                protocol_error(
                    "invalid_message",
                    "auth 必须是包含字符串 token 的对象",
                    request_id=request_id,
                )
            )
            return

        decision = self.authenticator.authorize(token, method)
        if not decision.allowed:
            err_code = (
                "forbidden_scope"
                if decision.reason == "forbidden_scope"
                else "unauthorized"
            )
            conn.send(response_error(request_id, err_code, decision.reason))
            logger.warning("远程鉴权拒绝 method=%r reason=%r", method, decision.reason)
            if conn.device_key is not None and err_code == "unauthorized":
                # 已鉴权连接的令牌失效（过期、撤销）：退订并断开。
                self._disconnect_unauthorized(conn, decision.reason.encode("utf-8"))
            return

        # 连接首次业务鉴权后固定设备身份，后续请求不能切换令牌，
        # 否则撤销定位与实际请求身份会分叉。
        if method not in UNAUTHENTICATED_METHODS:
            if conn.device_key is None:
                conn.device_key = decision.device_key
                conn.subscribe()
                logger.info("远程连接鉴权完成 device=%r", decision.device_name)
            elif decision.device_key != conn.device_key:
                conn.send(
                    response_error(
                        request_id,
                        "connection_identity_mismatch",
                        "已鉴权连接不能切换 token，请重新连接",
                    )
                )
                return

        self.dispatch(
            text,
            conn.send,
            origin="remote",
            connection_key=conn.key,
            device_key=decision.device_key,
            device_name=decision.device_name,
        )