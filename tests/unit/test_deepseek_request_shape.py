import json

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import (
    DialogueRequest,
    Message,
    MessageKind,
    MessageSource,
)


def _sse_response(content: bytes) -> Response:
    return Response(200, headers={"content-type": "text/event-stream"}, content=content)


def _capturing_transport(bodies: list[dict]) -> MockTransport:
    def handler(request: Request) -> Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        delta = json.dumps(
            {"choices": [{"delta": {"content": '{"speech":"ok"}'}}]}, ensure_ascii=True
        )
        lines = [f"data: {delta}\n\n".encode("ascii"), b"data: [DONE]\n\n"]
        return _sse_response(b"".join(lines))

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
async def test_deepseek_structured_dialogue_disables_thinking() -> None:
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
    # 真实 deepseek-v4-flash 在 thinking + JSON Output + 对话上下文时会返回
    # 只有空格的 content；结构化角色回合必须使用可解析的请求形态。
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in body
    assert "temperature" not in body  # 未配置温度时不写入
    assert body["max_tokens"] == 8192


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
    )
    [event async for event in model.stream_reply(make_request())]

    body = bodies[0]
    assert "thinking" not in body
    assert "reasoning_effort" not in body
    assert "response_format" not in body
    assert body["stream"] is True
