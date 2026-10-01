import json

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from pair_harness.adapters.dialogue.incremental_json import IncrementalJsonSpeechParser
from pair_harness.adapters.dialogue.openai_compatible import (
    DialogueProtocolError,
    OpenAICompatibleDialogueModel,
)
from pair_harness.core.contracts import DialogueRequest, Message, MessageKind, MessageSource

PAIR_ID = "phainon_ancient_machine"


def make_request() -> DialogueRequest:
    message = Message(
        conversation_id="c",
        pair_id=PAIR_ID,
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="你好",
    )
    return DialogueRequest(pair_id=PAIR_ID, conversation_id="c", user_message=message)


def json_delta_chunks(payload: dict, split_every: int | None = None) -> list[str]:
    """把 JSON 对象序列化为 SSE content 分片序列（可指定切分粒度）。"""
    raw = json.dumps(payload, ensure_ascii=False)
    if split_every is None:
        return [raw]
    return [raw[i : i + split_every] for i in range(0, len(raw), split_every)]


def stream_transport(chunks: list[str], *, reasoning: str = "") -> MockTransport:
    """Chat Completions SSE 流；reasoning 非空时随首个分片下发 reasoning_content。"""

    def handler(_request: Request) -> Response:
        lines = []
        for index, chunk in enumerate(chunks):
            delta = {"content": chunk}
            if reasoning and index == 0:
                delta = {"reasoning_content": reasoning, **delta}
            data = json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False)
            lines.append(f"data: {data}\n\n".encode("utf-8"))
        lines.append(b"data: [DONE]\n\n")
        return Response(
            200, headers={"content-type": "text/event-stream"}, content=b"".join(lines)
        )

    return MockTransport(handler)


# ---- 解析器单元测试 ----


@pytest.mark.parametrize(
    "chunks",
    [
        # 原始 JSON 分块
        ['{"speech": "你好，', '伙伴。", "delegation": null}'],
        # 键被截断在块边界
        ['{"speec', 'h": "你好"}'],
        # 值被截断在块边界
        ['{"speech": "你好', '，伙伴"}'],
        # 转义字符被截断
        ['{"speech": "他说\\"', '好\\""}'],
        ['{"speech": "第一行\\', 'n第二行\\u4f', '60"}'],
        # 其他字段的字符串值里出现 "speech" 字样
        ['{"note": "\\"speech\\": \\"假的", ', '"speech": "真的"}'],
        # 逐字符推进
        json_delta_chunks({"speech": "你好，伙伴"}, 1),
        json_delta_chunks({"speech": "引号\"与\\n换行"}, 1),
    ],
)
def test_parser_extracts_clean_speech_across_chunk_boundaries(chunks: list[str]) -> None:
    parser = IncrementalJsonSpeechParser()
    emitted = ""
    for chunk in chunks:
        emitted += parser.feed(chunk)
    raw = "".join(chunks)
    expected = json.loads(raw).get("speech", "")
    # 转义序列解码后上屏，增量预览即最终值
    assert parser.speech == expected
    assert emitted == expected


def test_parser_no_speech_key_extracts_nothing() -> None:
    """裸裁决 JSON（无 speech 字段）：不上屏增量。"""
    parser = IncrementalJsonSpeechParser()
    deltas = []
    for chunk in json_delta_chunks({"allow": True, "reason": "低风险"}, 5):
        deltas.append(parser.feed(chunk))
    assert all(d == "" for d in deltas)
    assert parser.speech == ""


# ---- 适配器流式事件序列 ----


@pytest.mark.asyncio
async def test_stream_yields_clean_speech_deltas_and_raw_completed() -> None:
    """JSON 流：speech.delta 只含干净台词；speech.completed 携带完整 raw。"""
    payload = {"speech": "这事得交给古代机械。", "delegation": None}
    client = AsyncClient(
        base_url="http://test",
        transport=stream_transport(json_delta_chunks(payload, 4)),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="k", model="m", client=client
    )

    events = [event async for event in model.stream_reply(make_request())]

    deltas = [e.delta for e in events if e.type == "speech.delta"]
    assert "".join(deltas) == "这事得交给古代机械。"
    # 干净台词：不含 JSON 键名与引号
    assert all("speech" not in (d or "") and '"' not in (d or "") for d in deltas)
    completed = [e for e in events if e.type == "speech.completed"]
    assert len(completed) == 1
    assert json.loads(completed[0].raw or "{}") == payload
    finals = [e for e in events if e.type == "character.final"]
    assert len(finals) == 1
    assert finals[0].turn.speech == "这事得交给古代机械。"
    assert finals[0].turn.delegation is None
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_emits_reasoning_lifecycle_events() -> None:
    """reasoning_content 走独立通道：started → delta → completed。"""
    payload = {"speech": "好，我们继续。"}
    client = AsyncClient(
        base_url="http://test",
        transport=stream_transport(json_delta_chunks(payload, 3), reasoning="我在思考"),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="k", model="m", client=client
    )

    events = [event async for event in model.stream_reply(make_request())]

    types = [e.type for e in events]
    assert "reasoning.started" in types
    assert "reasoning.delta" in types
    assert types.index("reasoning.started") < types.index("reasoning.delta") < types.index(
        "reasoning.completed"
    )
    reasoning = "".join(e.delta or "" for e in events if e.type == "reasoning.delta")
    assert reasoning == "我在思考"
    finals = [e for e in events if e.type == "character.final"]
    assert finals[0].turn.reasoning == "我在思考"
    assert finals[0].turn.speech == "好，我们继续。"
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_rejects_truncated_json_tail() -> None:
    """JSON 收尾截断时直接失败，不能把增量预览当成完整协议结果。"""
    client = AsyncClient(
        base_url="http://test",
        transport=stream_transport(['{"speech": "正式回复。", "delegation":']),
    )
    model = OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="k", model="m", client=client
    )

    with pytest.raises(DialogueProtocolError, match="不是 JSON"):
        _ = [event async for event in model.stream_reply(make_request())]
    await client.aclose()
