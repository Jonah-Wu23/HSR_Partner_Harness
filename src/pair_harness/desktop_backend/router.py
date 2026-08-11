from __future__ import annotations

import json
import logging
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

    def write(self, message: dict[str, Any]) -> None:
        self.stream.write(encode_message(message))
        self.stream.write("\n")
        self.stream.flush()


class SidecarRouter:
    def __init__(self, service: DesktopApplicationService, writer: JsonlWriter) -> None:
        self.service = service
        self.writer = writer
        self.stop_requested = False

    async def handle_line(self, line: str) -> None:
        try:
            command = parse_request(line)
        except Exception as exc:  # 协议错误必须留在 stdout 的结构化消息中
            code = getattr(exc, "code", "invalid_json")
            self.writer.write(protocol_error(code, str(exc)))
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


async def run_stdin(
    service: DesktopApplicationService, *, stdin: TextIO, stdout: TextIO
) -> None:
    """运行 Sidecar 主循环。

    Windows 控制台 stdin 不是 asyncio 原生异步流，使用线程读取单行，
    不阻塞事件循环中的模型、审批和语音任务。
    """
    writer = JsonlWriter(stdout)
    router = SidecarRouter(service, writer)
    while not router.stop_requested:
        line = await __import__("asyncio").to_thread(stdin.readline)
        if not line:
            break
        await router.handle_line(line)
