import json

import pytest
from httpx import AsyncClient, Request, Response
from httpx._transports.mock import MockTransport

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import DialogueRequest, Message, MessageKind, MessageSource


def _mock_stream_transport(content_chunks: list[str]) -> MockTransport:
    def handler(request: Request) -> Response:
        lines = []
        for chunk in content_chunks:
            data = (
                '{"choices":[{"delta":{"content":"'
                + chunk.replace('"', '\\"')
                + '"}}]}'
            )
            lines.append(f"data: {data}\n".encode("utf-8"))
        lines.append(b"data: [DONE]\n")
        return Response(200, content=b"".join(lines))

    return MockTransport(handler)


@pytest.mark.asyncio
async def test_openai_compatible_stream_yields_final_character_turn() -> None:
    client = AsyncClient(
        base_url="http://test", transport=_mock_stream_transport(["你好", "，", "伙伴"])
    )
    model = OpenAICompatibleDialogueModel(
        base_url="http://test",
        api_key="test-key",
        model="test-model",
        client=client,
    )
    message = Message(
        conversation_id="c",
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="你好",
    )
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=message,
    )

    events = [event async for event in model.stream_reply(request)]

    deltas = [event.delta for event in events if event.type == "speech.delta"]
    finals = [event for event in events if event.type == "character.final"]
    assert deltas == ["你好", "，", "伙伴"]
    assert len(finals) == 1
    assert finals[0].turn.speech == "你好，伙伴"


@pytest.mark.asyncio
async def test_generate_title_uses_assistant_only_non_streaming_request() -> None:
    captured: list[dict] = []

    def handler(request: Request) -> Response:
        body = json.loads(request.content)
        captured.append(body)
        return Response(
            200,
            json={"choices": [{"message": {"content": "整理今天的工作"}}]},
        )

    client = AsyncClient(base_url="http://test", transport=MockTransport(handler))
    model = OpenAICompatibleDialogueModel(
        base_url="http://test",
        api_key="test-key",
        model="test-model",
        client=client,
    )
    context = (
        Message(
            conversation_id="c",
            pair_id="phainon_ancient_machine",
            source=MessageSource.USER,
            kind=MessageKind.USER_TEXT,
            text="请帮我整理今天的工作",
        ),
        Message(
            conversation_id="c",
            pair_id="phainon_ancient_machine",
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text="好，我先陪你理清顺序。",
        ),
    )

    title = await model.generate_title(pair_id="phainon_ancient_machine", context=context)

    assert title == "整理今天的工作"
    assert len(captured) == 1
    assert captured[0]["stream"] is False
    assert "不能调用工具" in captured[0]["messages"][0]["content"]
    assert "用户：请帮我整理今天的工作" in captured[0]["messages"][1]["content"]
    assert "角色：好，我先陪你理清顺序。" in captured[0]["messages"][1]["content"]
    await client.aclose()


@pytest.mark.asyncio
async def test_generate_title_retries_when_content_empty() -> None:
    """推理模型把 token 预算耗在思考上（finish_reason=length、content 空）时
    必须用更大预算重试，而不是静默放弃标题。"""
    captured: list[dict] = []

    def handler(request: Request) -> Response:
        body = json.loads(request.content)
        captured.append(body)
        if len(captured) == 1:
            # 首次：思考耗尽 token，content 为空（真实 DeepSeek 故障形状）
            return Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": ""},
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {"completion_tokens_details": {"reasoning_tokens": 128}},
                },
            )
        return Response(
            200,
            json={"choices": [{"message": {"content": "整理今天的工作"}}]},
        )

    client = AsyncClient(base_url="https://api.deepseek.com", transport=MockTransport(handler))
    model = OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        client=client,
    )
    context = (
        Message(
            conversation_id="c",
            pair_id="phainon_ancient_machine",
            source=MessageSource.USER,
            kind=MessageKind.USER_TEXT,
            text="请帮我整理今天的工作",
        ),
    )

    title = await model.generate_title(pair_id="phainon_ancient_machine", context=context)

    assert title == "整理今天的工作"
    assert len(captured) == 2
    # 首次请求关闭思考（标题不需要推理）并给足够 token 预算
    assert captured[0]["max_tokens"] == 128
    assert captured[0]["thinking"] == {"type": "disabled"}
    # 重试放开思考并加大预算
    assert captured[1]["max_tokens"] == 512
    await client.aclose()


@pytest.mark.parametrize(
    "raw, expected_instructions",
    [
        # 角色卡 phainon.md 约定：delegation.data.instructions（嵌套 data）
        (
            json.dumps(
                {
                    "speech": "这事我插不上手。",
                    "delegation": {
                        "type": "task",
                        "data": {"instructions": "创建 hello.txt", "constraints": ["内容为 hello"]},
                    },
                },
                ensure_ascii=False,
            ),
            "创建 hello.txt",
        ),
        # 适配器输出格式指令：delegation.instructions（平铺）
        (
            json.dumps(
                {
                    "speech": "这事我插不上手。",
                    "delegation": {"type": "task", "instructions": "创建 hello.txt"},
                },
                ensure_ascii=False,
            ),
            "创建 hello.txt",
        ),
        # amendment 的 data 嵌套形态
        (
            json.dumps(
                {
                    "speech": "等等，先停一下。",
                    "delegation": {
                        "type": "amendment",
                        "data": {
                            "instructions": "改成表格",
                            "target_task_id": "task-001",
                            "revision": 2,
                        },
                    },
                },
                ensure_ascii=False,
            ),
            "改成表格",
        ),
    ],
)
def test_parse_delegation_accepts_flat_and_nested_data(
    raw: str, expected_instructions: str
) -> None:
    """B1：两种 delegation 形态（角色卡嵌套 data 与适配器平铺）都能解析。"""
    turn = OpenAICompatibleDialogueModel._parse_output(raw)
    assert turn.speech == "这事我插不上手。" or turn.speech == "等等，先停一下。"
    assert turn.delegation is not None
    assert turn.delegation.instructions == expected_instructions
