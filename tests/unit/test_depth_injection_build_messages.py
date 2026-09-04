"""V0.3.7：build_messages 深度注入（depth splice）与 turn_index 契约测试。

覆盖 ``docs/plans/V0.3.7-契约冻结.md`` §4.4/§4.5：

- resolver 三参契约：``(conversation_id, recent_messages, turn_index)``；
- depth 注入 splice 语义：depth=0 / 正常 / 越界 clamp、同 (depth, role)
  合并且 "\n" 连接、多注入按 depth 降序插入；
- 无注入（resolver 返回 None 或 depth_injections 为空）时行为与现状一致；
- orchestrator 侧 turn_index 计算（纯函数 + 真实历史流程）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
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
from tests.fakes import FixedDialogueModel, RecordingCodingEngine

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


def _injection(depth: int, role: str, text: str) -> SimpleNamespace:
    """鸭子类型深度注入条目（装配器 DepthInjection 未实现，此处用同构对象）。"""
    return SimpleNamespace(depth=depth, role=role, text=text)


def _assembled(system_text: str = "角色提示词", injections: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        system_text=system_text,
        first_mes="",
        depth_injections=injections or [],
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


def _roles(messages: list[dict]) -> list[str]:
    return [m["role"] for m in messages]


# ---------------------------------------------------------------------------
# 无注入回归：与 resolver 为空时输出完全一致
# ---------------------------------------------------------------------------


def test_no_depth_injections_keeps_current_behavior() -> None:
    """resolver 返回装配结果但 depth_injections 为空 → 不产生任何注入消息。

    （resolver 存在时 system 首条来自自定义装配，属于预期差异；此处仅断言
    对话消息结构与注入无关地与 resolver 为空时一致。）
    """
    recent = (_message(MessageSource.CHARACTER, "a"), _message(MessageSource.USER, "b"))
    base = make_model(resolver=None).build_messages(make_request(recent=recent))
    with_resolver = make_model(
        resolver=lambda cid, msgs, idx: _assembled()
    ).build_messages(make_request(recent=recent))
    # 对话段（去掉首条 system 提示）完全一致，未新增任何注入消息
    assert with_resolver[1:] == base[1:]
    # 消息总数一致（无额外注入）
    assert len(with_resolver) == len(base)


def test_resolver_none_falls_back_to_builtin() -> None:
    """resolver 为 None → 内置角色路径，无注入。"""
    recent = (_message(MessageSource.CHARACTER, "a"), _message(MessageSource.USER, "b"))
    messages = make_model(resolver=None).build_messages(make_request(recent=recent))
    assert _roles(messages) == [
        "system",
        "assistant",
        "user",
        "user",  # 当前用户消息
    ]


# ---------------------------------------------------------------------------
# depth 注入 splice 语义
# ---------------------------------------------------------------------------


def test_single_injection_depth_2_inserts_before_2nd_from_end() -> None:
    """单条注入 depth=2 role=system：插到距末尾第 2 条消息之前。"""
    recent = (
        _message(MessageSource.CHARACTER, "a"),
        _message(MessageSource.USER, "b"),
        _message(MessageSource.CHARACTER, "c"),
    )
    resolver = lambda cid, msgs, idx: _assembled(
        injections=[_injection(depth=2, role="system", text="深层提示")]
    )
    messages = make_model(resolver=resolver).build_messages(make_request(recent=recent))
    # 映射后对话消息：assistant:a, user:b, assistant:c；depth=2 → 距末尾第 2 条
    # （user:b）之前插入 → 位于 assistant:a 与 user:b 之间。
    contents = [m["content"] for m in messages]
    assert contents.index("a") < contents.index("深层提示") < contents.index("b")
    # 注入 role 为 system
    inj = next(m for m in messages if m["content"] == "深层提示")
    assert inj == {"role": "system", "content": "深层提示"}
    # 结尾仍是当前用户消息，未受影响
    assert messages[-1] == {"role": "user", "content": "当前用户消息"}


def test_depth_0_appends_after_conversation_before_runtime_context() -> None:
    """depth=0 → 追加到对话消息末尾之后、runtime 上下文之前。"""
    recent = (
        _message(MessageSource.CHARACTER, "a"),
        _message(MessageSource.USER, "b"),
    )
    resolver = lambda cid, msgs, idx: _assembled(
        injections=[_injection(depth=0, role="user", text="末尾注入")]
    )
    request = make_request(
        recent=recent,
        runtime=ProjectRuntimeContext(
            project_name="项目", project_abs_dir="C:/p", conversation_mode="collaboration"
        ),
    )
    messages = make_model(resolver=resolver).build_messages(request)
    roles = _roles(messages)
    # 注入的 user 消息位于 recent 对话之后、runtime 系统块之前、当前用户消息之前。
    assert "user" in roles
    inj_index = next(i for i, m in enumerate(messages) if m["content"] == "末尾注入")
    assert inj_index == 3  # system, assistant:a, user:b, 注入
    # 注入之后是 runtime 上下文系统块
    assert messages[inj_index + 1]["role"] == "system"
    assert "当前工作环境" in messages[inj_index + 1]["content"]
    # 当前用户消息仍在最末
    assert messages[-1] == {"role": "user", "content": "当前用户消息"}


def test_depth_out_of_bounds_clamps_to_front() -> None:
    """depth ≥ 消息数 → clamp 到列表最前。"""
    recent = (
        _message(MessageSource.CHARACTER, "a"),
        _message(MessageSource.USER, "b"),
    )
    resolver = lambda cid, msgs, idx: _assembled(
        injections=[_injection(depth=9, role="system", text="最前注入")]
    )
    messages = make_model(resolver=resolver).build_messages(make_request(recent=recent))
    assert messages[0] == {"role": "system", "content": "最前注入"}
    assert messages[1]["role"] == "system"  # 原有 system 提示随之后移


def test_same_depth_role_merged_and_different_role_split() -> None:
    """同 (depth, role) 多条合成为一条、文本 "\n" 连接；不同 role 同 depth 分开。"""
    recent = (
        _message(MessageSource.CHARACTER, "a"),
        _message(MessageSource.USER, "b"),
        _message(MessageSource.CHARACTER, "c"),
    )
    resolver = lambda cid, msgs, idx: _assembled(
        injections=[
            _injection(depth=3, role="system", text="X"),
            _injection(depth=3, role="system", text="Y"),
            _injection(depth=3, role="assistant", text="Z"),
        ]
    )
    messages = make_model(resolver=resolver).build_messages(make_request(recent=recent))
    # 同 (depth=3, role=system) 的 X、Y 合并为一条 "X\nY"
    assert sum(1 for m in messages if m["content"] == "X\nY") == 1
    # 不同 role（assistant）的 Z 是独立一条
    assert sum(1 for m in messages if m["content"] == "Z") == 1
    # 三条注入合并后只产生两条消息
    injected = [m for m in messages if m["content"] in ("X\nY", "Z")]
    assert len(injected) == 2
    sys_injected = next(m for m in injected if m["content"] == "X\nY")
    assert sys_injected["role"] == "system"
    user_injected = next(m for m in injected if m["content"] == "Z")
    assert user_injected["role"] == "assistant"


def test_multiple_injections_inserted_in_descending_depth_order() -> None:
    """多条注入按 depth 降序插入后整体位置正确（运行 offset 对齐 ST）。"""
    recent = (
        _message(MessageSource.CHARACTER, "a"),
        _message(MessageSource.USER, "b"),
        _message(MessageSource.CHARACTER, "c"),
    )
    resolver = lambda cid, msgs, idx: _assembled(
        injections=[
            _injection(depth=3, role="system", text="I3"),
            _injection(depth=1, role="assistant", text="I1"),
        ]
    )
    messages = make_model(resolver=resolver).build_messages(make_request(recent=recent))
    # depth=3 先插入到距末尾第 3 条（user:b）之前，即 index1 区域；
    # depth=1 在增长后列表上再插（运行 offset，对齐 ST doChatInject）。
    contents = [m["content"] for m in messages]
    assert "I3" in contents and "I1" in contents
    # I3(depth=3) 排在 I1(depth=1) 之前
    assert contents.index("I3") < contents.index("I1")
    # 注入内容落在对话消息之间，不落到当前用户消息之后
    assert messages[-1]["content"] == "当前用户消息"
    # 距末尾第 1 条是 assistant:c，I1(depth=1) 应插在它之前一处；c 仍在对话区尾部
    assert messages[-2]["content"] == "c"


# ---------------------------------------------------------------------------
# resolver 三参契约
# ---------------------------------------------------------------------------


def test_resolver_called_with_three_arguments() -> None:
    """resolver 以 (conversation_id, recent_messages, turn_index) 三参被调用。"""
    recent = (
        _message(MessageSource.CHARACTER, "a"),
        _message(MessageSource.USER, "b"),
    )
    captured: list[tuple] = []

    def resolver(cid, recent_messages, turn_index):
        captured.append((cid, recent_messages, turn_index))
        return _assembled()

    model = make_model(resolver=resolver)
    request = make_request(recent=recent, turn_index=7)
    model.build_messages(request)
    # build_messages 内 _system_prompt 与 _apply_depth_injections 各触发一次，
    # 两次都以三参契约调用。
    assert captured, "resolver 未被调用"
    for cid, msgs, idx in captured:
        assert cid == "c"
        assert isinstance(msgs, tuple)
        assert msgs == recent
        assert idx == 7


def test_turn_index_passed_to_resolver_from_request() -> None:
    """turn_index 从 request 透传进 resolver（默认 0 时传 0）。"""
    captured: dict = {}

    def resolver(cid, recent_messages, turn_index):
        captured["idx"] = turn_index
        return _assembled()

    model = make_model(resolver=resolver)
    model.build_messages(make_request(recent=(), turn_index=12))
    assert captured["idx"] == 12


# ---------------------------------------------------------------------------
# orchestrator 侧 turn_index 计算
# ---------------------------------------------------------------------------


def test_conversation_turn_index_pure_function() -> None:
    """纯函数：仅统计 source==USER 且 origin==USER 的历史消息 +1。"""
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


def _make_orchestrator(*turns: CharacterTurn, tmp_path) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id=PAIR_ID,
        project=ProjectRef(
            project_id="p", name="我的项目", root_path=str(tmp_path / "project")
        ),
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=RecordingCodingEngine(),
        approval_mode=ApprovalMode.FULL_AUTO,
    )


async def _run_round(orchestrator: ConversationOrchestrator, text: str) -> None:
    user = await orchestrator.submit_user_message(
        conversation_id="c", text=text, target="character"
    )
    await orchestrator.process_character_turn(
        conversation_id="c", user_message=user
    )


@pytest.mark.asyncio
async def test_process_character_turn_sets_turn_index(tmp_path) -> None:
    """真实历史流程：多轮 user/character 后，下一轮 turn_index = 用户发言数 +1。"""
    # 3 轮用户真实发言 + 开场白
    model = FixedDialogueModel(
        CharacterTurn(speech="一。"),
        CharacterTurn(speech="二。"),
        CharacterTurn(speech="三。"),
        CharacterTurn(speech="四。"),
    )
    orchestrator = _make_orchestrator(*[CharacterTurn(speech="end")], tmp_path=tmp_path)
    orchestrator.dialogue_model = model
    # 开场白注入历史（CHARACTER/SYSTEM 来源，不计入 turn_index）
    orchestrator._history["c"] = [
        _message(MessageSource.CHARACTER, "开场白"),
        # 签名无 SYSTEM Message；开场白用 CHARACTER 足够代表不计入
    ]
    await _run_round(orchestrator, "第一句")
    await _run_round(orchestrator, "第二句")
    await _run_round(orchestrator, "第三句")

    # 提交第四句后，角色回合请求里的 turn_index 应为 4（含当前回合）
    user4 = await orchestrator.submit_user_message(
        conversation_id="c", text="第四句", target="character"
    )
    await orchestrator.process_character_turn(
        conversation_id="c", user_message=user4
    )
    requests = model.requests
    assert len(requests) == 4
    assert requests[0].turn_index == 1
    assert requests[1].turn_index == 2
    assert requests[2].turn_index == 3
    assert requests[3].turn_index == 4