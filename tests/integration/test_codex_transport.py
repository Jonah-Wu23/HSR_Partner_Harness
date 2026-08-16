import asyncio
import json

import pytest

from pair_harness.adapters.codex.dialogue import CodexDialogueModel
from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport, TransportClosed
from pair_harness.core.contracts import (
    DialogueRequest,
    Message,
    MessageKind,
    MessageSource,
    ProjectRef,
    TaskRequest,
)
from tests.fixtures.fake_codex_app_server import FakeCodexAppServer, QueueJsonLineConnection


class ResetOnWriteConnection(QueueJsonLineConnection):
    async def write_line(self, data: bytes) -> None:
        del data
        raise ConnectionResetError("连接已重置")


class ExitedConnection(QueueJsonLineConnection):
    async def exit_description(self) -> str:
        return "Codex app-server exited (exit code 1): CODEX_HOME 不存在"


class EofConnection:
    """立即 EOF 的连接，用于制造旧 reader 的失败并结束旧代次。"""

    async def read_line(self) -> bytes:
        return b""

    async def write_line(self, data: bytes) -> None:
        del data

    async def close(self) -> None:
        pass


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_codex_reasoning_effort_accepts_gpt_56_sol_levels(effort: str) -> None:
    engine = CodexAppServerEngine(JsonlProcessTransport("unused"))

    engine.configure_reasoning(effort)

    assert engine.reasoning_effort == effort


def test_codex_reasoning_effort_normalizes_auto_to_medium() -> None:
    """configure_reasoning 的真实归一化：auto → medium（F5 档位语义）。"""
    engine = CodexAppServerEngine(JsonlProcessTransport("unused"), reasoning_effort="auto")

    engine.configure_reasoning("auto")

    assert engine.reasoning_effort == "medium"


def test_codex_reasoning_effort_rejects_invalid_values() -> None:
    """非法档位必须报错，而不是静默接受后带着错误档位发请求。"""
    engine = CodexAppServerEngine(JsonlProcessTransport("unused"))

    with pytest.raises(ValueError, match="unsupported"):
        engine.configure_reasoning("ultra")


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
async def test_transport_normalizes_connection_reset_and_releases_connection() -> None:
    connection = ResetOnWriteConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)

    with pytest.raises(TransportClosed) as raised:
        await transport.request("initialize")

    assert str(raised.value) == "Codex app-server connection lost"
    assert not transport.is_running
    assert transport._connection is None
    await transport.close()


@pytest.mark.asyncio
async def test_transport_preserves_process_exit_diagnostics() -> None:
    """app-server EOF 要保留退出码/启动 stderr，而不是只报泛化 EOF。"""
    connection = ExitedConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    request = asyncio.create_task(transport.request("initialize"))
    await connection.receive_request()
    await connection.server_to_client.put(b"")

    with pytest.raises(TransportClosed, match="CODEX_HOME 不存在"):
        await request
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
    assert request["params"]["model"] == "gpt-5.6-sol"
    assert request["params"]["effort"] == "medium"
    task_payload = json.loads(request["params"]["input"][0]["text"])
    assert task_payload == {
        "type": "TaskRequest",
        "task_id": task.task_id,
        "instructions": "run tests",
        "constraints": ["only edit tests", "do not rename files"],
    }
    await server.notify("turn/started", {"turn": {"id": "turn-1"}})
    await server.notify(
        "item/completed",
        {
            "turnId": "turn-1",
            "item": {"id": "msg-1", "type": "agentMessage", "text": "done"},
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
    project = ProjectRef(project_id="p", name="p", root_path=r"C:\project")

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


@pytest.mark.asyncio
async def test_engine_repeats_initialize_after_transport_reconnect() -> None:
    connections: list[QueueJsonLineConnection] = []

    async def factory():
        connection = QueueJsonLineConnection()
        connections.append(connection)
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    engine = CodexAppServerEngine(transport)
    project = ProjectRef(project_id="p", name="p", root_path="C:\\project")

    first_open = asyncio.create_task(engine.open_session(project))
    while len(connections) < 1:
        await asyncio.sleep(0)
    first_server = FakeCodexAppServer(connections[0])
    await first_server.serve_request({"thread": {"id": "thread-1"}})
    await first_open
    await transport.close()

    second_open = asyncio.create_task(engine.open_session(project))
    while len(connections) < 2:
        await asyncio.sleep(0)
    second_server = FakeCodexAppServer(connections[1])
    await second_server.serve_request({"thread": {"id": "thread-2"}})
    await second_open

    assert [request["method"] for request in second_server.requests] == [
        "initialize",
        "thread/start",
    ]
    await transport.close()


@pytest.mark.asyncio
async def test_run_turn_idle_timeout_requests_interrupt_then_fails() -> None:
    """M1.3：app-server 存活但不发事件时，短超时先 interrupt 再 TURN_FAILED。"""
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    engine = CodexAppServerEngine(transport, idle_timeout=0.05)
    server = FakeCodexAppServer(connection)
    session_ref = engine._encode_ref("thread-1")
    task = TaskRequest(
        conversation_id="conversation-1",
        origin_message_id="message-1",
        instructions="run",
    )

    async def collect_events():
        return [event async for event in engine.run_turn(session_ref, task)]

    collection = asyncio.create_task(collect_events())
    turn_request = await server.serve_request({"turn": {"id": "turn-1"}})
    assert turn_request["method"] == "turn/start"
    interrupt_request = await server.serve_request({})
    assert interrupt_request["method"] == "turn/interrupt"
    assert interrupt_request["params"] == {"threadId": "thread-1", "turnId": "turn-1"}

    events = await collection
    assert events[-1].type == "turn.failed"
    assert "idle timeout" in events[-1].payload["error"]
    await transport.close()


@pytest.mark.asyncio
async def test_codex_dialogue_cancel_interrupts_engine_and_cleans_session() -> None:
    """M6.1：Codex 角色对话流取消时向 app-server 发 interrupt 并清理 _sessions。"""
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    model = CodexDialogueModel(transport)
    server = FakeCodexAppServer(connection)
    message = Message(
        conversation_id="conversation-1",
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="你好",
    )
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="conversation-1",
        user_message=message,
    )
    collected: list[object] = []

    async def consume():
        async for event in model.stream_reply(request):
            collected.append(event)

    stream_task = asyncio.create_task(consume())
    await server.serve_request({"thread": {"id": "thread-1"}})
    await server.serve_request({"turn": {"id": "turn-1"}})
    await server.notify("turn/started", {"turn": {"id": "turn-1"}})
    await server.notify(
        "item/reasoning/summaryTextDelta",
        {"turnId": "turn-1", "itemId": "r1", "delta": "思考中"},
    )
    for _ in range(200):
        if collected:
            break
        await asyncio.sleep(0.01)
    assert collected, "dialogue stream should have started consuming engine events"

    stream_task.cancel()
    # cancel_turn 是请求-响应调用：先让 fake server 应答 interrupt，
    # 再等待被取消的流真正结束，避免双向等待。
    interrupt = await server.serve_request({})
    assert interrupt["method"] == "turn/interrupt"
    assert interrupt["params"] == {"threadId": "thread-1", "turnId": "turn-1"}
    with pytest.raises(asyncio.CancelledError):
        await stream_task
    assert request.conversation_id not in model._sessions
    await transport.close()


@pytest.mark.asyncio
async def test_old_reader_exception_does_not_poison_new_notification_queue() -> None:
    """M1.3：重连使用新通知队列，旧 reader 的 EOF 异常只结束旧队列。"""
    connections: list[object] = []

    async def factory():
        connection = EofConnection() if not connections else QueueJsonLineConnection()
        connections.append(connection)
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    await transport.start()
    while transport.is_running:
        await asyncio.sleep(0)
    assert transport.generation == 1

    await transport.start()
    assert transport.generation == 2

    # 新队列不应收到旧 reader 的 TransportClosed，只应正常等待通知。
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(transport.next_notification(), timeout=0.05)
    await transport.close()
