import pytest

from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    ProjectRef,
    ReviewerVerdict,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.storage.sqlite_store import SQLiteStore
from tests.fakes import (
    FixedDialogueModel,
    RecordingCodingEngine,
    ScriptedReviewer,
    allow_approval,
    deny_approval,
    make_context,
    unexpected_approval,
)


def _context(tmp_path, approval_mode: ApprovalMode):
    return make_context(
        ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        conversation_id="c",
        approval_mode=approval_mode,
    )


def _delegating_dialogue() -> FixedDialogueModel:
    return FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="收到结果。"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("approval_mode", "approval_callback", "resolved_count"),
    [
        (ApprovalMode.FULL_AUTO, unexpected_approval, 0),
        (ApprovalMode.REQUEST_APPROVAL, allow_approval, 1),
        # 低风险且带命令的操作在审查模式直接放行，不经审查智能体
        (ApprovalMode.REVIEW, unexpected_approval, 0),
    ],
)
async def test_low_risk_tool_runs_in_each_approval_mode(
    tmp_path, approval_mode, approval_callback, resolved_count
) -> None:
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    orchestrator = ConversationOrchestrator(
        dialogue_model=_delegating_dialogue(),
        coding_engine=engine,
        approval_callback=approval_callback,
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="执行", context=_context(tmp_path, approval_mode)
    )

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    # 引擎会话按任务的审批模式打开
    assert engine.opened_approval_modes == [approval_mode]
    types = [event.type for event in outcome.engine_events]
    assert types.count("approval.requested") == 1
    assert types.count("approval.resolved") == resolved_count
    finished = [e for e in outcome.engine_events if e.type == "tool.finished"]
    assert [e.payload["status"] for e in finished] == ["succeeded"]


@pytest.mark.asyncio
async def test_user_deny_finishes_tool_as_denied_and_persists_it(tmp_path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(project_id="p", name="p", root_path=str(tmp_path))
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="c"
        )
        orchestrator = ConversationOrchestrator(
            dialogue_model=_delegating_dialogue(),
            coding_engine=RecordingCodingEngine(
                tool_payload={"tool_kind": "shell", "command": "ls"}
            ),
            store=store,
            approval_callback=deny_approval,
        )

        outcome = await orchestrator.handle_character_input(
            conversation_id="c",
            text="执行",
            context=_context(tmp_path, ApprovalMode.REQUEST_APPROVAL),
        )

        events = outcome.engine_events
        assert [event.type for event in events] == [
            "turn.started",
            "assistant.delta",
            "tool.started",
            "approval.requested",
            "approval.resolved",
            "tool.finished",
            "assistant.final",
            "turn.completed",
        ]
        # 编排器合成的裁决与否决事件和引擎事件共用一个出口序号
        assert [event.sequence for event in events] == list(range(len(events)))
        assert events[5].payload["status"] == "denied"
        # 引擎收到否决后以 turn.completed 收尾，回执状态由 turn 终态决定
        assert outcome.receipt is not None
        assert outcome.receipt.status == "completed"
        assert [run.status for run in outcome.tool_runs] == ["denied"]
        assert store.load_conversation("c").tool_runs == outcome.tool_runs


@pytest.mark.asyncio
async def test_sandbox_violation_denies_tool(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="越界了。"),
    )
    engine = RecordingCodingEngine(
        tool_payload={"tool_kind": "file_write", "paths": ["../outside.txt"]}
    )
    orchestrator = ConversationOrchestrator(
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_callback=unexpected_approval,
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c",
        text="执行",
        context=_context(tmp_path, ApprovalMode.FULL_AUTO),
    )

    assert outcome.receipt is not None
    assert outcome.receipt.status == "failed"
    assert any("沙箱" in err or "越界" in err for err in outcome.receipt.errors)
    finished = [e for e in outcome.engine_events if e.type == "tool.finished"]
    assert finished and finished[-1].payload["status"] == "denied"


@pytest.mark.asyncio
async def test_review_mode_high_risk_calls_reviewer(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="被审查智能体否决了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "rm -rf build"})
    reviewer = ScriptedReviewer([ReviewerVerdict(allow=False, reason="危险", suggestion="用 shutil 替代")])
    orchestrator = ConversationOrchestrator(
        dialogue_model=dialogue,
        coding_engine=engine,
        reviewer=reviewer,
        approval_callback=unexpected_approval,
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c",
        text="执行",
        context=_context(tmp_path, ApprovalMode.REVIEW),
    )

    # 否决回复给引擎后由引擎终态决定回执；演示引擎跳过工具后正常收尾。
    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    assert len(reviewer.requests) == 1
    # 审查智能体只读取当前聊天里用户最后发送的三条消息
    _, context = reviewer.requests[0]
    assert context, "审查智能体应收到最近的用户消息"
    assert len(context) <= 3
    assert all(message.source == "user" for message in context)
    resolved = [e for e in outcome.engine_events if e.type == "approval.resolved"]
    assert len(resolved) == 1
    assert resolved[0].payload["actor"] == "reviewer"
    requested = [e for e in outcome.engine_events if e.type == "approval.requested"]
    assert len(requested) == 1
    # 审查模式下的审批请求也由审查智能体裁决
    assert requested[0].payload["actor"] == "reviewer"
