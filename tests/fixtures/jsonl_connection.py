from __future__ import annotations

import asyncio
import json
from typing import Any


class QueueJsonLineConnection:
    """内存中的 JSONL 子进程连接，实现 transport 的 JsonLineConnection 协议。

    client_to_server 收集客户端写出的行；server_to_client 是子进程 stdout，
    放入 b"" 表示 EOF（子进程退出）。
    """

    def __init__(
        self,
        *,
        stderr_tail: str = "",
        exit_description: str = "JSONL subprocess exited (exit code 0)",
    ) -> None:
        self.client_to_server: asyncio.Queue[bytes] = asyncio.Queue()
        self.server_to_client: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False
        self._stderr_tail = stderr_tail
        self._exit_description = exit_description

    async def read_line(self) -> bytes:
        return await self.server_to_client.get()

    async def write_line(self, data: bytes) -> None:
        await self.client_to_server.put(data)

    async def close(self) -> None:
        self.closed = True
        await self.server_to_client.put(b"")

    async def exit_description(self) -> str:
        return self._exit_description

    def stderr_tail(self, limit: int = 6) -> str:
        return self._stderr_tail

    async def receive(self) -> dict[str, Any]:
        """取出客户端写出的下一条 JSON-RPC 消息。"""
        return json.loads((await self.client_to_server.get()).decode("utf-8"))

    async def send(self, message: dict[str, Any]) -> None:
        """按 JSON-RPC 2.0 行格式写出一条子进程消息。"""
        line = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False)
        await self.server_to_client.put(line.encode("utf-8") + b"\n")

