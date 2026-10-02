import json

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from pair_harness.adapters.dialogue.openai_compatible import (
    DialogueProtocolError,
    OpenAICompatibleDialogueModel,
)
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.core.contracts import Message, MessageKind, MessageSource, PendingOperation

DELETE_OP = PendingOperation(tool_kind="shell", command="rm x", summary="删除文件")


def make_reviewer(content: str, bodies: list[dict] | None = None) -> DialogueModelReviewer:
    """审查模型的 Chat Completions 端点以 content 作为回复正文，请求体记入 bodies。"""

    def handler(request: Request) -> Response:
        if bodies is not None:
            bodies.append(json.loads(request.content))
        return Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        )

    client = AsyncClient(base_url="http://test", transport=MockTransport(handler))
    return DialogueModelReviewer(
        OpenAICompatibleDialogueModel(
            base_url="http://test", api_key="k", model="m", client=client
        )
    )


@pytest.mark.asyncio
async def test_dialogue_reviewer_fails_closed_on_invalid_json() -> None:
    """非 JSON 裁决直接抛错，由 ApprovalManager 的 review.failed 分支否决。"""
    with pytest.raises(DialogueProtocolError, match="不是 JSON"):
        await make_reviewer("这不是 JSON").review(DELETE_OP, [])


@pytest.mark.asyncio
async def test_dialogue_reviewer_rejects_non_boolean_allow() -> None:
    reviewer = make_reviewer('{"allow": "false", "reason": "", "suggestion": ""}')
    with pytest.raises(ValueError, match="allow 不是布尔值"):
        await reviewer.review(DELETE_OP, [])


@pytest.mark.asyncio
async def test_dialogue_reviewer_uses_only_latest_three_user_messages() -> None:
    bodies: list[dict] = []
    reviewer = make_reviewer('{"allow": true, "reason": "", "suggestion": ""}', bodies)

    context: list[Message] = []
    for i in range(5):
        context.append(
            Message(
                conversation_id="c",
                pair_id="phainon_ancient_machine",
                source=MessageSource.USER,
                kind=MessageKind.USER_TEXT,
                text=f"用户消息{i}",
            )
        )
        context.append(
            Message(
                conversation_id="c",
                pair_id="phainon_ancient_machine",
                source=MessageSource.CHARACTER,
                kind=MessageKind.CHARACTER_SPEECH,
                text=f"角色消息{i}",
            )
        )
    verdict = await reviewer.review(
        PendingOperation(tool_kind="shell", command="pytest", summary="运行测试"),
        context,
    )

    assert verdict.allow is True
    system, prompt = (message["content"] for message in bodies[0]["messages"])
    assert "用户消息0" not in prompt and "用户消息1" not in prompt
    assert all(f"用户消息{i}" in prompt for i in range(2, 5))
    assert "角色消息" not in prompt
    assert "是否直接要求或明确批准" in system
    assert bodies[0]["max_tokens"] == 512
