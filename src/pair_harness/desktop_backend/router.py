from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, TextIO

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
    """stdout 协议写入器；每次写入都是一行完整 JSON。"""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._lock = threading.Lock()

    def write(self, message: dict[str, Any]) -> None:
        with self._lock:
            self.stream.write(encode_message(message))
            self.stream.write("\n")
            self.stream.flush()


class SidecarRouter:
    def __init__(self, service: DesktopApplicationService, writer: JsonlWriter) -> None:
        self.service = service
        self.writer = writer
        self.stop_requested = False
        self._stop_event = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    def dispatch(self, line: str) -> None:
        """提交一条请求，不等待它完成，以便后续请求可以继续进入。"""
        task = asyncio.create_task(self.handle_line(line))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_stopped(self) -> None:
        await self._stop_event.wait()

    async def wait_for_tasks(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def handle_line(self, line: str) -> None:
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
            self.writer.write(protocol_error(code, str(exc), request_id=request_id))
            return

        try:
            result = await self.service.handle_command(command)
        except ServiceError as exc:
            self.writer.write(response_error(command.request_id, exc.code, str(exc)))
            return
        except Exception as exc:  # noqa: BLE001 - Sidecar 不能因单个请求崩溃
            logger.exception("desktop command failed: %s", command.method)
            self.writer.write(
                response_error(command.request_id, "internal_error", str(exc))
            )
            return

        self.writer.write(response_ok(command.request_id, result))
        if command.method == "app.shutdown":
            self.stop_requested = True
            self._stop_event.set()


async def run_stdin(
    service: DesktopApplicationService, *, stdin: TextIO, stdout: TextIO
) -> None:
    """运行 Sidecar 主循环。

    Windows 控制台 stdin 不是 asyncio 原生异步流，使用线程读取单行，
    不阻塞事件循环中的模型、审批和语音任务。
    """
    writer = JsonlWriter(stdout)
    router = SidecarRouter(service, writer)
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
        if not stop_task.done():
            stop_task.cancel()
        if not line_task.done():
            line_task.cancel()
        await asyncio.gather(stop_task, line_task, return_exceptions=True)
        await router.wait_for_tasks()
