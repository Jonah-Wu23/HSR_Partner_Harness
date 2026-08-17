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

# app-server 的 JSONL 单条通知可能携带完整工具输出；Python asyncio 默认
# 64 KiB 行上限会在 readline() 处直接截断协议。这里调整协议读取上限，
# 不捕获或改写读取异常，让真实传输错误继续暴露。
_SUBPROCESS_STREAM_LIMIT = 16 * 1024 * 1024


class TransportClosed(RuntimeError):
    pass


class JsonLineConnection(Protocol):
    async def read_line(self) -> bytes: ...

    async def write_line(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class SubprocessJsonLineConnection:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._stderr_task: asyncio.Task[None] | None = None

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
        stderr 由独立任务持续消费，避免管道缓冲打满阻塞子进程；最近的
        stderr 行会附在退出异常中，便于定位 app-server 启动失败。
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
            connection._drain_stderr(), name="codex-stderr-reader"
        )
        return connection

    async def _drain_stderr(self) -> None:
        if self.process.stderr is None:
            return
        while True:
            line = await self.process.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self._stderr_tail.append(text[-500:])
                logger.debug("Codex app-server stderr: %s", text)

    async def exit_description(self) -> str:
        """返回子进程退出码和最近的 stderr，避免只暴露泛化 EOF。"""
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
        detail = f"Codex app-server exited (exit code {self.process.returncode})"
        if self._stderr_tail:
            stderr = " | ".join(self._stderr_tail)
            detail = f"{detail}: {stderr[-3000:]}"
        return detail

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

    async def _terminate_tree(self) -> None:
        """强制结束整个子进程树。

        Windows 上 .cmd/.bat shim 只作为 cmd.exe 启动的包装，直接 kill 可能
        只结束 cmd 而留下真实 app-server；用 taskkill /T 覆盖整棵进程树。
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
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(self.process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            # 普通 terminate 无效时进入强制结束；真实错误保留在日志里。
            logger.warning(
                "Codex app-server 未在 2s 内退出，强制结束进程树 (pid=%s)",
                self.process.pid,
            )
            await self._terminate_tree()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.error(
                    "Codex app-server 强制结束后仍未退出 (pid=%s)", self.process.pid
                )
        if self._stderr_task is not None:
            await asyncio.gather(self._stderr_task, return_exceptions=True)


ConnectionFactory = Callable[[], Awaitable[JsonLineConnection]]


def _session_route_key(message: dict[str, Any]) -> str | None:
    """V0.3.2 M3：返回按 session 路由的键。

    只对携带 ``params.sessionId`` 的 ACP 会话事件生效（``session/update``、
    ``session/request_permission`` 等）；其他通知（Codex item/* 与无
    session 标识的旧形状）继续走通用队列，保持 Codex 适配器行为不变。
    """
    method = message.get("method")
    if not isinstance(method, str) or not method.startswith("session/"):
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    session_id = params.get("sessionId") or params.get("session_id")
    if session_id is None:
        return None
    return str(session_id)


class SessionSubscription:
    """单个 ACP session 的通知订阅器（V0.3.2 M3）。

    ``next()`` 只返回路由到该 session 的事件；transport 断开时收到同一个
    真实异常。订阅器由 :meth:`JsonlProcessTransport.subscribe_session`
    创建，``close()`` 归还路由槽位。
    """

    def __init__(self, transport: "JsonlProcessTransport", session_id: str) -> None:
        self._transport = transport
        self.session_id = session_id
        self._queue: asyncio.Queue[dict[str, Any] | BaseException] = asyncio.Queue()
        self._closed = False

    async def next(self) -> dict[str, Any]:
        if self._closed and self._queue.empty():
            raise TransportClosed(
                f"session subscription for {self.session_id} is closed"
            )
        item = await self._queue.get()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport._release_subscription(self)

    def _deliver(self, item: dict[str, Any] | BaseException) -> None:
        self._queue.put_nowait(item)


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
        self._pending_generation: dict[int, int] = {}
        self._notifications: asyncio.Queue[dict[str, Any] | BaseException] = asyncio.Queue()
        self._generation = 0
        self._next_id = 1
        # V0.3.2 M3：按 session 路由的 ACP 会话事件订阅器。一个 session
        # 同时只允许一个活动订阅器（与 Reasonix 同 session 单 prompt 一致）。
        self._session_subscriptions: dict[str, SessionSubscription] = {}
        # 未路由/未知 session 的事件保留在诊断缓冲中，绝不投给任意任务。
        self._session_diagnostics: deque[str] = deque(maxlen=50)
        self._failure_broadcast = False
        # 坏行容错计数（O1.3）：读循环跳过无法解析的行，不中断
        self.bad_line_count = 0

    @property
    def is_running(self) -> bool:
        return self._reader_task is not None and not self._reader_task.done()

    @property
    def generation(self) -> int:
        """连接代次。重连后递增，旧 reader 只归属旧代次。"""
        return self._generation

    async def start(self) -> None:
        if self.is_running:
            return
        # 读循环已经结束时，先收掉旧管道，再创建新的 app-server 连接。
        if self._connection is not None:
            await self._close_connection()
        self._generation += 1
        # M1.3：每次重连使用新的通知队列；旧 reader 的异常只进旧队列。
        self._notifications = asyncio.Queue()
        self._failure_broadcast = False
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
        self._pending_generation[request_id] = self._generation
        message = {"id": request_id, "method": method, "params": params or {}}
        encoded = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            await self._connection.write_line(encoded)
        except BaseException as exc:
            self._pending.pop(request_id, None)
            self._pending_generation.pop(request_id, None)
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
            self._pending_generation.pop(request_id, None)
            raise

    async def next_notification(self) -> dict[str, Any]:
        item = await self._notifications.get()
        if isinstance(item, BaseException):
            raise item
        return item

    def subscribe_session(self, session_id: str) -> SessionSubscription:
        """V0.3.2 M3：订阅指定 ACP session 的通知。

        一个 session 同时只允许一个活动订阅器——与 Reasonix 的
        ``session already has an active prompt`` 限制一致；重复订阅是路由
        缺陷，直接抛错暴露。
        """
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

    def _route_session_message(self, message: dict[str, Any]) -> bool:
        """按 sessionId 投递会话事件；返回是否已被 session 路由消费。"""
        session_id = _session_route_key(message)
        if session_id is None:
            return False
        subscription = self._session_subscriptions.get(session_id)
        if subscription is not None:
            subscription._deliver(message)
            return True
        # 未知 session：保留可观测诊断，绝不悄悄塞给任意任务/通用队列。
        method = message.get("method")
        self._session_diagnostics.append(
            f"unrouted session event: method={method} sessionId={session_id}"
        )
        logger.warning(
            "session notification without active subscriber dropped to diagnostics: "
            "method=%s sessionId=%s",
            method,
            session_id,
        )
        return True

    def _broadcast_failure_to_subscriptions(self, exc: BaseException) -> None:
        """transport 断开：向所有活动订阅器广播同一个真实异常。"""
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
        generation = self._generation
        notifications = self._notifications
        failure: BaseException = TransportClosed("Codex app-server exited")
        try:
            while True:
                line = await self._connection.read_line()
                if not line:
                    describe_exit = getattr(self._connection, "exit_description", None)
                    if callable(describe_exit):
                        raise TransportClosed(await describe_exit())
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
                    # O3.1：服务端发起的请求（如 item/commandExecution/requestApproval
                    # 或 session/request_permission）带 JSON-RPC id 与方法名，
                    # 与通知同队列消费，由调用方（run_turn 循环）经 respond()
                    # 回复；不能当作客户端请求的响应。V0.3.2 M3：携带
                    # sessionId 的会话请求先走 session 路由。
                    if not self._route_session_message(message):
                        await notifications.put(message)
                elif "id" in message:
                    request_id = int(message["id"])
                    if self._pending_generation.get(request_id) != generation:
                        continue
                    self._pending_generation.pop(request_id, None)
                    future = self._pending.pop(request_id, None)
                    if future is None:
                        continue
                    if "error" in message:
                        future.set_exception(RuntimeError(str(message["error"])))
                    else:
                        future.set_result(message.get("result", {}))
                elif "method" in message:
                    if not self._route_session_message(message):
                        await notifications.put(message)
        except asyncio.CancelledError:
            return
        except BaseException as exc:
            failure = exc
            for request_id, future in tuple(self._pending.items()):
                if self._pending_generation.get(request_id) != generation:
                    continue
                self._pending_generation.pop(request_id, None)
                self._pending.pop(request_id, None)
                if not future.done():
                    future.set_exception(exc)
            # V0.3.2 M3：断开对全部 session 订阅器广播同一真实异常。
            self._broadcast_failure_to_subscriptions(exc)
            # 旧 reader 的异常只放进自己代次的通知队列，不影响新队列。
            await notifications.put(exc)

    async def _close_connection(self) -> None:
        # V0.3.2 M3：主动关闭也要让所有 session 订阅器收到真实异常，
        # 不能让 next() 永久悬挂。
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
