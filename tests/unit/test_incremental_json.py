"""V0.2 M2：增量 JSON 解析器与对话流式事件序列（问题 10）。

- speech.delta 只含干净台词（不再闪烁 JSON 键名/引号）；
- reasoning 走独立通道（reasoning.started/delta/completed）；
- speech.completed 携带完整原始输出（raw 供技术详情与审查智能体）；
- 非 JSON 降级输出整段作为台词增量。
"""

import json

import pytest
from httpx import AsyncClient, Request, Response
from httpx._transports.mock import MockTransport

from pair_harness.adapters.dialogue.incremental_json import IncrementalJsonSpeechParser
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
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


def stream_transport(chunks: list[str]) -> MockTransport:
    def handler(_request: Request) -> Response:
        lines = []
        for chunk in chunks:
            data = (
                '{"choices":[{"delta":{"content":"'
                + chunk.replace('"', '\\"')
                + '"}}]}'
            )
            lines.append(f"data: {data}\n".encode("utf-8"))
        lines.append(b"data: [DONE]\n")
        return Response(200, content=b"".join(lines))

    return MockTransport(handler)


def reasoning_stream_transport(content_chunks: list[str]) -> MockTransport:
    """同时带 reasoning_content（仅首个分片）与 content 的流。"""

    def handler(_request: Request) -> Response:
        lines = []
        for index, chunk in enumerate(content_chunks):
            reasoning = '"reasoning_content":"我在思考",' if index == 0 else ""
            data = (
                '{"choices":[{"delta":{'
                + reasoning
                + '"content":"' + chunk.replace('"', '\\"') + '"}}]}'
            )
            lines.append(f"data: {data}\n".encode("utf-8"))
        lines.append(b"data: [DONE]\n")
        return Response(200, content=b"".join(lines))

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
        # 逐字符推进
        json_delta_chunks({"speech": "你好，伙伴"}, 1),
    ],
)
def test_parser_extracts_clean_speech_across_chunk_boundaries(chunks: list[str]) -> None:
    parser = IncrementalJsonSpeechParser()
    emitted = ""
    for chunk in chunks:
        emitted += parser.feed(chunk)
    raw = "".join(chunks)
    expected = json.loads(raw).get("speech", "")
    # 无转义时增量预览即最终值；含转义时预览呈原始转义序列，final 覆盖
    assert parser.full_object is not None
    assert parser.speech == expected
    assert emitted == expected or "\\" in emitted


def test_parser_plain_text_output_emits_raw_as_speech() -> None:
    """非 JSON 输出（角色卡降级/纯台词）：整段增量作为台词。"""
    parser = IncrementalJsonSpeechParser()
    deltas = []
    for chunk in ["这就", "去办。"]:
        deltas.append(parser.feed(chunk))
    assert deltas == ["这就", "去办。"]
    assert parser.speech == "这就去办。"
    assert parser.full_object is None


def test_parser_no_speech_key_extracts_nothing_but_keeps_raw() -> None:
    """裸裁决 JSON（无 speech 字段）：不上屏增量，完整输出留待 review 复用。"""
    parser = IncrementalJsonSpeechParser()
    deltas = []
    for chunk in json_delta_chunks({"allow": True, "reason": "低风险"}, 5):
        deltas.append(parser.feed(chunk))
    assert all(d == "" for d in deltas)
    assert parser.speech == ""
    assert parser.full_object is not None
    assert "allow" in parser.raw


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
        transport=reasoning_stream_transport(json_delta_chunks(payload, 3)),
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
async def test_stream_plain_text_falls_back_to_raw_deltas() -> None:
    """非 JSON 输出：整段作为台词增量，final 台词一致。"""
    client = AsyncClient(
        base_url="http://test", transport=stream_transport(["这就", "去办。"])
    )
    model = OpenAICompatibleDialogueModel(
        base_url="http://test", api_key="k", model="m", client=client
    )

    events = [event async for event in model.stream_reply(make_request())]

    deltas = [e.delta for e in events if e.type == "speech.delta"]
    assert deltas == ["这就", "去办。"]
    finals = [e for e in events if e.type == "character.final"]
    assert finals[0].turn.speech == "这就去办。"
    await client.aclose()
