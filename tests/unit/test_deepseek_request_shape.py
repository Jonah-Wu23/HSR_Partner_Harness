"""B1：DeepSeek 请求体形态（离线，用 MockTransport 断言请求字段）。

验证 MVP 计划 §5 B1.1：识别 api.deepseek.com 后自动应用 DeepSeek
请求形态（thinking.type + reasoning_effort），非 DeepSeek 端点保持
标准 OpenAI 兼容请求体。不发起真实请求。
"""

import json

import pytest
from httpx import AsyncClient, Request, Response
from httpx._transports.mock import MockTransport

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import DialogueRequest, Message, MessageKind, MessageSource


def _capturing_transport(bodies: list[dict]) -> MockTransport:
    def handler(request: Request) -> Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        delta = json.dumps({"choices": [{"delta": {"content": "ok"}}]}, ensure_ascii=True)
        lines = [f"data: {delta}\n".encode("ascii"), b"data: [DONE]\n"]
        return Response(200, content=b"".join(lines))

    return MockTransport(handler)


def make_request() -> DialogueRequest:
    message = Message(
        conversation_id="c",
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="你好",
    )
    return DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=message,
    )


@pytest.mark.asyncio
async def test_deepseek_request_carries_thinking_and_effort() -> None:
    bodies: list[dict] = []
    client = AsyncClient(
        base_url="https://api.deepseek.com",
        transport=_capturing_transport(bodies),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
        client=client,
    )
    events = [event async for event in model.stream_reply(make_request())]
    assert events[-1].type == "character.final"

    body = bodies[0]
    assert body["model"] == "deepseek-v4-flash"
    assert body["thinking"] == {"type": "enabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in body  # 未指定档位不写入


@pytest.mark.asyncio
async def test_deepseek_effort_medium_normalized_to_high() -> None:
    bodies: list[dict] = []
    client = AsyncClient(
        base_url="https://api.deepseek.com",
        transport=_capturing_transport(bodies),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
        client=client,
        thinking=True,
        reasoning_effort="medium",
    )
    [event async for event in model.stream_reply(make_request())]

    body = bodies[0]
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_deepseek_thinking_disabled() -> None:
    bodies: list[dict] = []
    client = AsyncClient(
        base_url="https://api.deepseek.com",
        transport=_capturing_transport(bodies),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
        client=client,
        thinking=False,
    )
    [event async for event in model.stream_reply(make_request())]

    assert bodies[0]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_non_deepseek_host_keeps_standard_body() -> None:
    bodies: list[dict] = []
    client = AsyncClient(
        base_url="https://example.com/v1",
        transport=_capturing_transport(bodies),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="some-model",
        client=client,
        thinking=False,
        reasoning_effort="high",
    )
    [event async for event in model.stream_reply(make_request())]

    body = bodies[0]
    assert "thinking" not in body
    assert "reasoning_effort" not in body
    assert "response_format" not in body
    assert body["stream"] is True


@pytest.mark.asyncio
async def test_temperature_written_only_when_set() -> None:
    """B1：显式温度写入请求体；未设置时不写（交给服务端默认）。"""
    bodies: list[dict] = []
    client = AsyncClient(
        base_url="https://api.deepseek.com",
        transport=_capturing_transport(bodies),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
        client=client,
        temperature=1.0,
    )
    [event async for event in model.stream_reply(make_request())]
    assert bodies[0]["temperature"] == 1.0

    bodies2: list[dict] = []
    client2 = AsyncClient(
        base_url="https://api.deepseek.com",
        transport=_capturing_transport(bodies2),
    )
    model2 = OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
        client=client2,
    )
    [event async for event in model2.stream_reply(make_request())]
    assert "temperature" not in bodies2[0]
