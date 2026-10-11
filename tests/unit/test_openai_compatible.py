import json

import pytest
from httpx import AsyncClient, ConnectError, HTTPStatusError, MockTransport, ReadTimeout, Request, Response

from pair_harness.adapters.dialogue import openai_compatible

from pair_harness.adapters.dialogue.openai_compatible import (
    DialogueProtocolError,
    OpenAICompatibleDialogueModel,
)
from pair_harness.core.contracts import (
    DialogueRequest,
    Message,
    MessageKind,
    MessageSource,
    TaskAmendmentDraft,
    TaskRequestDraft,
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
async def test_generate_title_uses_assistant_only_non_streaming_request() -> None:
    captured: list[dict] = []

    def handler(request: Request) -> Response:
        body = json.loads(request.content)
        captured.append(body)
        return Response(
            200,
            json={"choices": [{"message": {"content": '{"title": "整理今天的工作"}'}}]},
        )

    client = AsyncClient(base_url="http://test", transport=MockTransport(handler))
    model = OpenAICompatibleDialogueModel(
        base_url="http://test",
        api_key="test-key",
        model="test-model",
        client=client,
    )
    context = (
        _user_message("请帮我整理今天的工作"),
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


def test_parse_output_marks_delegation_missed_when_delegate_has_no_delegation() -> None:
    with pytest.raises(DialogueProtocolError, match="缺少 delegate 布尔字段"):
        OpenAICompatibleDialogueModel.parse_output('{"speech":"交给搭档。"}')
    turn = OpenAICompatibleDialogueModel.parse_output('{"speech":"交给搭档。","delegate":true}')
    assert turn.delegation_missed is True
    assert turn.delegation is None
    assert turn.speech == "交给搭档。"


@pytest.mark.parametrize(
    ("delegation", "expected"),
    [
        (
            {"type": "task", "instructions": "整理报告", "constraints": ["markdown"]},
            TaskRequestDraft(instructions="整理报告", constraints=("markdown",)),
        ),
        (
            {
                "type": "amendment",
                "instructions": "改用 shutil",
                "target_task_id": "t-9",
                "revision": 2,
            },
            TaskAmendmentDraft(instructions="改用 shutil", target_task_id="t-9", revision=2),
        ),
    ],
)
def test_parse_output_reads_delegation(delegation: dict, expected: object) -> None:
    raw = json.dumps(
        {"speech": "古代机械，交给你了。", "delegate": True, "delegation": delegation},
        ensure_ascii=False,
    )
    turn = OpenAICompatibleDialogueModel.parse_output(raw)
    assert turn.speech == "古代机械，交给你了。"
    assert turn.delegation == expected
    assert turn.delegation_missed is False


@pytest.mark.parametrize(
    "raw",
    [
        # 原始输出为空
        "   ",
        # 合法 JSON 内 speech 是占位标点
        '{"speech":"……"}',
        # JSON 截断（值尚未开始 / 值未闭合）
        '{"speech":',
        '{"speech": "你好',
    ],
)
def test_parse_output_rejects_unusable_output(raw: str) -> None:
    with pytest.raises(DialogueProtocolError):
        OpenAICompatibleDialogueModel.parse_output(raw)


@pytest.mark.parametrize(
    "memory",
    [
        # 键缺省表示本轮没有要记的内容
        None,
        [{"content": {"用户偏好": "回复简短", "nested": {"tags": ["a", "b"], "n": 3}}}],
        [{"content": {"第一": 1}}, {"content": {"第二": 2, "细节": {"x": [1, 2, 3]}}}],
    ],
)
def test_parse_output_keeps_memory_entries_verbatim_in_order(memory: list | None) -> None:
    output: dict = {"speech": "记下了。", "delegate": False}
    if memory is not None:
        output["memory"] = memory
    turn = OpenAICompatibleDialogueModel.parse_output(json.dumps(output, ensure_ascii=False))
    assert [draft.content for draft in turn.memory] == [
        entry["content"] for entry in memory or ()
    ]


@pytest.mark.parametrize(
    "raw, expected_message",
    [
        # memory 不是数组（显式 null 属于「存在且非数组」，不与缺省等同）
        ('{"speech": "好呀", "delegate": false, "memory": null}', "memory 必须是数组"),
        ('{"speech": "好呀", "delegate": false, "memory": {"content": {"a": 1}}}', "memory 必须是数组"),
        ('{"speech": "好呀", "delegate": false, "memory": "记住这件事"}', "memory 必须是数组"),
        # 元素不是对象
        ('{"speech": "好呀", "delegate": false, "memory": ["记住这件事"]}', "memory[0] 必须是对象"),
        # content 缺失或不是对象
        (
            '{"speech": "好呀", "delegate": false, "memory": [{"text": "记住这件事"}]}',
            "memory[0].content 必须是对象",
        ),
        (
            '{"speech": "好呀", "delegate": false, "memory": [{"content": "记住这件事"}]}',
            "memory[0].content 必须是对象",
        ),
        ('{"speech": "好呀", "delegate": false, "memory": [{"content": ["a"]}]}', "memory[0].content 必须是对象"),
        # content 为空对象违反契约（MemoryDraft.content min_length=1），如实失败
        ('{"speech": "好呀", "delegate": false, "memory": [{"content": {}}]}', "MemoryDraft"),
        # 第 2 条坏：已经合法的第 1 条不得被当成部分成功而静默保留
        (
            '{"speech": "好呀", "delegate": false, "memory": [{"content": {"a": 1}}, "坏条目"]}',
            "memory[1] 必须是对象",
        ),
    ],
)
def test_parse_output_rejects_malformed_memory_shapes(
    raw: str, expected_message: str
) -> None:
    with pytest.raises(ValueError) as exc_info:
        OpenAICompatibleDialogueModel.parse_output(raw)
    assert expected_message in str(exc_info.value)


def _raw_sse_model(data_lines: list[str]) -> OpenAICompatibleDialogueModel:
    def handler(request: Request) -> Response:
        body = "".join(f"data: {line}\n\n" for line in data_lines) + "data: [DONE]\n\n"
        return Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode("utf-8")
        )

    client = AsyncClient(base_url="http://test", transport=MockTransport(handler))
    return OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="test-key", model="test-model", client=client
    )


def _plain_request() -> DialogueRequest:
    return DialogueRequest(
        pair_id="phainon_ancient_machine", conversation_id="c", user_message=_user_message()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_line",
    ["not json", '{"error": {"message": "upstream 502"}}', '{"choices": [{"delta": null}]}'],
)
async def test_stream_reply_fails_on_malformed_chunk_with_raw_data(bad_line: str) -> None:
    model = _raw_sse_model([json.dumps({"choices": [{"delta": {"content": '{"delegate":false,"speech":"好'}}]}), bad_line])
    with pytest.raises(DialogueProtocolError) as raised:
        [event async for event in model.stream_reply(_plain_request())]
    assert bad_line[:10] in str(raised.value)


@pytest.mark.asyncio
async def test_stream_reply_skips_chunk_with_empty_choices() -> None:
    """OpenAI 协议允许 choices 为空的数据块（如 usage 统计块），它没有增量。"""
    model = _raw_sse_model(
        [
            '{"choices":[{"delta":{"content":"{\\"speech\\": \\"tn\\", \\"delegate\\": false}"}}]}',
            '{"choices":[],"usage":{"total_tokens":3}}',
        ]
    )
    events = [event async for event in model.stream_reply(_plain_request())]
    # "tn" 是正常台词，不能被当成占位标点
    assert events[-1].turn is not None and events[-1].turn.speech == "tn"


@pytest.mark.asyncio
@pytest.mark.parametrize(("stream", "failure"), [
    (stream, failure)
    for stream in (True, False)
    for failure in ("connect", "timeout", "429", "503", "content_type", "empty_response", "invalid_envelope", "empty", "whitespace", "invalid")
] + [(True, "missing_delegate"), (True, "invalid_delegate")])
async def test_requests_retry_with_identical_body_and_exponential_backoff(
    stream: bool, failure: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bodies: list[dict] = []
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(openai_compatible.asyncio, "sleep", sleep)

    def handler(request: Request) -> Response:
        bodies.append(json.loads(request.content))
        if len(bodies) <= 7:
            if failure == "connect":
                raise ConnectError("connection interrupted", request=request)
            if failure == "timeout":
                raise ReadTimeout("read timed out", request=request)
            if failure in ("429", "503"):
                return Response(int(failure), text="upstream unavailable")
            if failure == "content_type":
                return Response(200, headers={"content-type": "text/plain"}, text="upstream returned a plain response")
            if failure == "empty_response":
                return Response(200, headers={"content-type": "text/event-stream"} if stream else {}, text="")
            if failure == "invalid_envelope":
                return Response(200, headers={"content-type": "text/event-stream"} if stream else {}, text="data: broken JSON\n\n" if stream else "broken JSON")
            content = {
                "empty": "", "whitespace": "   ", "invalid": "broken JSON",
                "missing_delegate": '{"speech":"待验证台词"}',
                "invalid_delegate": '{"speech":"待验证台词","delegate":"false"}',
            }[failure]
        else:
            content = '{"speech":"完成","delegate":false}'
        if stream:
            chunk = json.dumps({"choices": [{"delta": {"content": content}}]})
            return Response(200, headers={"content-type": "text/event-stream"}, text=f"data: {chunk}\n\ndata: [DONE]\n\n")
        return Response(200, json={"choices": [{"message": {"content": content}}]})

    async with AsyncClient(base_url="https://api.deepseek.com", transport=MockTransport(handler)) as client:
        model = OpenAICompatibleDialogueModel(base_url="https://api.deepseek.com", model="test-model", client=client, temperature=0.2)
        if stream:
            events = [event async for event in model.stream_reply(_plain_request())]
            assert events[-1].type == "character.final"
            assert [event.delta for event in events if event.type == "speech.delta"] == ["完成"]
        else:
            assert await model.complete_json(system="JSON", user="hello", max_tokens=128) == {"speech": "完成", "delegate": False}
    assert delays == [1, 2, 4, 8, 16, 32, 60]
    assert len(bodies) == 8
    assert all(body == bodies[0] for body in bodies)
    assert bodies[0]["temperature"] == 1
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert bodies[0]["thinking"] == {"type": "disabled"}
    retry_logs = [record.message for record in caplog.records if "对话请求重试" in record.message]
    assert len(retry_logs) == 7
    assert "7/7" in retry_logs[-1] and "60 秒" in retry_logs[-1] and "触发条件" in retry_logs[-1]
    assert all("https://api.deepseek.com" not in message for message in retry_logs)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_requests_do_not_retry_nontransient_http_failure(stream: bool, status: int, caplog: pytest.LogCaptureFixture) -> None:
    calls = 0
    raw = "request rejected " + "详情" * 1500

    def handler(request: Request) -> Response:
        nonlocal calls
        calls += 1
        return Response(status, text=raw)

    async with AsyncClient(base_url="http://test", transport=MockTransport(handler)) as client:
        model = OpenAICompatibleDialogueModel(client=client)
        with pytest.raises(HTTPStatusError) as raised:
            if stream:
                [event async for event in model.stream_reply(_plain_request())]
            else:
                await model.complete_json(system="JSON", user="hello", max_tokens=128)
    assert raised.value.response.status_code == status
    assert calls == 1
    assert any(repr(raw) in record.message for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ['{"delegate":false,"speech":"已显示","memory":null}', '{"delegate":false,"speech":"已显示"'])
async def test_stream_reply_preserves_visible_speech_and_final_raw_on_failure(raw: str, caplog: pytest.LogCaptureFixture) -> None:
    model = _raw_sse_model([json.dumps({"choices": [{"delta": {"content": raw}}]})])
    events = []
    with pytest.raises(DialogueProtocolError):
        async for event in model.stream_reply(_plain_request()):
            events.append(event)
    assert [event.delta for event in events if event.type == "speech.delta"] == ["已显示"]
    assert events[-1].type == "speech.completed" and events[-1].raw == raw
    assert not any(event.type == "character.final" for event in events)
    assert not any("对话请求重试" in record.message for record in caplog.records)
    assert any(repr(raw) in record.message for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize("failure", ["model_output", "http", "content_type"])
async def test_requests_exhaust_retries_and_report_final_output(
    stream: bool, failure: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0
    delays = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(openai_compatible.asyncio, "sleep", sleep)

    def handler(request: Request) -> Response:
        nonlocal calls
        calls += 1
        raw = f"invalid output {calls}" + "详情" * 1500
        if failure == "http":
            return Response(503, text=raw)
        if failure == "content_type":
            return Response(200, headers={"content-type": "text/plain"}, text=raw)
        if stream:
            chunk = json.dumps({"choices": [{"delta": {"content": raw}}]})
            return Response(200, headers={"content-type": "text/event-stream"}, text=f"data: {chunk}\n\ndata: [DONE]\n\n")
        return Response(200, json={"choices": [{"message": {"content": raw}}]})

    async with AsyncClient(base_url="http://test", transport=MockTransport(handler)) as client:
        model = OpenAICompatibleDialogueModel(client=client)
        expected = HTTPStatusError if failure == "http" else openai_compatible.SSEError if stream and failure == "content_type" else DialogueProtocolError
        with pytest.raises(expected):
            if stream:
                [event async for event in model.stream_reply(_plain_request())]
            else:
                await model.complete_json(system="JSON", user="hello", max_tokens=128)
    assert calls == 8 and delays == [1, 2, 4, 8, 16, 32, 60]
    assert any("最后原始输出" in record.message and "invalid output 8" + "详情" * 1500 in record.message for record in caplog.records)
