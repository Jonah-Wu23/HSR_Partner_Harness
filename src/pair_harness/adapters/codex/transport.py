from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# 单条 JSONL 通知可能携带完整工具输出，asyncio 默认的 64 KiB 行上限会让
# readline() 截断协议，这里放宽读取上限。
_SUBPROCESS_STREAM_LIMIT = 16 * 1024 * 1024


class TransportClosed(RuntimeError):
    pass


class JsonRpcError(RuntimeError):
    """服务端对请求返回的 JSON-RPC error 对象，保留 code、message、data 原值。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        text = f"JSON-RPC error {code}: {message}"
        if data is not None:
            text = f"{text} (data: {json.dumps(data, ensure_ascii=False)})"
        super().__init__(text)


class JsonlProtocolError(RuntimeError):
    """子进程输出了无法解析的 JSONL 行，连接上的协议状态不再可信。"""


class JsonLineConnection(Protocol):
    async def read_line(self) -> bytes: ...

    async def write_line(self, data: bytes) -> None: ...

    async def close(self) -> None: ...

    async def exit_description(self) -> str: ...

    def stderr_tail(self, limit: int = 6) -> str: ...


class SubprocessJsonLineConnection:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._stderr_task: asyncio.Task[None] | None = None

    @staticmethod
    def _resolve_executable(executable: str) -> str:
        """按 PATHEXT 把裸命令名解析为可执行文件路径。

        Windows 上 npm 全局安装的命令是 .cmd 批处理 shim，直接交给
        create_subprocess_exec 会 FileNotFoundError。
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
        """启动子进程，args 追加在可执行文件之后，env 覆盖进程环境变量。

        stderr 由独立任务持续消费，避免管道缓冲打满阻塞子进程；最近的
        stderr 行附在退出说明里，便于定位启动失败。
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
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
            limit=_SUBPROCESS_STREAM_LIMIT,
        )
        connection = cls(process)
        connection._stderr_task = asyncio.create_task(
            connection._drain_stderr(), name="jsonl-stderr-reader"
        )
        return connection

    async def _drain_stderr(self) -> None:
        while True:
            line = await self.process.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self._stderr_tail.append(text[-500:])
                logger.info("JSONL subprocess stderr: %s", text)

    def stderr_tail(self, limit: int = 6) -> str:
        """最近几行 stderr，空闲超时等失败回执用它携带底层原因。"""
        return " | ".join(list(self._stderr_tail)[-limit:])[-1500:]

    async def exit_description(self) -> str:
        """子进程退出码和最近的 stderr。"""
        if self.process.returncode is None:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
        if self._stderr_task is not None:
            try:
                await asyncio.wait_for(self._stderr_task, timeout=0.5)
            except asyncio.TimeoutError:
                self._stderr_task.cancel()
                await asyncio.gather(self._stderr_task, return_exceptions=True)
        detail = f"JSONL subprocess exited (exit code {self.process.returncode})"
        if self._stderr_tail:
            stderr = " | ".join(self._stderr_tail)
            detail = f"{detail}: {stderr[-3000:]}"
        return detail

    async def read_line(self) -> bytes:
        return await self.process.stdout.readline()

    async def write_line(self, data: bytes) -> None:
        try:
            self.process.stdin.write(data)
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ValueError) as exc:
            raise TransportClosed("JSONL subprocess connection lost") from exc

    async def _terminate_tree(self) -> None:
        """强制结束整个子进程树。

        Windows 上 .cmd/.bat shim 经 cmd.exe 启动，直接 kill 可能只结束 cmd
        而留下真实子进程，因此用 taskkill /T 结束整棵进程树。
        """
        if os.name == "nt":
            kill = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(self.process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await kill.wait()
        else:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass

    async def close(self) -> None:
        self.process.stdin.close()
        if self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(self.process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning(
                "JSONL 子进程未在 2s 内退出，强制结束进程树 (pid=%s)",
                self.process.pid,
            )
            await self._terminate_tree()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.error(
                    "JSONL 子进程强制结束后仍未退出 (pid=%s)", self.process.pid
                )
        if self._stderr_task is not None:
            await asyncio.gather(self._stderr_task, return_exceptions=True)


ConnectionFactory = Callable[[], Awaitable[JsonLineConnection]]


def _session_route_key(message: dict[str, Any]) -> str | None:
    """ACP 会话消息（session/update、session/request_permission 等）的 sessionId。"""
    if not message["method"].startswith("session/"):
        return None
    return message.get("params", {}).get("sessionId")


class SessionSubscription:
    """单个 ACP session 的消息订阅器。

    读循环按 stdout 顺序把消息同步放进队列；transport 断开时所有订阅器收到
    同一个异常。close() 归还路由槽位。
    """

    def __init__(self, transport: "JsonlProcessTransport", session_id: str) -> None:
        self._transport = transport
        self.session_id = session_id
        self._queue: asyncio.Queue[dict[str, Any] | BaseException] = asyncio.Queue()

    async def next(self) -> dict[str, Any]:
        item = await self._queue.get()
        if isinstance(item, BaseException):
            raise item
        return item

    def next_nowait(self) -> dict[str, Any]:
        """取出已到达的下一条消息；队列为空时抛 asyncio.QueueEmpty。"""
        item = self._queue.get_nowait()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self._transport._release_subscription(self)

    def _deliver(self, item: dict[str, Any] | BaseException) -> None:
        self._queue.put_nowait(item)


class JsonlProcessTransport:
    """单读循环的 JSONL JSON-RPC 传输，按 id 关联请求与响应，按 sessionId 投递会话消息。"""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        request_timeout: float | None = None,
    ) -> None:
        self.connection_factory = connection_factory
        self.request_timeout = request_timeout
        self._connection: JsonLineConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._generation = 0
        self._next_id = 1
        # 一个 session 同时只有一个活动订阅器，与 Reasonix 同一 session 只跑一个 prompt 一致。
        self._session_subscriptions: dict[str, SessionSubscription] = {}
        self._failure_broadcast = False

    @property
    def is_running(self) -> bool:
        return self._reader_task is not None and not self._reader_task.done()

    @property
    def generation(self) -> int:
        """连接代次，每次建立新连接后递增，引擎据此判断是否需要重新 initialize。"""
        return self._generation

    async def start(self) -> None:
        if self.is_running:
            return
        # 读循环已经结束时，先收掉旧管道，再创建新连接。
        if self._connection is not None:
            await self._close_connection()
        self._generation += 1
        self._failure_broadcast = False
        self._connection = await self.connection_factory()
        self._reader_task = asyncio.create_task(self._read_loop(), name="jsonl-reader")

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not self.is_running:
            await self.start()
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write_message(
                {"id": request_id, "method": method, "params": params or {}}
            )
            effective_timeout = self.request_timeout if timeout is None else timeout
            return await asyncio.wait_for(future, effective_timeout)
        finally:
            # 写入失败、超时或取消时移除挂起项，迟到的响应由读循环丢弃。
            self._pending.pop(request_id, None)

    def stderr_tail(self, limit: int = 6) -> str:
        """当前连接最近的 stderr；尚未建立连接时为空。"""
        if self._connection is None:
            return ""
        return self._connection.stderr_tail(limit)

    def subscribe_session(self, session_id: str) -> SessionSubscription:
        """订阅指定 ACP session 的消息；同一 session 重复订阅是路由缺陷，直接抛错。"""
        if session_id in self._session_subscriptions:
            raise RuntimeError(
                f"session {session_id} already has an active notification subscriber"
            )
        subscription = SessionSubscription(self, session_id)
        self._session_subscriptions[session_id] = subscription
        return subscription

    def _release_subscription(self, subscription: SessionSubscription) -> None:
        current = self._session_subscriptions.get(subscription.session_id)
        if current is subscription:
            self._session_subscriptions.pop(subscription.session_id, None)

    def _route_session_message(self, message: dict[str, Any]) -> None:
        """把通知或服务端请求按 sessionId 交给订阅器；没有订阅器的消息记日志后丢弃。"""
        session_id = _session_route_key(message)
        subscription = self._session_subscriptions.get(session_id) if session_id else None
        if subscription is not None:
            subscription._deliver(message)
            return
        logger.warning(
            "JSONL message without active session subscriber dropped: method=%s sessionId=%s",
            message["method"],
            session_id,
        )

    def _broadcast_failure_to_subscriptions(self, exc: BaseException) -> None:
        if self._failure_broadcast:
            return
        self._failure_broadcast = True
        for subscription in tuple(self._session_subscriptions.values()):
            subscription._deliver(exc)

    async def _write_message(self, message: dict[str, Any]) -> None:
        if self._connection is None:
            raise TransportClosed("transport is not started")
        encoded = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            await self._connection.write_line(encoded)
        except TransportClosed:
            await self._close_connection()
            raise

    async def respond(self, request_id: int, result: dict[str, Any]) -> None:
        """回复服务端发起的请求，例如 session/request_permission 的裁决。"""
        await self._write_message({"id": request_id, "result": result})

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """发送 JSON-RPC notification（无 id，服务端不回复），例如 ACP 的 session/cancel。"""
        await self._write_message({"method": method, "params": params or {}})

    async def _read_loop(self) -> None:
        connection = self._connection
        try:
            while True:
                line = await connection.read_line()
                if not line:
                    raise TransportClosed(await connection.exit_description())
                # 坏行可能就是某个请求的响应，跳过会让该请求挂到超时，因此直接结束读循环。
                try:
                    message = json.loads(line)
                except ValueError as exc:
                    raise JsonlProtocolError(
                        f"unparseable JSONL line from subprocess: {line[:500]!r}"
                    ) from exc
                if "method" in message:
                    # 通知，或带 id 的服务端请求（由调用方经 respond() 回复）。
                    self._route_session_message(message)
                    continue
                # 已超时或取消的请求不在 _pending 中，迟到的响应直接丢弃。
                future = self._pending.pop(message["id"], None)
                if future is None:
                    continue
                if "error" in message:
                    error = message["error"]
                    future.set_exception(
                        JsonRpcError(error["code"], error["message"], error.get("data"))
                    )
                else:
                    future.set_result(message["result"])
        except asyncio.CancelledError:
            return
        except BaseException as exc:
            pending = tuple(self._pending.values())
            self._pending.clear()
            for future in pending:
                future.set_exception(exc)
            self._broadcast_failure_to_subscriptions(exc)

    async def _close_connection(self) -> None:
        # 主动关闭时订阅器同样收到异常，避免 next() 永久挂起。
        self._broadcast_failure_to_subscriptions(TransportClosed("transport closed"))
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
