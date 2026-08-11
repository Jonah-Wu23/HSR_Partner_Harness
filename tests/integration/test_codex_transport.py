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

    open_task = asyncio.create_task(
        engine.open_session(project, developer_instructions="保持古代机械口吻")
    )
    request = await server.serve_request({"thread": {"id": "thread-1"}})
    assert request["method"] == "thread/start"
    assert request["params"] == {
        "cwd": "C:\\project",
        "developerInstructions": "保持古代机械口吻",
    }
    session_ref = await open_task
    assert "thread-1" not in session_ref.opaque_ref

    task = TaskRequest(
        conversation_id="conversation-1",
        origin_message_id="message-1",
        instructions="run tests",
        constraints=("only edit tests", "do not rename files"),
    )

    async def collect_events():
        return [event async for event in engine.run_turn(session_ref, task)]

    collection = asyncio.create_task(collect_events())
    request = await server.serve_request({"turn": {"id": "turn-1"}})
    assert request["method"] == "turn/start"
    assert request["params"]["threadId"] == "thread-1"
    assert request["params"]["input"][0]["text"] == (
        "run tests\n\n本次任务约束：\n"
        "- only edit tests\n- do not rename files"
    )
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


@pytest.mark.asyncio
async def test_server_initiated_request_goes_to_notification_queue() -> None:
    """O3.1：服务端发起的请求（带 id+method，如 requestApproval）不得被
    当作客户端请求的响应（否则挂起请求被错误消费、裁决回复丢失）。"""
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    server = FakeCodexAppServer(connection)
    pending = asyncio.create_task(transport.request("thread/start", {"cwd": "C:\\p"}))
    request = await connection.receive_request()
    assert request["method"] == "thread/start"

    # 服务端先发审批请求（带 id），再回 thread/start 的响应
    await server.connection.send(
        {
            "id": 100,
            "method": "item/commandExecution/requestApproval",
            "params": {"itemId": "tool-1", "command": "pytest", "cwd": "C:\\p"},
        }
    )
    await server.connection.send(
        {"id": request["id"], "result": {"thread": {"id": "thread-1"}}}
    )

    # 响应仍然路由回挂起的 request（id 未串扰）
    result = await pending
    assert result["thread"]["id"] == "thread-1"

    # 审批请求进入通知队列，可经 respond 回复
    notification = await transport.next_notification()
    assert notification["method"] == "item/commandExecution/requestApproval"
    assert notification["id"] == 100
    await transport.respond(100, {"decision": "accept"})
    reply = await server.connection.receive_request()
    assert reply == {"id": 100, "result": {"decision": "accept"}}
    await transport.close()



@pytest.mark.asyncio
async def test_open_session_sends_initialize_handshake_before_thread_start() -> None:
    """B1：app-server 协议要求 initialize 握手先于 thread/start。

    真实 app-server 未握手时返回 {"code": -32600, "message": "Not initialized"}；
    握手只发一次，恢复线程时不再重复。
    """
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    project = ProjectRef(project_id="p", name="p", root_path="C:\project")

    open_task = asyncio.create_task(engine.open_session(project))
    request = await server.serve_request({"thread": {"id": "thread-1"}})
    assert request["method"] == "thread/start"
    session_ref = await open_task

    # 握手请求已被 fake server 透明应答并记录
    handshakes = [r for r in server.requests if r["method"] == "initialize"]
    assert len(handshakes) == 1
    assert handshakes[0]["params"]["clientInfo"]["name"] == "pair-harness"

    # 恢复线程：仅 thread/resume，不再重复握手
    resume_task = asyncio.create_task(engine.open_session(project, stored_ref=session_ref))
    resume_request = await server.serve_request({"thread": {"id": "thread-1"}})
    assert resume_request["method"] == "thread/resume"
    await resume_task
    handshakes = [r for r in server.requests if r["method"] == "initialize"]
    assert len(handshakes) == 1
    await transport.close()
