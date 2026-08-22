from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from aiohttp import WSMsgType, web

from .event_fanout import EventFanout
from .protocol import encode_message, protocol_error, response_error
from .pwa_static import add_static_routes

logger = logging.getLogger(__name__)

# 把 response / protocol_error 写回发起连接（同步入队，由连接自己的写任务下发）。
ReplySink = Callable[[dict], None]

# 不需要 token 即可调用的命令白名单（配对握手）。批 3 由主控同步进 commands.py。
UNAUTHENTICATED_METHODS: frozenset[str] = frozenset({"remote.pair"})


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    reason: str = ""         # 拒绝原因，进审计日志
    device_name: str = ""    # 允许时的设备名


class RemoteAuthenticator(Protocol):
    def authorize(self, token: str | None, method: str) -> AuthDecision: ...


def _extract_frame_id(payload: Any) -> str | None:
    """从已解析的帧里提取请求 id；解析失败或非对象时返回 None。"""
    if not isinstance(payload, dict):
        return None
    candidate = payload.get("id")
    if isinstance(candidate, str) and candidate:
        return candidate
    return None

class _RemoteConnection:
    """管理一条远端 WS 连接：上行队列 + 扇出订阅 + 下行写任务。"""

    def __init__(self, fanout: EventFanout, ws: Any) -> None:
        self._fanout = fanout
        self._ws = ws
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscription: Any = None
        self._closed = False
        # 该连接是否已完成一次带 token 的鉴权并订阅 fanout
        self.authenticated = False
        # 完成鉴权后该连接使用的 token 原文；撤销联动按它定位连接（V0.3.4 缺陷 7）
        self.token: str | None = None
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def _writer_loop(self) -> None:
        """消费下行队列并把每个 envelope 编码成 WS 文本帧下发。"""
        try:
            while True:
                envelope = await self._queue.get()
                try:
                    await self._ws.send_str(encode_message(envelope))
                except Exception:  # noqa: BLE001 - 对端断开只隔离本条连接
                    self._teardown()
                    return
        except asyncio.CancelledError:
            return

    def send(self, envelope: dict) -> None:
        """同步入队（作为 dispatch reply_sink 与 fanout 订阅写回调共用）。"""
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
        """同步退订并停写（幂等）：撤销联动时立即切断事件下发。"""
        self._teardown()

    async def close(self, *, code: int = 1000, message: bytes = b"") -> None:
        self._teardown()
        task = self._writer_task
        if not task.done() and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        # 真正断开底层 WS，让对端与 handler 循环感知连接已关闭。
        if self._ws is not None:
            try:
                await self._ws.close(code=code, message=message)
            except Exception:  # noqa: BLE001 - 对端已断开时关闭即无事可做
                pass


class WSServerMode:
    """WS 服务器模式：同一 aiohttp 应用承载 PWA 静态路由与 GET /ws 升级。

    构造参数冻结；dispatch 由批 3 主控接到 SidecarRouter.dispatch 扩展签名。
    """

    def __init__(
        self,
        *,
        dispatch: Callable[[str, ReplySink | None], None],
        authenticator: RemoteAuthenticator,
        fanout: EventFanout,
        static_root: Path | None,
        port: int,
    ) -> None:
        self.dispatch = dispatch
        self.authenticator = authenticator
        self.fanout = fanout
        self.static_root = static_root
        self.port = port
        # 手机经局域网/自组网接入，绑定全部接口；鉴权门保证未鉴权无法触发命令执行。
        self._host = "0.0.0.0"
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._connections: set[_RemoteConnection] = set()

    def _build_app(self) -> web.Application:
        app = web.Application()
        # /ws 必须在静态前缀路由之前注册，避免被静态 / 路由截获。
        app.router.add_get("/ws", self._handle_ws)
        add_static_routes(app, self.static_root)
        return app

    async def start(self) -> None:
        app = self._build_app()
        self._app = app
        runner = web.AppRunner(app)
        await runner.setup()
        self._runner = runner
        site = web.TCPSite(runner, self._host, self.port)
        await site.start()
        self._site = site

    async def stop(self) -> None:
        for conn in set(self._connections):
            await conn.close()
        self._connections.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._site = None

    def close_connections_for_token(self, token: str, device_name: str = "") -> int:
        """撤销联动：立即断开仍以该 token 鉴权的已建立连接，返回断开数。

        先同步退订（事件扇出立即停止），再调度真正的 WS 关闭；
        ``device_name`` 仅用于日志。必须在事件循环线程内调用。
        """
        matched = [conn for conn in self._connections if conn.token == token]
        for conn in matched:
            self._connections.discard(conn)
            conn.detach()
        if matched:
            logger.info(
                "撤销 token：断开 %d 条已建立连接 device=%r",
                len(matched),
                device_name,
            )
            loop = asyncio.get_running_loop()
            for conn in matched:
                loop.create_task(conn.close(code=4401, message=b"token revoked"))
        return len(matched)

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
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
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 单条连接异常不传播影响服务器与其他连接
            logger.exception("远程 WS 连接处理异常，隔离该连接")
        finally:
            self._connections.discard(conn)
            await conn.close()
        return ws

    def _handle_frame(self, conn: _RemoteConnection, text: str) -> None:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError) as exc:
            detail = getattr(exc, "msg", None) or str(exc)
            conn.send(protocol_error("invalid_json", f"JSON 解析失败：{detail}"))
            return
        if not isinstance(payload, dict):
            conn.send(
                protocol_error(
                    "invalid_message",
                    "协议消息必须是 JSON 对象",
                    request_id=_extract_frame_id(payload),
                )
            )
            return

        method = payload.get("method")
        auth = payload.get("auth")
        token = auth.get("token") if isinstance(auth, Mapping) else None

        try:
            decision = self.authenticator.authorize(token, method)
        except Exception:  # noqa: BLE001 - 鉴权实现异常按未授权拒绝，不让服务器崩溃
            logger.exception("远程鉴权接口异常，拒绝该请求")
            conn.send(
                response_error(_extract_frame_id(payload), "unauthorized", "鉴权不可用")
            )
            return

        if not decision.allowed:
            conn.send(
                response_error(_extract_frame_id(payload), "unauthorized", decision.reason)
            )
            logger.warning("远程鉴权拒绝 method=%r reason=%r", method, decision.reason)
            return

        # 仅在已鉴权（非未认证白名单）请求处把连接标记为可订阅，
        # remote.pair 握手阶段不下发业务/系统事件。
        if not conn.authenticated and method not in UNAUTHENTICATED_METHODS:
            conn.authenticated = True
            if isinstance(token, str):
                conn.token = token
            conn.subscribe()
            logger.info("远程连接鉴权完成 device=%r", decision.device_name)

        self.dispatch(text, conn.send)