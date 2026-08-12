"""V0.2 M1 逻辑回归：快速接受、聊天模式边界、运行时上下文、消息归属、审查生命周期。

对应 14 项问题：1（快速接受）、3/8（模式独立）、4（聊天模式边界）、
5（项目运行上下文）、7（消息空间归属）、14（审查生命周期）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pair_harness.adapters.reviewer import ScriptedReviewer
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageTarget,
    ProjectRef,
    ReviewerVerdict,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel, RecordingCodingEngine


def _make_orchestrator(
    *turns: CharacterTurn,
    tmp_path: Path,
    engine=None,
    approval_mode: ApprovalMode = ApprovalMode.FULL_AUTO,
    reviewer=None,
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(
            project_id="p", name="我的项目", root_path=str(tmp_path / "project")
        ),
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=engine or RecordingCodingEngine(),
        approval_mode=approval_mode,
        reviewer=reviewer,
    )


@pytest.mark.asyncio
async def test_fast_accept_returns_real_message_id_before_turn(tmp_path: Path) -> None:
    """问题 1：submit_user_message 立即返回真实 id，回合随后处理。"""
    model = FixedDialogueModel(CharacterTurn(speech="你好。", delegation=None))
    orchestrator = _make_orchestrator(tmp_path=tmp_path, engine=RecordingCodingEngine())
    orchestrator.dialogue_model = model

    user = await orchestrator.submit_user_message(
        conversation_id="c", text="第一条消息", target="character"
    )
    assert user.message_id
    assert user.target == MessageTarget.CHARACTER
    assert user.origin == MessageOrigin.USER
    # 回合尚未处理：模型请求为空
    assert model.requests == []

    outcome = await orchestrator.process_character_turn(
        conversation_id="c", user_message=user
    )
    assert outcome.messages[0].message_id == user.message_id
    assert model.requests[0].user_message.message_id == user.message_id


@pytest.mark.asyncio
async def test_user_message_target_and_origin(tmp_path: Path) -> None:
    """问题 7：用户直发角色/助手的消息携带 target 与 origin。"""
    model = FixedDialogueModel(CharacterTurn(speech="好。", delegation=None))
    orchestrator = _make_orchestrator(tmp_path=tmp_path)
    orchestrator.dialogue_model = model

    to_character = await orchestrator.submit_user_message(
        conversation_id="c", text="聊聊", target="character"
    )
    to_assistant = await orchestrator.submit_user_message(
        conversation_id="c", text="查一下", target="assistant"
    )
    assert (to_character.target, to_character.origin) == (
        MessageTarget.CHARACTER,
        MessageOrigin.USER,
    )
    assert (to_assistant.target, to_assistant.origin) == (
        MessageTarget.ASSISTANT,
        MessageOrigin.USER,
    )


@pytest.mark.asyncio
async def test_chat_mode_blocks_delegation(tmp_path: Path) -> None:
    """问题 4：聊天模式角色输出 delegation 一律不执行，给可见提示。"""
    engine = RecordingCodingEngine()
    orchestrator = _make_orchestrator(
        CharacterTurn(
            speech="好，让机枢跑一下。",
            delegation=TaskRequestDraft(instructions="跑测试"),
        ),
        tmp_path=tmp_path,
        engine=engine,
    )
    orchestrator.set_conversation_mode("c", "chat")

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="帮我跑测试"
    )

    assert outcome.task is None
    assert len(engine.requests) == 0
    kinds = [message.kind for message in outcome.messages]
    assert MessageKind.SYSTEM_STATUS in kinds
    notice = next(m for m in outcome.messages if m.source == MessageSource.SYSTEM)
    assert "聊天模式" in notice.text


@pytest.mark.asyncio
async def test_collaboration_executes_delegation_with_delegation_id(tmp_path: Path) -> None:
    """问题 7：协作模式委派执行，执行记录带 delegation_id 与 character_delegation 来源。"""
    engine = RecordingCodingEngine()
    orchestrator = _make_orchestrator(
        CharacterTurn(
            speech="好，让机枢跑一下。",
            delegation=TaskRequestDraft(instructions="跑测试"),
        ),
        CharacterTurn(speech="做完了。"),
        tmp_path=tmp_path,
        engine=engine,
    )
    orchestrator.set_conversation_mode("c", "collaboration")

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="帮我跑测试"
    )

    assert outcome.task is not None
    assistant = next(
        m for m in outcome.messages if m.source == MessageSource.ASSISTANT
    )
    assert assistant.delegation_id == outcome.task.task_id
    assert assistant.origin == MessageOrigin.CHARACTER_DELEGATION
    # 角色执行结果回应带同一 delegation_id，Presenter 可连接两侧
    result_char = next(
        m
        for m in outcome.messages
        if m.source == MessageSource.CHARACTER and m.text == "做完了。"
    )
    assert result_char.delegation_id == outcome.task.task_id


@pytest.mark.asyncio
async def test_runtime_context_injected_in_dialogue_request(tmp_path: Path) -> None:
    """问题 5：项目运行上下文注入 DialogueRequest（名称/目录/模式）。"""
    model = FixedDialogueModel(
        CharacterTurn(speech="你好。", delegation=None),
        CharacterTurn(speech="我看不到。", delegation=None),
    )
    orchestrator = _make_orchestrator(tmp_path=tmp_path)
    orchestrator.dialogue_model = model
    orchestrator.set_conversation_mode("c", "collaboration")

    await orchestrator.handle_character_input(conversation_id="c", text="你好")

    request = model.requests[0]
    assert request.runtime_context is not None
    assert request.runtime_context.project_name == "我的项目"
    assert request.runtime_context.project_abs_dir
    assert request.runtime_context.local_time
    assert request.runtime_context.conversation_mode == "collaboration"

    # 聊天模式注入的能力边界
    orchestrator.set_conversation_mode("c", "chat")
    await orchestrator.handle_character_input(conversation_id="c", text="这项目是啥")
    assert model.requests[1].runtime_context.conversation_mode == "chat"


@pytest.mark.asyncio
async def test_review_lifecycle_events_only_when_reviewer_invoked(tmp_path: Path) -> None:
    """问题 14：审查事件只在真正调用审查智能体时出现；低风险直接放行不触发。"""
    events: list[tuple[str, dict]] = []
    reviewer = ScriptedReviewer([ReviewerVerdict(allow=True)])
    # 高风险命令（git push --force 命中 git_destructive 规则）→ 必须走审查智能体
    engine = RecordingCodingEngine(
        tool_payload={"tool_kind": "shell", "command": "git push --force origin main"}
    )
    orchestrator = _make_orchestrator(
        CharacterTurn(
            speech="交给机枢。",
            delegation=TaskRequestDraft(instructions="执行"),
        ),
        CharacterTurn(speech="做完了。"),
        tmp_path=tmp_path,
        engine=engine,
        approval_mode=ApprovalMode.REVIEW,
        reviewer=reviewer,
    )
    orchestrator.on_review_event = lambda event, payload: events.append((event, payload))

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="执行"
    )
    assert outcome.receipt is not None
    assert [event for event, _ in events] == ["review.started", "review.completed"]

    # 低风险操作（如 ls）在 REVIEW 模式直接放行，不产生审查事件
    events.clear()
    model = FixedDialogueModel(
        CharacterTurn(
            speech="交给机枢。",
            delegation=TaskRequestDraft(instructions="执行"),
        ),
        CharacterTurn(speech="做完了。"),
    )
    low_engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    low = _make_orchestrator(
        tmp_path=tmp_path,
        engine=low_engine,
        approval_mode=ApprovalMode.REVIEW,
        reviewer=ScriptedReviewer(),
    )
    low.on_review_event = lambda event, payload: events.append((event, payload))
    low.dialogue_model = model
    await low.handle_character_input(conversation_id="c", text="执行")
    assert events == []


@pytest.mark.asyncio
async def test_message_status_failed_keeps_text(tmp_path: Path) -> None:
    """问题 1：回合失败把用户消息标记 failed，文字保留（可重试）。"""
    orchestrator = _make_orchestrator(
        CharacterTurn(speech="好。", delegation=None), tmp_path=tmp_path
    )
    user = await orchestrator.submit_user_message(
        conversation_id="c", text="这条会失败", target="character"
    )
    status_changed: list = []

    async def capture(msg) -> None:
        status_changed.append(msg)

    # 模拟回合失败：直接标记
    orchestrator.mark_message_failed("c", user.message_id, "模拟错误")
    # on_message_status_changed 为 None 时不崩溃；此处验证落库与内存一致
    assert orchestrator._history["c"][0].status == "failed"
    assert orchestrator._history["c"][0].text == "这条会失败"
    assert orchestrator._history["c"][0].payload.get("error") == "模拟错误"
