from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class TransportClosed(RuntimeError):
    pass


class JsonLineConnection(Protocol):
    async def read_line(self) -> bytes: ...

    async def write_line(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class SubprocessJsonLineConnection:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process

    @classmethod
    async def create(cls, executable: str) -> "SubprocessJsonLineConnection":
        process = await asyncio.create_subprocess_exec(
            executable,
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return cls(process)

    async def read_line(self) -> bytes:
        if self.process.stdout is None:
            return b""
        return await self.process.stdout.readline()

    async def write_line(self, data: bytes) -> None:
        if self.process.stdin is None:
            raise TransportClosed("app-server stdin is unavailable")
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self.process.returncode is None:
            self.process.terminate()
        await self.process.wait()


ConnectionFactory = Callable[[], Awaitable[JsonLineConnection]]


class JsonlProcessTransport:
    """One-reader JSONL RPC transport with request correlation."""

    def __init__(
        self,
        executable: str,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.executable = executable
        self.connection_factory = connection_factory
        self._connection: JsonLineConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any] | BaseException] = asyncio.Queue()
        self._next_id = 1

    @property
    def is_running(self) -> bool:
        return self._reader_task is not None and not self._reader_task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        if self.connection_factory is not None:
            self._connection = await self.connection_factory()
        else:
            self._connection = await SubprocessJsonLineConnection.create(self.executable)
        self._reader_task = asyncio.create_task(self._read_loop(), name="codex-jsonl-reader")

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_running or self._connection is None:
            await self.start()
        assert self._connection is not None
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = {"id": request_id, "method": method, "params": params or {}}
        encoded = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            await self._connection.write_line(encoded)
        except BaseException:
            self._pending.pop(request_id, None)
            raise
        return await future

    async def next_notification(self) -> dict[str, Any]:
        item = await self._notifications.get()
        if isinstance(item, BaseException):
            raise item
        return item

    async def _read_loop(self) -> None:
        assert self._connection is not None
        failure: BaseException = TransportClosed("Codex app-server exited")
        try:
            while True:
                line = await self._connection.read_line()
                if not line:
                    raise failure
                message = json.loads(line.decode("utf-8"))
                if "id" in message:
                    request_id = int(message["id"])
                    future = self._pending.pop(request_id, None)
                    if future is None:
                        continue
                    if "error" in message:
                        future.set_exception(RuntimeError(str(message["error"])))
                    else:
                        future.set_result(message.get("result", {}))
                elif "method" in message:
                    await self._notifications.put(message)
        except asyncio.CancelledError:
            return
        except BaseException as exc:
            failure = exc
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(exc)
            self._pending.clear()
            await self._notifications.put(exc)

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
            self._reader_task = None
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

