import asyncio

import pytest

from pair_harness.adapters.codex.transport import (
    JsonlProcessTransport,
    JsonlProtocolError,
    TransportClosed,
)
from tests.fixtures.jsonl_connection import QueueJsonLineConnection
from tests.service_helpers import wait_until


class ResetOnWriteConnection(QueueJsonLineConnection):
    """管道已断开的连接，写入时与 SubprocessJsonLineConnection 一样抛 TransportClosed。"""

    async def write_line(self, data: bytes) -> None:
        raise TransportClosed("JSONL subprocess connection lost")


def make_transport(
    connection: QueueJsonLineConnection, *, request_timeout: float | None = None
) -> JsonlProcessTransport:
    async def factory() -> QueueJsonLineConnection:
        return connection

    return JsonlProcessTransport(factory, request_timeout=request_timeout)


def agent_message_chunk(session_id: str, text: str) -> dict:
    return {
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": text},
            },
        },
    }


@pytest.mark.asyncio
async def test_transport_correlates_responses_by_id() -> None:
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    first = asyncio.create_task(transport.request("first"))
    second = asyncio.create_task(transport.request("second"))
    request_a = await connection.receive()
    request_b = await connection.receive()
    await connection.send({"id": request_b["id"], "result": {"value": 2}})
    await connection.send({"id": request_a["id"], "result": {"value": 1}})

    assert await first == {"value": 1}
    assert await second == {"value": 2}
    await transport.close()


@pytest.mark.asyncio
async def test_write_failure_closes_connection() -> None:
    connection = ResetOnWriteConnection()
    transport = make_transport(connection)

    with pytest.raises(TransportClosed, match="connection lost"):
        await transport.request("initialize")

    assert not transport.is_running
    assert connection.closed
    await transport.close()


@pytest.mark.asyncio
async def test_eof_fails_pending_request_with_exit_diagnostics() -> None:
    connection = QueueJsonLineConnection(
        exit_description="JSONL subprocess exited (exit code 1): config.toml not found"
    )
    transport = make_transport(connection)
    request = asyncio.create_task(transport.request("initialize"))
    await connection.receive()
    await connection.server_to_client.put(b"")

    with pytest.raises(TransportClosed, match=r"exit code 1\): config.toml not found"):
        await request
    await transport.close()


@pytest.mark.asyncio
async def test_unparseable_line_fails_all_pending_requests() -> None:
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    first = asyncio.create_task(transport.request("ping"))
    second = asyncio.create_task(transport.request("pong"))
    await connection.receive()
    await connection.receive()
    await connection.server_to_client.put(b"this is not json\n")

    for future in (first, second):
        with pytest.raises(JsonlProtocolError, match="this is not json"):
            await future
    assert not transport.is_running
    await transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_timeout", "call_timeout"),
    [(None, 0.05), (0.05, None)],
)
async def test_request_without_response_times_out(
    request_timeout: float | None, call_timeout: float | None
) -> None:
    transport = make_transport(QueueJsonLineConnection(), request_timeout=request_timeout)
    with pytest.raises(TimeoutError):
        await transport.request("ping", timeout=call_timeout)
    await transport.close()


@pytest.mark.asyncio
async def test_session_notifications_route_by_session_id() -> None:
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    await transport.start()
    sub_a = transport.subscribe_session("session-a")
    sub_b = transport.subscribe_session("session-b")
    await connection.send(agent_message_chunk("session-a", "A1"))
    await connection.send(agent_message_chunk("session-b", "B1"))
    await connection.send(agent_message_chunk("session-a", "A2"))

    async def next_text(subscription) -> str:
        notification = await asyncio.wait_for(subscription.next(), timeout=2)
        return notification["params"]["update"]["content"]["text"]

    assert [await next_text(sub_a), await next_text(sub_a)] == ["A1", "A2"]
    assert await next_text(sub_b) == "B1"
    sub_a.close()
    sub_b.close()
    await transport.close()


@pytest.mark.asyncio
async def test_server_request_reaches_session_subscriber_and_gets_reply() -> None:
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    subscription = transport.subscribe_session("s1")
    pending = asyncio.create_task(
        transport.request("session/prompt", {"sessionId": "s1", "prompt": []})
    )
    request = await connection.receive()

    # 服务端在 prompt 响应之前发起审批请求，两者的 id 互不串扰
    await connection.send(
        {
            "id": 100,
            "method": "session/request_permission",
            "params": {
                "sessionId": "s1",
                "toolCall": {
                    "toolCallId": "gate-a1",
                    "title": "bash ls",
                    "kind": "execute",
                    "status": "pending",
                },
                "options": [
                    {"optionId": "allow_once", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "reject_once", "name": "Reject", "kind": "reject_once"},
                ],
            },
        }
    )
    await connection.send({"id": request["id"], "result": {"stopReason": "end_turn"}})

    assert await pending == {"stopReason": "end_turn"}
    notification = await asyncio.wait_for(subscription.next(), timeout=2)
    assert notification["method"] == "session/request_permission"
    assert notification["id"] == 100
    await transport.respond(100, {"outcome": {"outcome": "selected", "optionId": "allow_once"}})
    assert await connection.receive() == {
        "id": 100,
        "result": {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
    }
    subscription.close()
    await transport.close()


@pytest.mark.asyncio
async def test_reconnect_does_not_deliver_stale_reader_failure() -> None:
    """旧连接 EOF 只结束旧代次，重连后新建的订阅器收不到旧 reader 的失败。"""
    connections: list[QueueJsonLineConnection] = []

    async def factory() -> QueueJsonLineConnection:
        connection = QueueJsonLineConnection()
        if not connections:
            connection.server_to_client.put_nowait(b"")
        connections.append(connection)
        return connection

    transport = JsonlProcessTransport(factory)
    await transport.start()
    await wait_until(lambda: not transport.is_running)
    assert transport.generation == 1

    await transport.start()
    assert transport.generation == 2
    subscription = transport.subscribe_session("s1")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(subscription.next(), timeout=0.05)
    subscription.close()
    await transport.close()
