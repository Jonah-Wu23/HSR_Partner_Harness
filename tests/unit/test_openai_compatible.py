import json

import pytest
from httpx import AsyncClient, Request, Response
from httpx._transports.mock import MockTransport

from pair_harness.adapters.dialogue.openai_compatible import (
    OpenAICompatibleDialogueModel,
    UnusableSpeechError,
)
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


def _deepseek_model(handler) -> OpenAICompatibleDialogueModel:
    client = AsyncClient(base_url="https://api.deepseek.com", transport=MockTransport(handler))
    return OpenAICompatibleDialogueModel(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        client=client,
    )


def _user_message(text: str = "你好") -> Message:
    return Message(
        conversation_id="c",
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text=text,
    )


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


def test_public_parse_output_marks_delegation_missed_for_protocol_breach() -> None:
    """M6.1：公开解析入口对自报 delegate=true 却无 delegation 打真实失败标记。"""
    from pair_harness.core.contracts import ProjectRuntimeContext

    model = OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="test-key", model="test-model"
    )
    message = Message(
        conversation_id="c",
        pair_id="phainon_ancient_machine",
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="请让搭档检查项目文件",
    )
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=message,
        runtime_context=ProjectRuntimeContext(
            project_name="项目",
            project_abs_dir="C:/project",
            conversation_mode="collaboration",
        ),
    )
    turn = model.parse_output(
        '{"speech":"交给搭档。","delegate":true}', request=request
    )
    assert turn.delegation_missed is True
    assert turn.speech == "交给搭档。"


def test_public_parse_output_keeps_empty_body_failure() -> None:
    model = OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="test-key", model="test-model"
    )
    with pytest.raises(ValueError, match="可用 speech"):
        model.parse_output("   ")


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


# ---------------------------------------------------------------------------
# V0.3.3：不可用输出按「输出为空 / JSON 截断」分类，原始片段入本地日志，
# 空输出/截断 JSON 对 DeepSeek 结构化端点做有界重试（不合成结果）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected_category",
    [
        # 原始输出为空
        ("   ", "empty"),
        # 合法 JSON 内 speech 是占位标点
        ('{"speech":"……"}', "empty"),
        # 模型以 { 开头输出 JSON 但被截断（值尚未开始 / 值未闭合）
        ('{"speech":', "truncated"),
        ('{"speech": "你好', "truncated"),
    ],
)
def test_parse_output_classifies_unusable_output(
    raw: str, expected_category: str
) -> None:
    model = OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="test-key", model="test-model"
    )
    with pytest.raises(UnusableSpeechError) as exc_info:
        model.parse_output(raw)
    assert exc_info.value.category == expected_category
    if expected_category == "truncated":
        assert "JSON 截断" in str(exc_info.value)
    else:
        # 「输出为空」与「JSON 内占位标点」的文案落在可用 speech 说明上
        assert "speech" in str(exc_info.value)


@pytest.mark.asyncio
async def test_stream_reply_retries_empty_output_then_raises_bounded() -> None:
    """DeepSeek 结构化端点持续空输出：有界重试后仍失败才报「输出为空」。

    不合成结果：三次真实请求后直接抛错（初始 + 2 次有界重试）。
    """
    requests: list[dict] = []

    def handler(request: Request) -> Response:
        requests.append(json.loads(request.content))
        data = '{"choices":[{"delta":{"content":" "}}]}'
        return Response(
            200,
            content=f"data: {data}\ndata: [DONE]\n".encode("utf-8"),
        )

    model = _deepseek_model(handler)
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=_user_message(),
    )
    with pytest.raises(UnusableSpeechError, match="输出为空"):
        [event async for event in model.stream_reply(request)]
    assert len(requests) == 3
    # 重试时放宽供应商格式约束，仍请求真实模型
    assert all("response_format" not in r2 for r2 in requests[1:])


@pytest.mark.asyncio
async def test_stream_reply_recovers_after_truncated_json_retry() -> None:
    """首次输出 JSON 截断、尚无 speech 增量时，对有界重试后的正常结果放行。"""
    requests: list[dict] = []
    scripts = ['{"speech":', "好呀"]

    def handler(request: Request) -> Response:
        requests.append(json.loads(request.content))
        chunk = scripts.pop(0)
        data = json.dumps(
            {"choices": [{"delta": {"content": chunk}}]}, ensure_ascii=False
        )
        return Response(
            200,
            content=f"data: {data}\ndata: [DONE]\n".encode("utf-8"),
        )

    model = _deepseek_model(handler)
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=_user_message(),
    )
    events = [event async for event in model.stream_reply(request)]
    finals = [event for event in events if event.type == "character.final"]
    assert len(finals) == 1
    assert finals[0].turn.speech == "好呀"
    assert len(requests) == 2
