from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from pair_harness.desktop_backend.application_service import ServiceError
from pair_harness.desktop_backend.commands import DesktopCommand

DEFAULT_TIMEOUT_S = 5.0


def command(
    request_id: str, method: str, *, origin: str = "desktop", **params: Any
) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params, origin=origin)


async def call(
    service,
    request_id: str,
    method: str,
    *,
    origin: str = "desktop",
    timeout: float = DEFAULT_TIMEOUT_S,
    **params: Any,
) -> Any:
    """带超时的命令调用，挂起时按超时失败。"""
    return await asyncio.wait_for(
        service.handle_command(command(request_id, method, origin=origin, **params)),
        timeout=timeout,
    )


async def wait_until(
    predicate: Callable[[], bool],
    *,
    message: str = "等待的条件在超时内没有成立",
    timeout: float = DEFAULT_TIMEOUT_S,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError(message)
        await asyncio.sleep(0.01)


async def expect_service_error(
    action: Callable[[], Awaitable[Any]],
    code: str,
    *,
    contains: str | None = None,
) -> ServiceError:
    with pytest.raises(ServiceError) as excinfo:
        await action()
    assert excinfo.value.code == code, str(excinfo.value)
    if contains is not None:
        assert contains in str(excinfo.value)
    return excinfo.value


class EventLog:
    """作为 event_sink 记录全部事件信封，按事件名取 payload。"""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def __call__(self, envelope: dict[str, Any]) -> None:
        self.items.append(envelope)

    def payloads(self, event: str) -> list[dict[str, Any]]:
        return [item["payload"] for item in self.items if item["event"] == event]
