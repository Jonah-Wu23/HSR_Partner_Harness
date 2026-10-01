from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pair_harness.core.context import ExecutionContext
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    Message,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    ProjectRef,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.repository import Conversation, ConversationSnapshot
from pair_harness.core.summary import ConversationSummary
from tests.fakes import (
    FixedDialogueModel,
    RecordingCodingEngine,
    allow_approval,
    make_context,
)

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_orchestrator(*turns: CharacterTurn) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=RecordingCodingEngine(),
        approval_callback=allow_approval,
    )


def _context(tmp_path: Path, conversation_id: str, pair_id: str) -> ExecutionContext:
    return make_context(
        ProjectRef(project_id="p1", name="测试项目", root_path=str(tmp_path)),
        conversation_id=conversation_id,
        pair_id=pair_id,
        approval_mode=ApprovalMode.FULL_AUTO,
    )


async def test_system_status_uses_each_conversation_pair(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(
        CharacterTurn(speech="甲聊天回应。"),
        CharacterTurn(speech="乙聊天回应。"),
    )
    await orchestrator.handle_character_input(
        conversation_id="conv_a", text="甲", context=_context(tmp_path, "conv_a", "pair_a")
    )
    await orchestrator.handle_character_input(
        conversation_id="conv_b", text="乙", context=_context(tmp_path, "conv_b", "pair_b")
    )

    # 后处理的 conv_b 不改变 conv_a 的搭档归属
    assert orchestrator.report_system_status("conv_a", "后台通知").pair_id == "pair_a"
    assert orchestrator.report_system_status("conv_b", "后台通知").pair_id == "pair_b"
    explicit = orchestrator.report_system_status("conv_a", "显式搭档", pair_id="custom_pair")
    assert explicit.pair_id == "custom_pair"
    with pytest.raises(RuntimeError, match="没有登记搭档"):
        orchestrator.report_system_status("unregistered", "没有归属的提示")


def _snapshot(summary: ConversationSummary | None) -> ConversationSnapshot:
    messages = tuple(
        Message(
            message_id=f"m{index}",
            conversation_id="c_restored",
            pair_id="restored_pair",
            source=MessageSource.USER,
            kind=MessageKind.USER_TEXT,
            text=f"用户消息 {index}",
            origin=MessageOrigin.USER,
            status=MessageStatus.DONE,
            created_at=_NOW,
            timeline_order=index,
        )
        for index in range(1, 4)
    )
    return ConversationSnapshot(
        conversation=Conversation(
            conversation_id="c_restored",
            project_id="p1",
            pair_id="restored_pair",
            title="恢复的聊天",
            last_mode="collaboration",
            archived=False,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        messages=messages,
        tool_runs=(),
        engine_session=None,
        summary=summary,
    )


def test_restore_conversation_registers_pair_and_summary_coverage() -> None:
    orchestrator = _make_orchestrator()
    completed = ConversationSummary(
        summary_id="s1",
        conversation_id="c_restored",
        status="completed",
        covers_from_message_id="m1",
        covers_to_message_id="m2",
        covers_message_count=2,
        content={"summary": "前两条讨论"},
    )
    orchestrator.restore_conversation(_snapshot(completed))
    assert orchestrator.report_system_status("c_restored", "已恢复").pair_id == "restored_pair"
    assert orchestrator.summary_coverage("c_restored") == "m2"

    # 再次打开时已没有成功摘要：覆盖终点随之清除
    orchestrator.restore_conversation(_snapshot(None))
    assert orchestrator.summary_coverage("c_restored") is None


async def test_task_result_turn_shares_character_turn_context(tmp_path: Path) -> None:
    model = FixedDialogueModel(
        CharacterTurn(speech="先聊两句。"),
        CharacterTurn(
            speech="古代机械，这件事交给你。",
            delegation=TaskRequestDraft(instructions="执行测试任务"),
        ),
        CharacterTurn(speech="任务已完成，回复结果。"),
    )
    orchestrator = ConversationOrchestrator(
        dialogue_model=model,
        coding_engine=RecordingCodingEngine(),
        approval_callback=allow_approval,
    )
    context = _context(tmp_path, "c_assembly", "pair_assembly")
    await orchestrator.handle_character_input(
        conversation_id="c_assembly", text="你好", context=context
    )
    outcome = await orchestrator.handle_character_input(
        conversation_id="c_assembly", text="帮我跑个任务", context=context
    )
    assert outcome.receipt is not None and outcome.receipt.status == "completed"

    _, character_turn, result_turn = model.requests
    current_user = outcome.messages[0]
    # 主角色轮：当前用户消息只由 user_message 承载，不重复进入上下文窗口
    assert character_turn.user_message.message_id == current_user.message_id
    assert [m.text for m in character_turn.recent_messages] == ["你好", "先聊两句。"]
    # 任务结果轮沿用同一搭档、回合序号与项目运行上下文，并携带任务结果
    assert result_turn.pair_id == character_turn.pair_id == "pair_assembly"
    assert result_turn.turn_index == character_turn.turn_index == 2
    assert result_turn.runtime_context.project_name == character_turn.runtime_context.project_name
    assert (
        result_turn.runtime_context.project_abs_dir
        == character_turn.runtime_context.project_abs_dir
    )
    assert result_turn.user_message.source == MessageSource.SYSTEM
    assert result_turn.result_summary is not None
    assert result_turn.result_summary.status == "completed"