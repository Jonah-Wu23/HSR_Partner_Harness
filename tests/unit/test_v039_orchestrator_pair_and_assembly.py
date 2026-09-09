"""V0.3.9 契约 §1/§2：编排器搭档归属回退修复与三处装配一致性测试。

契约出处：``docs/plans/V0.3.9-契约冻结.md`` §1（身份与搭档归属）、§2（装配与投影）。

- 消息与系统提示必须使用该聊天自己的 pair_id，不能退化为可变全局 self.pair_id；
- 快照恢复 (restore_conversation) 登记聊天权威搭档并设置摘要覆盖终点；
- 三处装配点（主角色轮、委派纠偏重试轮、任务结果轮）共享同一上下文窗口、
  同一回合序号与同一项目运行上下文。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pair_harness.character_cards.models import CharacterCard
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
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.summary import (
    ConversationSummary,
    ROLE_CONTEXT_LIMIT_AFTER_SUMMARY,
    ROLE_CONTEXT_LIMIT_PRE_SUMMARY,
)
from tests.fakes import FixedDialogueModel, RecordingCodingEngine

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_orchestrator(
    *turns: CharacterTurn,
    tmp_path: Path,
    pair_id: str = "default_pair",
) -> ConversationOrchestrator:
    project_dir = tmp_path / "test_proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    return ConversationOrchestrator(

        project=ProjectRef(
            project_id="p_default", name="测试项目", root_path=str(project_dir)
        ),
        pair_id=pair_id,
        dialogue_model=FixedDialogueModel(*turns),
        coding_engine=RecordingCodingEngine(),
        approval_mode=ApprovalMode.FULL_AUTO,
    )


def _user_message(
    index: int,
    conversation_id: str = "c1",
    pair_id: str = "pair_c1",
    text: str | None = None,
) -> Message:
    return Message(
        message_id=f"m{index}",
        conversation_id=conversation_id,
        pair_id=pair_id,
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text=text or f"用户消息 {index}",
        origin=MessageOrigin.USER,
        status=MessageStatus.DONE,
        created_at=_NOW,
    )


def test_pair_id_resolution_and_fallback(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """V0.3.9 契约 §1：显式优先，已登记优先，未登记告警并退回启动搭档。"""
    orchestrator = _make_orchestrator(tmp_path=tmp_path, pair_id="launch_pair")

    # 1. 显式传入优先
    assert orchestrator._pair_id_for("c1", "explicit_pair") == "explicit_pair"

    # 2. 已登记搭档优先
    orchestrator._remember_conversation_pair("c1", "pair_c1")
    assert orchestrator._pair_id_for("c1", None) == "pair_c1"

    # 3. 未登记会话退回启动搭档并只告警一次
    with caplog.at_level(logging.WARNING):
        first_call = orchestrator._pair_id_for("unregistered_c", None)
        assert first_call == "launch_pair"
        assert "未登记搭档" in caplog.text

        record_count_before = len(caplog.records)
        second_call = orchestrator._pair_id_for("unregistered_c", None)
        assert second_call == "launch_pair"
        # 不会因多次调用重复告警
        assert len(caplog.records) == record_count_before


def test_report_system_status_uses_conversation_pair(tmp_path: Path) -> None:
    """系统消息使用该聊天的已登记搭档，不被全局 self.pair_id 篡改。"""
    orchestrator = _make_orchestrator(tmp_path=tmp_path, pair_id="global_pair")
    orchestrator._remember_conversation_pair("c1", "pair_c1")

    # 未显式传 pair_id 时按 c1 解析
    msg1 = orchestrator.report_system_status("c1", "发生错误")
    assert msg1.pair_id == "pair_c1"

    # 显式传 pair_id 时尊重显式值
    msg2 = orchestrator.report_system_status("c1", "显式搭档", pair_id="custom_pair")
    assert msg2.pair_id == "custom_pair"


def test_multiconversation_pair_isolation_on_select_context(tmp_path: Path) -> None:
    """多会话并发时，select_context 切换前台搭档不影响后台已登记聊天。"""
    orchestrator = _make_orchestrator(tmp_path=tmp_path, pair_id="init_pair")
    proj = ProjectRef(project_id="p1", name="P1", root_path=str(tmp_path))

    orchestrator.select_context(
        project=proj,
        pair_id="pair_a",
        conversation_id="conv_a",
        approval_mode=ApprovalMode.FULL_AUTO,
        assistant_instructions="",
    )
    assert orchestrator._pair_id_for("conv_a", None) == "pair_a"

    # 切换到另一个会话，更新了 self.pair_id = "pair_b"
    orchestrator.select_context(
        project=proj,
        pair_id="pair_b",
        conversation_id="conv_b",
        approval_mode=ApprovalMode.FULL_AUTO,
        assistant_instructions="",
    )
    assert orchestrator._pair_id_for("conv_b", None) == "pair_b"

    # 后台会话 conv_a 依然使用 pair_a，未发生 pair 回退错写
    assert orchestrator._pair_id_for("conv_a", None) == "pair_a"
    msg_a = orchestrator.report_system_status("conv_a", "后台通知")
    assert msg_a.pair_id == "pair_a"


def test_restore_conversation_registers_pair_and_summary_coverage(tmp_path: Path) -> None:
    """快照恢复时正确登记搭档身份与成功摘要覆盖终点。"""
    orchestrator = _make_orchestrator(tmp_path=tmp_path)

    # 模拟快照：搭档为 restored_pair，携带 completed 摘要
    from unittest.mock import MagicMock

    conv_mock = MagicMock()
    conv_mock.conversation_id = "c_restored"
    conv_mock.pair_id = "restored_pair"

    completed_summary_dict = {
        "summary_id": "s1",
        "conversation_id": "c_restored",
        "status": "completed",
        "covers_from_message_id": "m1",
        "covers_to_message_id": "m20",
        "covers_message_count": 20,
        "content": {"summary": "前20条讨论"},
    }

    orchestrator.restore_conversation({
        "conversation": conv_mock,
        "messages": [_user_message(1, conversation_id="c_restored")],
        "summary": completed_summary_dict,
    })

    assert orchestrator._pair_id_for("c_restored", None) == "restored_pair"
    assert orchestrator.summary_coverage("c_restored") == "m20"

    # 若快照摘要为 failed，不收窄窗口（coverage 为 None）
    failed_summary_dict = {
        "summary_id": "s2",
        "conversation_id": "c_failed",
        "status": "failed",
        "error_code": "summary_timeout",
        "error": "timed out",
    }
    conv_failed = MagicMock()
    conv_failed.conversation_id = "c_failed"
    conv_failed.pair_id = "pair_failed"

    orchestrator.restore_conversation({
        "conversation": conv_failed,
        "messages": [],
        "summary": failed_summary_dict,
    })
    assert orchestrator.summary_coverage("c_failed") is None


def test_summary_coverage_switches_roleplay_context_window(tmp_path: Path) -> None:
    """摘要触发后角色上下文窗口收窄至契约 12 条，未触发时为 50 条。"""
    orchestrator = _make_orchestrator(tmp_path=tmp_path)
    conv_id = "c_long"
    messages = [_user_message(i, conversation_id=conv_id) for i in range(1, 61)]
    orchestrator._history[conv_id] = list(messages)

    # 1. 未登记摘要覆盖：沿用契约触发前上限 50 条
    context_pre = orchestrator._roleplay_context(conv_id)
    assert len(context_pre) == ROLE_CONTEXT_LIMIT_PRE_SUMMARY
    assert context_pre[0].message_id == "m11"
    assert context_pre[-1].message_id == "m60"

    # 2. 登记成功摘要覆盖到 m30：保留覆盖终点之后的最近 12 条
    orchestrator.set_summary_coverage(conv_id, "m30")
    assert orchestrator.summary_coverage(conv_id) == "m30"

    context_post = orchestrator._roleplay_context(conv_id)
    assert len(context_post) == ROLE_CONTEXT_LIMIT_AFTER_SUMMARY
    # m31 到 m60 共 30 条，取最后 12 条即 m49..m60
    assert context_post[0].message_id == "m49"
    assert context_post[-1].message_id == "m60"

    # 3. 清除摘要覆盖（如摘要被作废重算）：回到 50 条
    orchestrator.set_summary_coverage(conv_id, None)
    assert len(orchestrator._roleplay_context(conv_id)) == ROLE_CONTEXT_LIMIT_PRE_SUMMARY


@pytest.mark.asyncio
async def test_three_assembly_points_consistency(tmp_path: Path) -> None:
    """V0.3.9 契约 §2：主角色轮、委派纠偏重试轮、任务结果轮三处装配必须一致。

    核对：
    - 统一使用 _dialogue_request；
    - 同一回合序号 turn_index；
    - 同一项目运行上下文 runtime_context；
    - 统一角色原文窗口（排除当前用户消息，尊重摘要覆盖）。
    """
    model = FixedDialogueModel(
        CharacterTurn(speech="收到，正在处理。", delegation=None),
        CharacterTurn(speech="委派纠偏回复。", delegation=None),
        CharacterTurn(speech="任务已完成，回复结果。"),
    )
    orchestrator = _make_orchestrator(tmp_path=tmp_path)
    orchestrator.dialogue_model = model
    conv_id = "c_assembly"
    orchestrator._remember_conversation_pair(conv_id, "pair_assembly")

    proj = ProjectRef(project_id="p1", name="测试项目", root_path=str(tmp_path))
    exec_context = ExecutionContext(
        account_id="acc1",
        project=proj,
        conversation_id=conv_id,
        pair_id="pair_assembly",
    )

    # 1. 装配点 1：process_character_turn（主角色轮）
    user_msg = _user_message(1, conversation_id=conv_id, pair_id="pair_assembly")
    orchestrator._history[conv_id] = [user_msg]
    outcome1 = await orchestrator.process_character_turn(
        conversation_id=conv_id,
        user_message=user_msg,
        context=exec_context,
    )
    assert len(model.requests) == 1
    req1 = model.requests[0]

    assert req1.pair_id == "pair_assembly"
    assert req1.conversation_id == conv_id
    assert req1.turn_index == 1
    assert req1.user_message.message_id == user_msg.message_id
    # 当前 user_message 不在 recent_messages 中（按 id 排除）
    assert all(m.message_id != user_msg.message_id for m in req1.recent_messages)
    assert req1.runtime_context.project_name == "测试项目"

    # 2. 装配点 2：_retry_character_delegation（委派纠偏重试轮）
    retry_turn = await orchestrator._retry_character_delegation(
        conversation_id=conv_id,
        user_message=user_msg,
        context=exec_context,
    )
    assert len(model.requests) == 2
    req2 = model.requests[1]

    assert req2.pair_id == "pair_assembly"
    assert req2.conversation_id == conv_id
    # 回合序号与主角色轮一致
    assert req2.turn_index == req1.turn_index == 1
    # 运行上下文一致
    assert req2.runtime_context.project_name == req1.runtime_context.project_name
    assert req2.runtime_context.project_abs_dir == req1.runtime_context.project_abs_dir
    # 纠偏提示由 synthetic 承载作为 user_message
    assert req2.user_message.source == MessageSource.SYSTEM
    assert "重新输出本轮结果" in req2.user_message.text

    # 3. 装配点 3：_execute 末尾的角色结果轮（任务结果轮）
    task = TaskRequest(
        task_id="t_assembly",
        conversation_id=conv_id,
        origin_message_id=user_msg.message_id,
        instructions="执行测试任务",
    )
    await orchestrator._execute(
        task,
        origin=MessageOrigin.CHARACTER_DELEGATION,
        context=exec_context,
    )
    assert len(model.requests) == 3
    req3 = model.requests[2]

    assert req3.pair_id == "pair_assembly"
    assert req3.conversation_id == conv_id
    # 结果轮的回合序号同样以 origin_message_id 为基准，保持一致
    assert req3.turn_index == req1.turn_index == 1
    # 运行上下文一致
    assert req3.runtime_context.project_name == req1.runtime_context.project_name
    assert req3.runtime_context.project_abs_dir == req1.runtime_context.project_abs_dir
    # 携带任务结果摘要
    assert req3.result_summary is not None
    assert bool(req3.result_summary.summary)
    assert req3.user_message.source == MessageSource.SYSTEM