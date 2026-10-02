# 本机回放 DashScope 推理 WebSocket 协议：客户端发 run-task、二进制音频或 continue-task、
# finish-task，服务端回 task-started、result-generated、二进制音频、task-finished 或
# task-failed。qwen_asr 与 qwen_tts 适配器经 ws_url（或 PAIR_HARNESS_DASHSCOPE_WS_URL）
# 连到这里，真实 dashscope SDK 全程参与。事件形状见 docs/design/dashscope/。

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import dashscope
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

WS_PATH = "/api-ws/v1/inference"


class DashScopeTask:
    """一条推理连接的服务端：记录客户端发来的指令与音频，按脚本回放服务端事件。"""

    def __init__(self, request: web.Request, ws: web.WebSocketResponse) -> None:
        self.headers = dict(request.headers)
        self.task_id = ""
        self.run_task: dict[str, Any] = {}
        self.actions: list[dict[str, Any]] = []
        self.audio: list[bytes] = []
        self.texts: list[str] = []
        self.closed = False
        self._ws = ws

    @property
    def finish_directives(self) -> list[str | None]:
        """每条 finish-task 的 payload.input.directive（取消合成时为 cancel）。"""
        return [
            action["payload"]["input"].get("directive")
            for action in self.actions
            if action["header"]["action"] == "finish-task"
        ]

    async def receive(self) -> bytes | dict[str, Any]:
        """读取客户端下一条消息；二进制帧是音频，文本帧是 JSON 指令。"""
        msg = await self._ws.receive()
        if msg.type == aiohttp.WSMsgType.BINARY:
            self.audio.append(msg.data)
            return msg.data
        if msg.type != aiohttp.WSMsgType.TEXT:
            self.closed = True
            raise ConnectionError(f"客户端已断开：{msg.type.name}")
        message = json.loads(msg.data)
        self.actions.append(message)
        header = message["header"]
        if header["action"] == "run-task":
            self.task_id = header["task_id"]
            self.run_task = message["payload"]
        elif header["action"] == "continue-task":
            self.texts.append(message["payload"]["input"]["text"])
        return message

    async def expect(self, action: str) -> dict[str, Any]:
        """读到下一条 JSON 指令并校验 action，其间的音频帧照常记录。"""
        while True:
            message = await self.receive()
            if isinstance(message, dict):
                assert message["header"]["action"] == action, message
                return message

    async def next_audio(self) -> bytes:
        message = await self.receive()
        assert isinstance(message, bytes), message
        return message

    async def _send(self, event: str, payload: dict[str, Any] | None, **header: Any) -> None:
        envelope: dict[str, Any] = {
            "header": {"task_id": self.task_id, "event": event, "attributes": {}, **header}
        }
        if payload is not None:
            envelope["payload"] = payload
        await self._ws.send_str(json.dumps(envelope, ensure_ascii=False))

    async def started(self) -> None:
        await self._send("task-started", {})

    async def sentence(self, begin_time: int, text: str, *, sentence_end: bool = False) -> None:
        """识别结果：同一 begin_time 的后续结果是同一句的更新。"""
        await self._send(
            "result-generated",
            {
                "output": {
                    "sentence": {
                        "begin_time": begin_time,
                        "end_time": begin_time + 500 if sentence_end else None,
                        "text": text,
                        "sentence_end": sentence_end,
                        "words": [],
                    }
                },
                "usage": None,
            },
        )

    async def audio_out(self, pcm: bytes) -> None:
        """合成结果：音频以二进制帧下发。"""
        await self._ws.send_bytes(pcm)

    async def finished(self, *, with_payload: bool = True) -> None:
        await self._send("task-finished", {"output": {}, "usage": None} if with_payload else None)

    async def failed(self, code: str, message: str) -> None:
        await self._send("task-failed", {}, error_code=code, error_message=message)


Script = Callable[[DashScopeTask], Awaitable[None]]


class DashScopeServer:
    """127.0.0.1 上的推理端点；每条连接按到达顺序取用一个已登记的脚本。"""

    def __init__(self) -> None:
        self.tasks: list[DashScopeTask] = []
        self.handshakes: list[dict[str, str]] = []
        self.errors: list[BaseException] = []
        self._scripts: list[Script] = []
        self._rejections: list[int] = []
        self._server = TestServer(self._build_app(), host="127.0.0.1")

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self._server.port}{WS_PATH}"

    def serve(self, script: Script) -> None:
        self._scripts.append(script)

    def reject_handshake(self, status: int) -> None:
        """下一次 WebSocket 握手直接返回该 HTTP 状态（例如 Key 无效的 401）。"""
        self._rejections.append(status)

    def _build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get(WS_PATH, self._handle)
        return app

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        self.handshakes.append(dict(request.headers))
        if self._rejections:
            return web.Response(status=self._rejections.pop(0))
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        task = DashScopeTask(request, ws)
        self.tasks.append(task)
        try:
            if not self._scripts:
                raise AssertionError("DashScope 连接没有登记回放脚本")
            await self._scripts.pop(0)(task)
            # 脚本结束后继续记录客户端消息，直到客户端关闭连接。
            while not ws.closed:
                await task.receive()
        except ConnectionError:
            pass
        except Exception as exc:  # noqa: BLE001 - 脚本断言失败在夹具收尾时抛给用例
            self.errors.append(exc)
        return ws

    async def start(self) -> None:
        await self._server.start_server()

    async def close(self) -> None:
        await self._server.close()


@pytest.fixture
async def dashscope_server(monkeypatch: pytest.MonkeyPatch):
    # 适配器会把 api_key 与 ws_url 写进 dashscope 的进程级配置，用例结束后还原。
    monkeypatch.setattr(dashscope, "api_key", dashscope.api_key)
    monkeypatch.setattr(dashscope, "base_websocket_api_url", dashscope.base_websocket_api_url)
    server = DashScopeServer()
    await server.start()
    yield server
    await server.close()
    if server.errors:
        raise server.errors[0]
