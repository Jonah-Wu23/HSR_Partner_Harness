from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from dataclasses import replace
from typing import Any, Callable, TextIO

from .application_service import DesktopApplicationService, ServiceError
from .protocol import (
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
    关闭流程，并把真实错误写入 stderr。
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
                callback = self.on_broken_pipe
                if callback is not None:
                    try:
                        callback()
                    except Exception:  # noqa: BLE001 - 关闭通知失败不能掩盖原始 BrokenPipe
                        logger.exception("stdout BrokenPipeError 关闭通知回调失败")


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
    ) -> None:
        """提交一条请求，不等待它完成，以便后续请求可以继续进入。

        ``reply_sink``（V0.3.3 WS 服务器模式）把 response 额外写回发起
        该请求的远程连接；stdout 仍始终收到同一份 response（唯一权威）。
        stdin 路径不传 reply_sink，行为与之前完全一致。
        ``origin``（V0.3.5）标记命令来源（desktop/remote），由传输层注入
        并写进 DesktopCommand，前端参数不可伪造。
        """
        task = asyncio.create_task(
            self.handle_line(
                line, reply_sink, origin=origin, connection_key=connection_key
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
    ) -> None:
        def respond(message: dict[str, Any]) -> None:
            """response 写 stdout（权威）；远程发起方同时收到同一份。"""
            self.writer.write(message)
            if reply_sink is not None:
                reply_sink(message)

        try:
            command = parse_request(line)
        except Exception as exc:  # 协议错误必须留在 stdout 的结构化消息中
            code = getattr(exc, "code", "invalid_json")
            request_id: str | None = None
            try:
                payload = json.loads(line)
                candidate = payload.get("id") if isinstance(payload, dict) else None
                if isinstance(candidate, str) and candidate:
                    request_id = candidate
            except (TypeError, ValueError):
                pass
            respond(protocol_error(code, str(exc), request_id=request_id))
            return

        if origin != "desktop" or connection_key is not None:
            # V0.3.5：传输层注入来源与连接 key；payload 里的同名字段一律忽略。
            command = replace(command, origin=origin, connection_key=connection_key)

        try:
            result = await self.service.handle_command(command)
        except ServiceError as exc:
            respond(response_error(command.request_id, exc.code, str(exc)))
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
    router: SidecarRouter | None = None,
) -> None:
    """运行 Sidecar 主循环。

    Windows 控制台 stdin 不是 asyncio 原生异步流，使用线程读取单行，
    不阻塞事件循环中的模型、审批和语音任务。stdout 写入器由 __main__
    创建并传入，避免出现第二把写入锁。

    V0.3.3：``--serve`` 模式传入已创建的 ``router``（WS 服务器共享同一
    Router 与 service）；stdin 路径不传则在此创建，行为与之前一致。
    """
    if router is None:
        router = SidecarRouter(service, writer)
    writer.on_broken_pipe = router.request_stop
    lines: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def read_lines() -> None:
        while True:
            line = stdin.readline()
            try:
                loop.call_soon_threadsafe(lines.put_nowait, line)
            except RuntimeError:
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
        # M2.2：stdout 断开时先执行 Sidecar 关闭流程（取消业务任务、结清
        # 审批、关闭运行时），不能无限等待仍在运行的后台任务。
        if writer.closed and not service._shutdown:
            await service.shutdown()
        if not stop_task.done():
            stop_task.cancel()
        if not line_task.done():
            line_task.cancel()
        await asyncio.gather(stop_task, line_task, return_exceptions=True)
        await router.wait_for_tasks()
