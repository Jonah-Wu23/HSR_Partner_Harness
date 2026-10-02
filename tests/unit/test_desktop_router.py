from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime, timezone

from pair_harness.desktop_backend.commands import DESKTOP_COMMANDS
from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter


async def test_sidecar_router_accepts_cancel_while_chat_request_is_running() -> None:
    chat_started = asyncio.Event()
    cancel_seen = asyncio.Event()
    release_chat = asyncio.Event()
    chat_finished = False

    class BlockingService:
        async def handle_command(self, command):
            nonlocal chat_finished
            if command.method == "chat.submit":
                chat_started.set()
                await release_chat.wait()
                chat_finished = True
                return {"status": "completed"}
            if command.method == "task.cancel":
                cancel_seen.set()
                return {"cancelled": True}
            return {}

    output = io.StringIO()
    router = SidecarRouter(BlockingService(), JsonlWriter(output))  # type: ignore[arg-type]
    router.dispatch(
        json.dumps(
            {
                "kind": "request",
                "id": "chat-1",
                "method": "chat.submit",
                "params": {"text": "长任务"},
            }
        )
    )
    await asyncio.wait_for(chat_started.wait(), timeout=1)

    router.dispatch(
        json.dumps(
            {
                "kind": "request",
                "id": "cancel-1",
                "method": "task.cancel",
                "params": {},
            }
        )
    )
    await asyncio.wait_for(cancel_seen.wait(), timeout=1)
    assert chat_finished is False
    assert [json.loads(line)["id"] for line in output.getvalue().splitlines()] == ["cancel-1"]

    release_chat.set()
    await router.wait_for_tasks()
    assert chat_finished is True
    assert {json.loads(line)["id"] for line in output.getvalue().splitlines()} == {
        "chat-1",
        "cancel-1",
    }


async def test_protocol_whitelist_matches_service_handlers(service) -> None:
    """协议白名单里的方法都有处理器，处理器也都能经协议调用。"""
    assert set(service._handlers) == DESKTOP_COMMANDS


async def test_router_reports_unserializable_response_instead_of_timeout() -> None:
    """响应不可序列化时回执 encode_error，调用方不会等到超时。"""

    class UnserializableService:
        async def handle_command(self, command):
            return {"leaked": datetime.now(timezone.utc)}

    output = io.StringIO()
    router = SidecarRouter(UnserializableService(), JsonlWriter(output))  # type: ignore[arg-type]
    await router.handle_line('{"kind":"request","id":"r-1","method":"ping","params":{}}')
    frame = json.loads(output.getvalue())
    assert frame["id"] == "r-1"
    assert frame["ok"] is False
    assert frame["error"]["code"] == "encode_error"
    assert "datetime" in frame["error"]["message"]
