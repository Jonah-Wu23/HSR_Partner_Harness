import asyncio

import pytest

from pair_harness.adapters.codex.transport import JsonlProcessTransport
from tests.fixtures.fake_codex_app_server import QueueJsonLineConnection


def make_transport(*, request_timeout: float | None = None) -> JsonlProcessTransport:
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    return JsonlProcessTransport(
        "unused", connection_factory=factory, request_timeout=request_timeout
    ), connection


@pytest.mark.asyncio
async def test_bad_json_line_is_skipped_and_loop_continues() -> None:
    """O1.3：读循环遇到坏 JSON 行只跳过，后续正常响应仍被解析。"""
    transport, connection = make_transport()
    future = asyncio.create_task(transport.request("ping"))
    request = await connection.receive_request()
    # 直接注入坏行（绕过 send 的 json 序列化）
    await connection.server_to_client.put(b"this is not json\n")
    await connection.send({"id": request["id"], "result": {"ok": True}})

    assert await future == {"ok": True}
    assert transport.bad_line_count == 1
    await transport.close()


@pytest.mark.asyncio
async def test_request_timeout_raises_recognizable_error() -> None:
    """O1.3：服务端不响应时请求超时，抛出可识别异常。"""
    transport, connection = make_transport()
    with pytest.raises(asyncio.TimeoutError):
        await transport.request("ping", timeout=0.05)
    await transport.close()


@pytest.mark.asyncio
async def test_constructor_request_timeout_applies_by_default() -> None:
    """O1.3：构造级 request_timeout 作为默认超时生效。"""
    transport, connection = make_transport(request_timeout=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await transport.request("ping")
    await transport.close()
