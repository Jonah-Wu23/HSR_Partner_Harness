from __future__ import annotations

import asyncio
import io
import json

import pytest

from pair_harness.desktop_backend.router import JsonlWriter, SidecarRouter


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_protocol_whitelist_and_dispatch_reach_onboarding_complete() -> None:
    class Service:
        async def handle_command(self, command):
            assert command.method == "account.onboarding_complete"
            return {"account": {"onboarding_complete": True}}

    output = io.StringIO()
    router = SidecarRouter(Service(), JsonlWriter(output))  # type: ignore[arg-type]
    await router.handle_line(
        json.dumps(
            {
                "kind": "request",
                "id": "ob-1",
                "method": "account.onboarding_complete",
                "params": {},
            }
        )
    )
    response = json.loads(output.getvalue())
    assert response["id"] == "ob-1"
    assert response["ok"] is True
