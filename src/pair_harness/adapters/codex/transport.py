from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TransportClosed(RuntimeError):
    pass


class JsonLineConnection(Protocol):
    async def read_line(self) -> bytes: ...

    async def write_line(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class SubprocessJsonLineConnection:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process

    @staticmethod
    def _resolve_executable(executable: str) -> str:
        """把裸命令名解析为可启动的可执行文件路径。

        B1 联调发现：npm 全局安装的 codex-cli 在 Windows 上是 ``codex.cmd``
        批处理 shim，``create_subprocess_exec("codex", ...)`` 直接
        FileNotFoundError；这里按 PATHEXT 解析出 .cmd/.bat 脚本路径。
        """
        if os.path.sep in executable or (os.path.altsep and os.path.altsep in executable):
            return executable
        if executable.lower().endswith((".exe", ".cmd", ".bat", ".ps1")):
            return executable
        found = shutil.which(executable)
        return found or executable

    @classmethod
    async def create(
        cls,
        executable: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> "SubprocessJsonLineConnection":
        """启动子进程。

        ``args`` 追加到可执行文件后（codex 用 ``app-server``，Reasonix
        ACP 用 ``acp``）；``env`` 为账号级环境覆盖（V0.2 M3：每个本地
        账号独立的 Codex 数据目录 CODEX_HOME，见 CodexAuthService）。
        stderr 无人消费会打满管道缓冲并阻塞子进程（O1.3）。MVP 阶段丢弃
        stderr；B1 联调需要诊断输出时再改为独立任务消费并接入日志。
        """
        resolved = cls._resolve_executable(executable)
        if resolved.lower().endswith((".cmd", ".bat")):
            # 批处理 shim 必须经 cmd.exe 启动，直接 CreateProcess 会 WinError 193
            cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", resolved, *(args or [])]
        else:
            cmd = [resolved, *(args or [])]
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=merged_env,
        )
        return cls(process)

    async def read_line(self) -> bytes:
        if self.process.stdout is None:
            return b""
        return await self.process.stdout.readline()

    async def write_line(self, data: bytes) -> None:
        if self.process.stdin is None:
            raise TransportClosed("app-server stdin is unavailable")
        try:
            self.process.stdin.write(data)
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ValueError) as exc:
            raise TransportClosed("Codex app-server connection lost") from exc

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
        request_timeout: float | None = None,
    ) -> None:
        self.executable = executable
        self.connection_factory = connection_factory
        self.request_timeout = request_timeout
        self._connection: JsonLineConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any] | BaseException] = asyncio.Queue()
        self._next_id = 1
        # 坏行容错计数（O1.3）：读循环跳过无法解析的行，不中断
        self.bad_line_count = 0

    @property
    def is_running(self) -> bool:
        return self._reader_task is not None and not self._reader_task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        # 读循环已经结束时，先收掉旧管道，再创建新的 app-server 连接。
        if self._connection is not None:
            await self._close_connection()
        if self.connection_factory is not None:
            self._connection = await self.connection_factory()
        else:
            self._connection = await SubprocessJsonLineConnection.create(self.executable)
        self._reader_task = asyncio.create_task(self._read_loop(), name="codex-jsonl-reader")

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
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
        except BaseException as exc:
            self._pending.pop(request_id, None)
            if isinstance(exc, (TransportClosed, ConnectionError, ValueError)):
                await self._close_connection()
                if not isinstance(exc, TransportClosed):
                    raise TransportClosed("Codex app-server connection lost") from exc
            raise
        effective_timeout = self.request_timeout if timeout is None else timeout
        if effective_timeout is None:
            return await future
        try:
            return await asyncio.wait_for(future, effective_timeout)
        except asyncio.TimeoutError:
            # 超时后移除挂起项，迟到的响应直接丢弃，避免污染后续请求
            self._pending.pop(request_id, None)
            raise

    async def next_notification(self) -> dict[str, Any]:
        item = await self._notifications.get()
        if isinstance(item, BaseException):
            raise item
        return item

    async def _write_message(self, message: dict[str, Any]) -> None:
        if self._connection is None:
            raise TransportClosed("transport is not started")
        encoded = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            await self._connection.write_line(encoded)
        except (TransportClosed, ConnectionError, ValueError) as exc:
            await self._close_connection()
            if not isinstance(exc, TransportClosed):
                raise TransportClosed("Codex app-server connection lost") from exc
            raise

    async def respond(self, request_id: int, result: dict[str, Any]) -> None:
        """O3.1：回复服务端发起的请求（如审批裁决结果）。

        请求带 JSON-RPC id 与方法名进入通知队列，调用方识别后在此回复。
        """
        await self._write_message({"id": request_id, "result": result})

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """发送 JSON-RPC notification（无 id，服务端不回复）。

        ACP 的 ``session/cancel`` 是 notification：按 request 发送会挂在
        pending 直到超时，服务端不会回响应。
        """
        await self._write_message({"method": method, "params": params or {}})

    async def _read_loop(self) -> None:
        assert self._connection is not None
        failure: BaseException = TransportClosed("Codex app-server exited")
        try:
            while True:
                line = await self._connection.read_line()
                if not line:
                    raise failure
                # 单行坏 JSON 只跳过并计数，不杀掉整个读循环（O1.3）；
                # 只有连接关闭（空行）才终止循环。
                try:
                    message = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self.bad_line_count += 1
                    logger.warning("忽略无法解析的 JSONL 行: %r", line[:200])
                    continue
                if "id" in message and "method" in message:
                    # O3.1：服务端发起的请求（如 item/commandExecution/requestApproval）
                    # 带 JSON-RPC id 与方法名，与通知同队列消费，由调用方
                    # （run_turn 循环）经 respond() 回复；不能当作客户端请求的响应。
                    await self._notifications.put(message)
                elif "id" in message:
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

    async def _close_connection(self) -> None:
        reader_task = self._reader_task
        self._reader_task = None
        if reader_task is not None and reader_task is not asyncio.current_task():
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
        connection = self._connection
        self._connection = None
        if connection is not None:
            await connection.close()

    async def close(self) -> None:
        await self._close_connection()
