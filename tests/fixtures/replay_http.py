# 本机 HTTP 回放服务：按真实接口的 JSON 响应形状应答 POST 请求，并记录收到的请求。
# 对话服务探测（Chat Completions）与 DashScope 音色定制客户端把服务地址指向这里，
# 请求经生产代码自己的 httpx 与 urllib 传输发出。

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

_PROXY_VARIABLES = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
)


@dataclass(frozen=True)
class RecordedRequest:
    path: str
    headers: dict[str, str]
    body: dict[str, Any]


class ReplayHttpServer:
    """127.0.0.1 上的 HTTP 端点：按路径回放登记的响应，未登记的路径返回 404。"""

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self._replies: dict[str, tuple[int, dict[str, Any]] | None] = {}
        self._holds: dict[str, asyncio.Event] = {}
        # 音色复刻请求体携带 base64 参考音频，放宽默认的 1 MiB 上限。
        app = web.Application(client_max_size=32 * 1024 * 1024)
        app.router.add_post("/{tail:.*}", self._handle)
        self._server = TestServer(app, host="127.0.0.1")

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.port}"

    def reply(self, path: str, status: int, payload: dict[str, Any]) -> None:
        self._replies[path] = (status, payload)

    def disconnect(self, path: str) -> None:
        """该路径收到请求后不返回响应，直接断开连接。"""
        self._replies[path] = None

    def hold(self, path: str) -> asyncio.Event:
        """该路径的请求记录后停在服务端，直到返回的 Event 被 set 才应答。"""
        gate = asyncio.Event()
        self._holds[path] = gate
        return gate

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        body = json.loads(await request.read())
        self.requests.append(
            RecordedRequest(path=request.path, headers=dict(request.headers), body=body)
        )
        if request.path in self._holds:
            await self._holds[request.path].wait()
        if request.path not in self._replies:
            return web.json_response(
                {"error": {"message": f"未登记的路径：{request.path}"}}, status=404
            )
        reply = self._replies[request.path]
        if reply is None:
            request.transport.close()
            return web.Response()
        status, payload = reply
        return web.json_response(payload, status=status)

    async def start(self) -> None:
        await self._server.start_server()

    async def close(self) -> None:
        for gate in self._holds.values():
            gate.set()
        await self._server.close()


@pytest.fixture
async def replay_http(monkeypatch: pytest.MonkeyPatch):
    # httpx 读环境代理，urllib 在 Windows 上没有代理变量时还会读系统代理；
    # 回环地址一律直连。
    for name in _PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    server = ReplayHttpServer()
    await server.start()
    yield server
    await server.close()
