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
