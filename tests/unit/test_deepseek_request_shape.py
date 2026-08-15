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
from pair_harness.core.contracts import (
    DialogueRequest,
    Message,
    MessageKind,
    MessageSource,
    ProjectRuntimeContext,
)


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
    assert "reasoning_effort" not in body  # 未指定档位不写入
    assert body["temperature"] == 1.0
    assert body["max_tokens"] == 8192


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
    assert body["thinking"] == {"type": "disabled"}
    # 结构化角色回合不把已关闭的 thinking 与 effort 再混传。
    assert "reasoning_effort" not in body


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
async def test_deepseek_structured_dialogue_uses_configured_sampling() -> None:
    """结构化角色回合按配置采样温度，不再固定为确定式采样。"""
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
    assert bodies[0]["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_deepseek_structured_dialogue_retries_empty_content_once() -> None:
    calls = 0

    def handler(request: Request) -> Response:
        nonlocal calls
        calls += 1
        content = " " if calls < 3 else '{"speech":"ok"}'
        delta = json.dumps({"choices": [{"delta": {"content": content}}]})
        lines = [f"data: {delta}\n".encode(), b"data: [DONE]\n"]
        return Response(200, content=b"".join(lines))

    client = AsyncClient(
        base_url="https://api.deepseek.com",
        transport=MockTransport(handler),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
        client=client,
    )
    events = [event async for event in model.stream_reply(make_request())]
    assert calls == 3
    assert events[-1].type == "character.final"
    assert events[-1].turn is not None
    assert events[-1].turn.speech == "ok"


@pytest.mark.asyncio
async def test_deepseek_collaboration_retries_missing_delegation() -> None:
    calls = 0

    def handler(request: Request) -> Response:
        nonlocal calls
        calls += 1
        content = (
            '{"speech":"交给搭档。","delegate":true}'
            if calls == 1
            else '{"speech":"交给搭档。","delegation":{"type":"task","instructions":"检查项目文件"}}'
        )
        delta = json.dumps({"choices": [{"delta": {"content": content}}]})
        lines = [f"data: {delta}\n".encode(), b"data: [DONE]\n"]
        return Response(200, content=b"".join(lines))

    user = make_request().user_message.model_copy(update={"text": "请让搭档检查项目文件"})
    request = make_request().model_copy(
        update={
            "user_message": user,
            "runtime_context": ProjectRuntimeContext(
                project_name="项目",
                project_abs_dir="C:/project",
                conversation_mode="collaboration",
            ),
        }
    )
    client = AsyncClient(
        base_url="https://api.deepseek.com",
        transport=MockTransport(handler),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        model="deepseek-v4-flash",
        client=client,
    )
    events = [event async for event in model.stream_reply(request)]
    assert calls == 2
    assert events[-1].turn is not None
    assert events[-1].turn.delegation is not None
