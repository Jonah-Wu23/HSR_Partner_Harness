from __future__ import annotations

import pytest

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.character_prompt_assembler import AssembledPrompt, DepthInjection
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    DialogueRequest,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    ProjectRef,
    ProjectRuntimeContext,
)
from pair_harness.core.orchestrator import ConversationOrchestrator, _conversation_turn_index
from tests.fakes import (
    FixedDialogueModel,
    RecordingCodingEngine,
    make_context,
    unexpected_approval,
)

PAIR_ID = "phainon_ancient_machine"


def _message(source: MessageSource, text: str, origin: MessageOrigin = MessageOrigin.USER) -> Message:
    return Message(
        conversation_id="c",
        pair_id=PAIR_ID,
        source=source,
        kind=(
            MessageKind.USER_TEXT
            if source == MessageSource.USER
            else MessageKind.CHARACTER_SPEECH
        ),
        text=text,
        origin=origin,
    )


def _assembled(*injections: DepthInjection) -> AssembledPrompt:
    return AssembledPrompt(
        system_text="角色提示词", modules=[], first_mes="", depth_injections=injections
    )


def make_model(resolver=None) -> OpenAICompatibleDialogueModel:
    return OpenAICompatibleDialogueModel(
        base_url="http://test",
        api_key="test-key",
        model="test-model",
        character_prompt_resolver=resolver,
    )


def make_request(
    *,
    recent: tuple[Message, ...] = (),
    turn_index: int = 0,
    runtime: ProjectRuntimeContext | None = None,
) -> DialogueRequest:
    user = _message(MessageSource.USER, "当前用户消息")
    return DialogueRequest(
        pair_id=PAIR_ID,
        conversation_id="c",
        user_message=user,
        recent_messages=recent,
        turn_index=turn_index,
        runtime_context=runtime,
    )


def _recent() -> tuple[Message, ...]:
    return (
        _message(MessageSource.CHARACTER, "a"),
        _message(MessageSource.USER, "b"),
        _message(MessageSource.CHARACTER, "c"),
    )


_RUNTIME = ProjectRuntimeContext(
    project_name="项目", project_abs_dir="C:/p", conversation_mode="collaboration"
)
_PROMPT = ("system", "<角色提示>")
_A = ("assistant", "a")
_B = ("user", "b")
_C = ("assistant", "c")


def _layout(messages: list[dict]) -> list[tuple[str, str]]:
    """系统提示与运行环境块换成占位，只比对消息顺序与注入位置。"""
    layout = []
    for message in messages:
        content = message["content"]
        if content.startswith("角色提示词"):
            content = "<角色提示>"
        elif "当前工作环境" in content:
            content = "<运行环境>"
        layout.append((message["role"], content))
    return layout


# 注入按 SillyTavern doChatInject 只计对话消息：同 (depth, role) 以换行合并为
# 一条，按 depth 降序逐组插到距末尾 depth 条之前，越界夹到最前；运行环境块与
# 当前用户消息始终在注入之后。
@pytest.mark.parametrize(
    ("injections", "expected"),
    [
        pytest.param((), [_PROMPT, _A, _B, _C], id="无注入"),
        pytest.param(
            (DepthInjection(depth=2, role="system", text="深层提示"),),
            [_PROMPT, _A, ("system", "深层提示"), _B, _C],
            id="depth2插到倒数第2条前",
        ),
        pytest.param(
            (DepthInjection(depth=0, role="user", text="末尾注入"),),
            [_PROMPT, _A, _B, _C, ("user", "末尾注入")],
            id="depth0追加到对话末尾",
        ),
        pytest.param(
            (DepthInjection(depth=9, role="system", text="最前注入"),),
            [("system", "最前注入"), _PROMPT, _A, _B, _C],
            id="越界夹到最前",
        ),
        pytest.param(
            (
                DepthInjection(depth=3, role="system", text="X"),
                DepthInjection(depth=3, role="system", text="Y"),
                DepthInjection(depth=3, role="assistant", text="Z"),
            ),
            [_PROMPT, ("system", "X\nY"), ("assistant", "Z"), _A, _B, _C],
            id="同depth同role合并",
        ),
        pytest.param(
            (
                DepthInjection(depth=3, role="system", text="I3"),
                DepthInjection(depth=1, role="assistant", text="I1"),
            ),
            [_PROMPT, ("system", "I3"), _A, _B, ("assistant", "I1"), _C],
            id="多组按depth降序插入",
        ),
    ],
)
def test_depth_injections_spliced_into_conversation(
    injections: tuple[DepthInjection, ...], expected: list[tuple[str, str]]
) -> None:
    model = make_model(resolver=lambda cid, msgs, idx: _assembled(*injections))
    messages = model.build_messages(make_request(recent=_recent(), runtime=_RUNTIME))
    assert _layout(messages) == [
        *expected,
        ("system", "<运行环境>"),
        ("user", "当前用户消息"),
    ]


def test_resolver_receives_conversation_recent_messages_and_turn_index() -> None:
    recent = _recent()
    captured: list[tuple] = []

    def resolver(cid, recent_messages, turn_index):
        captured.append((cid, recent_messages, turn_index))
        return _assembled()

    make_model(resolver=resolver).build_messages(make_request(recent=recent, turn_index=7))
    # 每次请求只装配一次角色卡。
    assert captured == [("c", recent, 7)]


# ---------------------------------------------------------------------------
# orchestrator 侧 turn_index 计算
# ---------------------------------------------------------------------------


def test_conversation_turn_index_counts_user_typed_messages() -> None:
    # 只统计来源与 origin 都是用户的历史消息，再加当前回合。
    greeting = _message(MessageSource.CHARACTER, "开场白")  # 不计入
    user1 = _message(MessageSource.USER, "你好")
    char1 = _message(MessageSource.CHARACTER, "你好呀")
    user2 = _message(MessageSource.USER, "再聊聊")
    deleg = _message(
        MessageSource.USER, "委派副本", origin=MessageOrigin.CHARACTER_DELEGATION
    )  # origin != USER，不计入
    sys_msg = _message(MessageSource.SYSTEM, "系统")

    assert _conversation_turn_index([]) == 1
    assert _conversation_turn_index([greeting]) == 1
    assert _conversation_turn_index([greeting, user1]) == 2
    assert _conversation_turn_index([greeting, user1, char1, user2]) == 3
    assert _conversation_turn_index([greeting, user1, char1, deleg, sys_msg]) == 2


async def test_character_turn_request_carries_turn_index(tmp_path) -> None:
    model = FixedDialogueModel(*(CharacterTurn(speech=f"{n}。") for n in range(3)))
    orchestrator = ConversationOrchestrator(
        dialogue_model=model,
        coding_engine=RecordingCodingEngine(),
        approval_callback=unexpected_approval,
    )
    context = make_context(
        ProjectRef(project_id="p", name="我的项目", root_path=str(tmp_path / "project")),
        conversation_id="c",
        pair_id=PAIR_ID,
        approval_mode=ApprovalMode.FULL_AUTO,
    )
    for text in ("第一句", "第二句", "第三句"):
        user = await orchestrator.submit_user_message(
            conversation_id="c", text=text, target="character", pair_id=PAIR_ID
        )
        await orchestrator.process_character_turn(
            conversation_id="c", user_message=user, context=context
        )
    # 当前用户消息计入本回合。
    assert [request.turn_index for request in model.requests] == [1, 2, 3]