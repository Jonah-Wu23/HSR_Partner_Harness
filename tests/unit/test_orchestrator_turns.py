from __future__ import annotations

from pathlib import Path

import pytest

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
from tests.fakes import (
    FixedDialogueModel,
    RecordingCodingEngine,
    ScriptedReviewer,
    make_context,
    unexpected_approval,
)

PAIR_ID = "phainon_ancient_machine"


def _make_orchestrator(
    *turns: CharacterTurn,
    engine=None,
    reviewer=None,
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=engine or RecordingCodingEngine(),
        reviewer=reviewer,
        approval_callback=unexpected_approval,
    )


def _context(
    tmp_path: Path,
    *,
    conversation_mode: str = "collaboration",
    approval_mode: ApprovalMode = ApprovalMode.FULL_AUTO,
):
    return make_context(
        ProjectRef(project_id="p", name="我的项目", root_path=str(tmp_path / "project")),
        conversation_id="c",
        conversation_mode=conversation_mode,
        approval_mode=approval_mode,
    )


@pytest.mark.asyncio
async def test_submit_returns_stored_message_before_turn_runs(tmp_path: Path) -> None:
    """submit_user_message 先返回落库消息的真实 id，角色回合随后处理同一条消息。"""
    orchestrator = _make_orchestrator(CharacterTurn(speech="你好。"))
    model = orchestrator.dialogue_model

    user = await orchestrator.submit_user_message(
        conversation_id="c", text="第一条消息", target="character", pair_id=PAIR_ID
    )
    assert user.message_id
    assert model.requests == []

    outcome = await orchestrator.process_character_turn(
        conversation_id="c", user_message=user, context=_context(tmp_path)
    )
    assert outcome.messages[0].message_id == user.message_id
    assert model.requests[0].user_message.message_id == user.message_id


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [MessageTarget.CHARACTER, MessageTarget.ASSISTANT])
async def test_submitted_user_message_keeps_target_and_user_origin(
    target: MessageTarget,
) -> None:
    orchestrator = _make_orchestrator()

    message = await orchestrator.submit_user_message(
        conversation_id="c", text="你好", target=target.value, pair_id=PAIR_ID
    )

    assert (message.target, message.origin) == (target, MessageOrigin.USER)


@pytest.mark.asyncio
async def test_chat_mode_blocks_delegation(tmp_path: Path) -> None:
    """聊天模式下角色输出的委派一律不执行，并留下可见提示。"""
    engine = RecordingCodingEngine()
    orchestrator = _make_orchestrator(
        CharacterTurn(
            speech="好，让机枢跑一下。",
            delegation=TaskRequestDraft(instructions="跑测试"),
        ),
        engine=engine,
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c",
        text="帮我跑测试",
        context=_context(tmp_path, conversation_mode="chat"),
    )

    assert outcome.task is None
    assert len(engine.requests) == 0
    kinds = [message.kind for message in outcome.messages]
    assert MessageKind.SYSTEM_STATUS in kinds
    notice = next(m for m in outcome.messages if m.source == MessageSource.SYSTEM)
    assert "聊天模式" in notice.text


@pytest.mark.asyncio
async def test_collaboration_executes_delegation_with_delegation_id(tmp_path: Path) -> None:
    """协作模式执行委派，执行记录带 delegation_id 与 character_delegation 来源。"""
    orchestrator = _make_orchestrator(
        CharacterTurn(
            speech="好，让机枢跑一下。",
            delegation=TaskRequestDraft(instructions="跑测试"),
        ),
        CharacterTurn(speech="做完了。"),
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="帮我跑测试", context=_context(tmp_path)
    )

    assert outcome.task is not None
    assistant = next(
        m for m in outcome.messages if m.source == MessageSource.ASSISTANT
    )
    assert assistant.delegation_id == outcome.task.task_id
    assert assistant.origin == MessageOrigin.CHARACTER_DELEGATION
    # 角色的结果回应带同一 delegation_id，界面据此连接角色区与工作台
    result_char = next(
        m
        for m in outcome.messages
        if m.source == MessageSource.CHARACTER and m.text == "做完了。"
    )
    assert result_char.delegation_id == outcome.task.task_id
    delegation_message = next(
        m
        for m in outcome.messages
        if m.origin == MessageOrigin.CHARACTER_DELEGATION
    )
    assert delegation_message.status == "done"
    assert result_char.payload["execution_status"] == "completed"


@pytest.mark.asyncio
async def test_engine_stream_without_terminal_event_fails_turn(tmp_path: Path) -> None:
    """引擎事件流没有终态事件时回合报错，委派卡不会被标成完成。"""

    class SilentEngine(RecordingCodingEngine):
        async def run_turn(self, session_ref, request):
            return
            yield  # pragma: no cover - 使其成为 async 生成器

    orchestrator = _make_orchestrator(
        CharacterTurn(
            speech="交给古代机械。",
            delegation=TaskRequestDraft(instructions="检查项目"),
        ),
        engine=SilentEngine(),
    )
    user = await orchestrator.submit_user_message(
        conversation_id="c", text="检查项目", target="character", pair_id=PAIR_ID
    )

    with pytest.raises(RuntimeError, match="终态事件"):
        await orchestrator.process_character_turn(
            conversation_id="c", user_message=user, context=_context(tmp_path)
        )

    delegation_message = next(
        m
        for m in orchestrator._history["c"]
        if m.origin == MessageOrigin.CHARACTER_DELEGATION
    )
    assert delegation_message.status == "processing"


@pytest.mark.asyncio
async def test_runtime_context_injected_in_dialogue_request(tmp_path: Path) -> None:
    """角色请求携带项目运行上下文：名称、目录、时间与对话模式。"""
    orchestrator = _make_orchestrator(
        CharacterTurn(speech="你好。"),
        CharacterTurn(speech="我看不到。"),
    )
    model = orchestrator.dialogue_model

    await orchestrator.handle_character_input(
        conversation_id="c", text="你好", context=_context(tmp_path)
    )

    request = model.requests[0]
    assert request.runtime_context is not None
    assert request.runtime_context.project_name == "我的项目"
    assert request.runtime_context.project_abs_dir
    assert request.runtime_context.local_time
    assert request.runtime_context.conversation_mode == "collaboration"

    await orchestrator.handle_character_input(
        conversation_id="c",
        text="这项目是啥",
        context=_context(tmp_path, conversation_mode="chat"),
    )
    assert model.requests[1].runtime_context.conversation_mode == "chat"


@pytest.mark.asyncio
async def test_review_events_forwarded_when_reviewer_invoked(tmp_path: Path) -> None:
    """调用审查智能体时经 on_review_event 转发审查生命周期，并带任务所属聊天。"""
    events: list[tuple[str, dict]] = []
    # git push --force 命中高风险规则，审查模式下交审查智能体裁决
    engine = RecordingCodingEngine(
        tool_payload={"tool_kind": "shell", "command": "git push --force origin main"}
    )
    orchestrator = _make_orchestrator(
        CharacterTurn(
            speech="交给机枢。",
            delegation=TaskRequestDraft(instructions="执行"),
        ),
        CharacterTurn(speech="做完了。"),
        engine=engine,
        reviewer=ScriptedReviewer([ReviewerVerdict(allow=True)]),
    )
    orchestrator.on_review_event = lambda event, payload: events.append((event, payload))

    outcome = await orchestrator.handle_character_input(
        conversation_id="c",
        text="执行",
        context=_context(tmp_path, approval_mode=ApprovalMode.REVIEW),
    )

    assert outcome.receipt is not None
    assert [event for event, _ in events] == ["review.started", "review.completed"]
    assert {payload["conversation_id"] for _, payload in events} == {"c"}
