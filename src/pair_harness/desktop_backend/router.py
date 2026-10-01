from __future__ import annotations

import asyncio
import logging
import sys
import threading
from dataclasses import replace
from typing import Any, Callable, TextIO

from .application_service import DesktopApplicationService, ServiceError
from .protocol import (
    ProtocolError,
    encode_message,
    parse_request,
    protocol_error,
    response_error,
    response_ok,
)

logger = logging.getLogger(__name__)


class JsonlWriter:
    """stdout 协议写入器；每次写入都是一行完整 JSON。

    整个 Sidecar 只允许创建一个实例，事件发射器与 Router 共用同一把锁。
    BrokenPipeError 视为传输已经关闭：原子标记 closed、通知主循环执行
    关闭流程，并把真实错误写入 stderr。``on_broken_pipe`` 在 run_stdin
    接上 Router 之前为 None。
    """

    def __init__(
        self,
        stream: TextIO,
        *,
        on_broken_pipe: Callable[[], None] | None = None,
    ) -> None:
        self.stream = stream
        self._lock = threading.Lock()
        self._closed = False
        self.on_broken_pipe = on_broken_pipe

    @property
    def closed(self) -> bool:
        return self._closed

    def write(self, message: dict[str, Any]) -> None:
        encoded = encode_message(message)
        with self._lock:
            if self._closed:
                return
            try:
                self.stream.write(encoded)
                self.stream.write("\n")
                self.stream.flush()
            except BrokenPipeError:
                self._closed = True
                print(
                    "Sidecar stdout 已关闭（BrokenPipeError），正在有序退出。",
                    file=sys.stderr,
                    flush=True,
                )
                if self.on_broken_pipe is not None:
                    self.on_broken_pipe()


class SidecarRouter:
    def __init__(self, service: DesktopApplicationService, writer: JsonlWriter) -> None:
        self.service = service
        self.writer = writer
        self.stop_requested = False
        self._stop_event = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    def dispatch(
        self,
        line: str,
        reply_sink: Callable[[dict[str, Any]], None] | None = None,
        *,
        origin: str = "desktop",
        connection_key: str | None = None,
        device_key: str | None = None,
        device_name: str | None = None,
    ) -> None:
        """提交一条请求，不等待它完成，以便后续请求可以继续进入。

        ``reply_sink`` 把 response 额外写回发起该请求的远程连接；stdout 始终
        收到同一份 response。来源、连接 key、设备身份与设备名由传输层注入
        DesktopCommand，请求参数里的同名字段不参与。
        """
        task = asyncio.create_task(
            self.handle_line(
                line,
                reply_sink,
                origin=origin,
                connection_key=connection_key,
                device_key=device_key,
                device_name=device_name,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_stopped(self) -> None:
        await self._stop_event.wait()

    def request_stop(self) -> None:
        """通知主循环退出（stdout 断开等传输级关闭路径）。"""
        self.stop_requested = True
        self._stop_event.set()

    async def wait_for_tasks(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def handle_line(
        self,
        line: str,
        reply_sink: Callable[[dict[str, Any]], None] | None = None,
        *,
        origin: str = "desktop",
        connection_key: str | None = None,
        device_key: str | None = None,
        device_name: str | None = None,
    ) -> None:
        def respond(message: dict[str, Any]) -> None:
            """response 写 stdout；远程发起方同时收到同一份。

            结果不可序列化时回执真实的编码失败，不让调用方等到 backend_timeout；
            回执只含字符串，不会再次编码失败。
            """
            try:
                self.writer.write(message)
            except ProtocolError as exc:
                logger.error(
                    "response 不可序列化，改为回执真实失败：%s", exc, exc_info=True
                )
                message = response_error(message.get("id"), exc.code, str(exc))
                self.writer.write(message)
            if reply_sink is not None:
                reply_sink(message)

        try:
            command = parse_request(line)
        except ProtocolError as exc:
            respond(protocol_error(exc.code, str(exc), request_id=exc.request_id))
            return

        command = replace(
            command,
            origin=origin,
            connection_key=connection_key,
            remote_device_key=device_key,
            remote_device_name=device_name or None,
        )

        try:
            result = await self.service.handle_command(command)
        except ServiceError as exc:
            respond(
                response_error(
                    command.request_id,
                    exc.code,
                    str(exc),
                    details=exc.details or None,
                )
            )
            return
        except Exception as exc:  # noqa: BLE001 - Sidecar 不能因单个请求崩溃
            logger.exception("desktop command failed: %s", command.method)
            respond(
                response_error(command.request_id, "internal_error", str(exc))
            )
            return

        respond(response_ok(command.request_id, result))
        if command.method == "app.shutdown":
            self.stop_requested = True
            self._stop_event.set()


async def run_stdin(
    service: DesktopApplicationService,
    *,
    writer: JsonlWriter,
    stdin: TextIO,
    router: SidecarRouter,
) -> None:
    """运行 Sidecar 主循环。

    Windows 控制台 stdin 不是 asyncio 原生异步流，使用线程读取单行，
    不阻塞事件循环中的模型、审批和语音任务。stdout 写入器与 Router 由
    __main__ 创建并传入，WS 服务器共用同一个 Router。
    """
    writer.on_broken_pipe = router.request_stop
    lines: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def read_lines() -> None:
        while True:
            line = stdin.readline()
            try:
                loop.call_soon_threadsafe(lines.put_nowait, line)
            except RuntimeError:
                # 主循环已关闭，daemon 线程随进程退出。
                return
            if not line:
                return

    # Windows 控制台 stdin 仍然使用阻塞读取；独立 daemon 线程只负责搬运
    # 文本，事件循环可以同时调度多个请求和模型/引擎事件。
    threading.Thread(target=read_lines, name="sidecar-stdin", daemon=True).start()
    line_task = asyncio.create_task(lines.get())
    stop_task = asyncio.create_task(router.wait_stopped())
    try:
        while True:
            done, _ = await asyncio.wait(
                (line_task, stop_task), return_when=asyncio.FIRST_COMPLETED
            )
            if stop_task in done:
                if not line_task.done():
                    line_task.cancel()
                    await asyncio.gather(line_task, return_exceptions=True)
                break
            line = line_task.result()
            if not line:
                break
            router.dispatch(line)
            line_task = asyncio.create_task(lines.get())
    finally:
        # stdout 断开时先执行 Sidecar 关闭流程（取消业务任务、结清审批、
        # 关闭运行时），不能无限等待仍在运行的后台任务。
        if writer.closed and not service._shutdown:
            await service.shutdown()
        if not stop_task.done():
            stop_task.cancel()
        if not line_task.done():
            line_task.cancel()
        await asyncio.gather(stop_task, line_task, return_exceptions=True)
        await router.wait_for_tasks()
