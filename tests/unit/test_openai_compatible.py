import json
import logging

import pytest
from httpx import AsyncClient, Request, Response
from httpx._transports.mock import MockTransport

from pair_harness.adapters.dialogue.openai_compatible import (
    OpenAICompatibleDialogueModel,
    UnusableSpeechError,
)
from pair_harness.core.contracts import (
    DialogueRequest,
    MemoryDraft,
    Message,
    MessageKind,
    MessageSource,
    ProjectRuntimeContext,
)


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


# ---------------------------------------------------------------------------
# V0.3.9（V039-S4-019）：不可用输出、是否重试、最终来源按 INFO 可数。
# 真实证据 A02/sidecar.log 只有 79 条「输出不可用（empty）」WARNING，缺少
# INFO，无法判定空白输出之后走的是重试还是别的路径；下面锁定日志事实。
# ---------------------------------------------------------------------------


_LOGGER_NAME = "pair_harness.adapters.dialogue.openai_compatible"


def _info_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _LOGGER_NAME and record.levelno == logging.INFO
    ]


def _stream_transport(contents: list[str]):
    """按请求顺序返回 content 分片的 SSE 传输（每次请求取一项）。"""

    def handler(request: Request) -> Response:
        content = contents.pop(0)
        data = json.dumps(
            {"choices": [{"delta": {"content": content}}]}, ensure_ascii=False
        )
        return Response(200, content=f"data: {data}\ndata: [DONE]\n".encode("utf-8"))

    return handler


@pytest.mark.asyncio
async def test_stream_reply_logs_empty_output_retry_and_final_source(caplog) -> None:
    """空输出后重试成功：INFO 必须记下不可用输出、重试与最终来源。

    第一次真实请求返回纯空白（A02 证据里的形状），第二次返回可用 JSON。
    修复前只有一条无法归因的 WARNING；修复后一次额外计费往返可数。
    """
    requests: list[dict] = []
    inner = _stream_transport(["   ", '{"speech": "好呀", "delegate": false}'])

    def handler(request: Request) -> Response:
        requests.append(json.loads(request.content))
        return inner(request)

    model = _deepseek_model(handler)
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=_user_message(),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        events = [event async for event in model.stream_reply(request)]

    finals = [event for event in events if event.type == "character.final"]
    assert len(finals) == 1
    assert finals[0].turn.speech == "好呀"
    assert len(requests) == 2

    messages = _info_messages(caplog)
    assert any(
        "角色对话模型输出不可用，重试真实模型" in message
        and "category=empty" in message
        and "attempt=0→1" in message
        and "原始输出字符数=3" in message
        for message in messages
    )
    assert any(
        "角色对话回合输出来源：空输出重试第 1 次" in message and "speech 字符数=2" in message
        for message in messages
    )
    assert not [message for message in messages if "不再重试" in message]


@pytest.mark.asyncio
async def test_stream_reply_logs_blocked_retry_reason_when_attempts_exhausted(
    caplog,
) -> None:
    """重试耗尽：两次重试各留一条 INFO，最后一次说明不再重试的原因。"""
    requests: list[dict] = []
    inner = _stream_transport([" ", " ", " "])

    def handler(request: Request) -> Response:
        requests.append(json.loads(request.content))
        return inner(request)

    model = _deepseek_model(handler)
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=_user_message(),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        with pytest.raises(UnusableSpeechError, match="输出为空"):
            [event async for event in model.stream_reply(request)]

    assert len(requests) == 3
    messages = _info_messages(caplog)
    assert len([m for m in messages if "重试真实模型" in m]) == 2
    assert [
        m for m in messages if "不再重试" in m and "重试已达上限" in m and "attempt=2" in m
    ]
    # 没有可用输出，就没有「最终来源」这一条
    assert not [m for m in messages if "角色对话回合输出来源" in m]


@pytest.mark.asyncio
async def test_stream_reply_does_not_retry_when_speech_already_streamed(caplog) -> None:
    """已上屏半截正文后解析失败：不重试并记下原因，真实失败继续抛出。"""
    requests: list[dict] = []
    inner = _stream_transport(['{"speech": "你好'])

    def handler(request: Request) -> Response:
        requests.append(json.loads(request.content))
        return inner(request)

    model = _deepseek_model(handler)
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=_user_message(),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        with pytest.raises(UnusableSpeechError, match="JSON 截断"):
            [event async for event in model.stream_reply(request)]

    assert len(requests) == 1
    messages = _info_messages(caplog)
    assert [
        m
        for m in messages
        if "不再重试" in m and "已有 speech 增量上屏" in m and "category=truncated" in m
    ]


@pytest.mark.asyncio
async def test_stream_reply_logs_non_deepseek_endpoint_retry_block(caplog) -> None:
    """非 DeepSeek 端点不做空输出重试：原因必须落盘，失败如实抛出。"""
    requests: list[dict] = []
    inner = _stream_transport(["   "])

    def handler(request: Request) -> Response:
        requests.append(json.loads(request.content))
        return inner(request)

    client = AsyncClient(base_url="http://test", transport=MockTransport(handler))
    model = OpenAICompatibleDialogueModel(
        base_url="http://test",
        api_key="test-key",
        model="test-model",
        client=client,
    )
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=_user_message(),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        with pytest.raises(UnusableSpeechError, match="输出为空"):
            [event async for event in model.stream_reply(request)]

    assert len(requests) == 1
    messages = _info_messages(caplog)
    assert [m for m in messages if "不再重试" in m and "非 DeepSeek 结构化端点" in m]
    await client.aclose()


# ---------------------------------------------------------------------------
# V0.3.9（V039-S4-003）：可选 memory 字段的协议一致性检查。
# 要不要记、记什么由模型自己判断；代码只查形状，不猜语义、不丢弃坏条目。
# ---------------------------------------------------------------------------


def test_parse_output_memory_defaults_to_empty_tuple() -> None:
    """缺省 memory（键不存在，含纯台词输出）＝ 本轮没有要记的内容，不是失败。

    显式 null 不算缺省，见 test_parse_output_rejects_malformed_memory_shapes。
    """
    json_turn = OpenAICompatibleDialogueModel._parse_output(
        '{"speech": "好呀", "delegate": false}'
    )
    assert json_turn.memory == ()

    plain_turn = OpenAICompatibleDialogueModel._parse_output("你好，我一直在。")
    assert plain_turn.memory == ()


def test_parse_output_memory_keeps_single_entry_verbatim() -> None:
    """单条 memory：内容原样交给 MemoryDraft，代码不改写、不摘要。"""
    content = {"用户偏好": "回复简短", "nested": {"tags": ["a", "b"], "n": 3}}
    turn = OpenAICompatibleDialogueModel._parse_output(
        json.dumps(
            {"speech": "记下了。", "delegate": False, "memory": [{"content": content}]},
            ensure_ascii=False,
        )
    )
    assert isinstance(turn.memory, tuple)
    assert len(turn.memory) == 1
    assert isinstance(turn.memory[0], MemoryDraft)
    assert turn.memory[0].content == content


def test_parse_output_memory_keeps_multiple_entries_in_order() -> None:
    turn = OpenAICompatibleDialogueModel._parse_output(
        json.dumps(
            {
                "speech": "都记下了。",
                "delegate": False,
                "memory": [
                    {"content": {"第一": 1}},
                    {"content": {"第二": 2, "细节": {"x": [1, 2, 3]}}},
                ],
            },
            ensure_ascii=False,
        )
    )
    assert [draft.content for draft in turn.memory] == [
        {"第一": 1},
        {"第二": 2, "细节": {"x": [1, 2, 3]}},
    ]


@pytest.mark.parametrize(
    "raw, expected_message",
    [
        # memory 不是数组（显式 null 属于「存在且非数组」，不与缺省等同）
        ('{"speech": "好呀", "memory": null}', "memory 必须是数组"),
        ('{"speech": "好呀", "memory": {"content": {"a": 1}}}', "memory 必须是数组"),
        ('{"speech": "好呀", "memory": "记住这件事"}', "memory 必须是数组"),
        # 元素不是对象
        ('{"speech": "好呀", "memory": ["记住这件事"]}', "memory[0] 必须是对象"),
        # content 缺失或不是对象
        (
            '{"speech": "好呀", "memory": [{"text": "记住这件事"}]}',
            "memory[0].content 必须是对象",
        ),
        (
            '{"speech": "好呀", "memory": [{"content": "记住这件事"}]}',
            "memory[0].content 必须是对象",
        ),
        ('{"speech": "好呀", "memory": [{"content": ["a"]}]}', "memory[0].content 必须是对象"),
        # content 为空对象违反契约（MemoryDraft.content min_length=1），如实失败
        ('{"speech": "好呀", "memory": [{"content": {}}]}', "MemoryDraft"),
        # 第 2 条坏：已经合法的第 1 条不得被当成部分成功而静默保留
        (
            '{"speech": "好呀", "memory": [{"content": {"a": 1}}, "坏条目"]}',
            "memory[1] 必须是对象",
        ),
    ],
)
def test_parse_output_rejects_malformed_memory_shapes(
    raw: str, expected_message: str
) -> None:
    """坏形状如实抛 ValueError：不跳过、不改写、不整体丢弃。"""
    with pytest.raises(ValueError) as exc_info:
        OpenAICompatibleDialogueModel._parse_output(raw)
    assert expected_message in str(exc_info.value)


def test_public_parse_output_does_not_swallow_malformed_memory() -> None:
    """公开解析入口（Codex 适配器共用）同样如实抛出，不吞成 delegation_missed。"""
    model = OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="test-key", model="test-model"
    )
    with pytest.raises(ValueError) as exc_info:
        model.parse_output('{"speech": "好呀", "delegate": false, "memory": 5}')
    assert "memory 必须是数组" in str(exc_info.value)

    # 缺省（键不存在）与显式 null 必须分开：前者合法为空元组
    turn = model.parse_output('{"speech": "好呀", "delegate": false}')
    assert turn.memory == ()
    with pytest.raises(ValueError) as null_exc:
        model.parse_output('{"speech": "好呀", "delegate": false, "memory": null}')
    assert "memory 必须是数组" in str(null_exc.value)


@pytest.mark.asyncio
async def test_stream_reply_carries_memory_from_retried_attempt(caplog) -> None:
    """空输出重试后可用输出来自第二次请求；其 memory 必须随最终回合保留。"""
    requests: list[dict] = []
    second = json.dumps(
        {
            "speech": "好呀",
            "delegate": False,
            "memory": [{"content": {"从重试记住": True}}],
        },
        ensure_ascii=False,
    )
    inner = _stream_transport(["   ", second])

    def handler(request: Request) -> Response:
        requests.append(json.loads(request.content))
        return inner(request)

    model = _deepseek_model(handler)
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=_user_message(),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        events = [event async for event in model.stream_reply(request)]

    finals = [event for event in events if event.type == "character.final"]
    assert len(finals) == 1
    assert len(requests) == 2
    assert [draft.content for draft in finals[0].turn.memory] == [{"从重试记住": True}]
    assert [
        m
        for m in _info_messages(caplog)
        if "角色对话回合输出来源：空输出重试第 1 次" in m and "memory 条数=1" in m
    ]


@pytest.mark.asyncio
async def test_stream_reply_carries_memory_from_delegation_retry() -> None:
    """委派纠偏重试后的回合同样保留该次输出的 memory（字段不在重试路径丢失）。"""
    bodies = [
        json.dumps({"speech": "交给搭档。", "delegate": True}, ensure_ascii=False),
        json.dumps(
            {
                "speech": "交给搭档。",
                "delegate": True,
                "delegation": {"type": "task", "instructions": "创建 hello.txt"},
                "memory": [{"content": {"任务已委派": "hello.txt"}}],
            },
            ensure_ascii=False,
        ),
    ]
    inner = _stream_transport(bodies)

    def handler(request: Request) -> Response:
        return inner(request)

    model = _deepseek_model(handler)
    request = DialogueRequest(
        pair_id="phainon_ancient_machine",
        conversation_id="c",
        user_message=_user_message("请让搭档创建 hello.txt"),
        runtime_context=ProjectRuntimeContext(
            project_name="项目",
            project_abs_dir="C:/project",
            conversation_mode="collaboration",
        ),
    )
    events = [event async for event in model.stream_reply(request)]
    finals = [event for event in events if event.type == "character.final"]
    assert len(finals) == 1
    turn = finals[0].turn
    assert turn.delegation is not None
    assert turn.delegation.instructions == "创建 hello.txt"
    assert [draft.content for draft in turn.memory] == [{"任务已委派": "hello.txt"}]
