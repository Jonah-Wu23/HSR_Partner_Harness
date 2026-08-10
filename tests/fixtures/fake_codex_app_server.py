from __future__ import annotations

import asyncio
import json
from typing import Any


class QueueJsonLineConnection:
    def __init__(self) -> None:
        self.client_to_server: asyncio.Queue[bytes] = asyncio.Queue()
        self.server_to_client: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False

    async def read_line(self) -> bytes:
        return await self.server_to_client.get()

    async def write_line(self, data: bytes) -> None:
        await self.client_to_server.put(data)

    async def close(self) -> None:
        self.closed = True
        await self.server_to_client.put(b"")

    async def receive_request(self) -> dict[str, Any]:
        return json.loads((await self.client_to_server.get()).decode("utf-8"))

    async def send(self, message: dict[str, Any]) -> None:
        await self.server_to_client.put(
            json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        )


class FakeCodexAppServer:
    def __init__(self, connection: QueueJsonLineConnection) -> None:
        self.connection = connection
        self.requests: list[dict[str, Any]] = []

    async def serve_request(self, result: dict[str, Any]) -> dict[str, Any]:
        request = await self.connection.receive_request()
        self.requests.append(request)
        await self.connection.send({"id": request["id"], "result": result})
        return request

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self.connection.send({"method": method, "params": params})

