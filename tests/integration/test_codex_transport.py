import asyncio

import pytest

from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.core.contracts import ProjectRef, TaskRequest
from tests.fixtures.fake_codex_app_server import FakeCodexAppServer, QueueJsonLineConnection


@pytest.mark.asyncio
async def test_transport_correlates_requests_with_single_reader() -> None:
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    server = FakeCodexAppServer(connection)
    first = asyncio.create_task(transport.request("first"))
    second = asyncio.create_task(transport.request("second"))
    request_a = await connection.receive_request()
    request_b = await connection.receive_request()
    await connection.send({"id": request_b["id"], "result": {"value": 2}})
    await connection.send({"id": request_a["id"], "result": {"value": 1}})

    assert await first == {"value": 1}
    assert await second == {"value": 2}
    assert server.requests == []
    await transport.close()


@pytest.mark.asyncio
async def test_offline_engine_opens_session_and_streams_mapped_events() -> None:
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    project = ProjectRef(project_id="p", name="p", root_path="C:\\project")

    open_task = asyncio.create_task(engine.open_session(project))
    request = await server.serve_request({"thread": {"id": "thread-1"}})
    assert request["method"] == "thread/start"
    assert request["params"] == {"cwd": "C:\\project"}
    session_ref = await open_task
    assert "thread-1" not in session_ref.opaque_ref

    task = TaskRequest(
        conversation_id="conversation-1",
        origin_message_id="message-1",
        instructions="run tests",
    )

    async def collect_events():
        return [event async for event in engine.run_turn(session_ref, task)]

    collection = asyncio.create_task(collect_events())
    request = await server.serve_request({"turn": {"id": "turn-1"}})
    assert request["method"] == "turn/start"
    assert request["params"]["threadId"] == "thread-1"
    await server.notify("turn/started", {"turn": {"id": "turn-1"}})
    await server.notify(
        "item/completed",
        {
            "turnId": "turn-1",
            "item": {"id": "msg-1", "type": "agent_message", "text": "done"},
        },
    )
    await server.notify(
        "turn/completed", {"turn": {"id": "turn-1", "status": "completed"}}
    )
    events = await collection

    assert [event.type for event in events] == [
        "turn.started",
        "assistant.final",
        "turn.completed",
    ]
    assert {event.conversation_id for event in events} == {"conversation-1"}
    await transport.close()


@pytest.mark.asyncio
async def test_cancel_turn_sends_interrupt_with_thread_and_turn_ids() -> None:
    """O2.3：取消任务发出 turn/interrupt，参数携带 threadId 与 turnId。"""
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    session_ref = engine._encode_ref("thread-1")

    cancel = asyncio.create_task(engine.cancel_turn(session_ref, "turn-9"))
    request = await server.serve_request({})
    assert request["method"] == "turn/interrupt"
    assert request["params"] == {"threadId": "thread-1", "turnId": "turn-9"}
    await cancel
    await transport.close()

