import pytest

from pair_harness.adapters.reviewer import ScriptedReviewer
from pair_harness.core.approval import ApprovalManager, ApprovalRequired
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    EngineEvent,
    EngineEventType,
    PendingOperation,
    ProjectRef,
    ReviewerVerdict,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.risk_rules import default_risk_rules
from tests.fakes import FixedDialogueModel, RecordingCodingEngine


@pytest.mark.asyncio
async def test_full_auto_allows_tool_without_approval(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="执行")

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"


@pytest.mark.asyncio
async def test_request_approval_denies_without_callback(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="被否决了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="执行")

    assert outcome.receipt is not None
    assert outcome.receipt.status == "failed"
    assert "否决" in outcome.receipt.errors[0]


@pytest.mark.asyncio
async def test_request_approval_callback_allows_tool(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})

    async def allow(op, approval_id: str, reason: str) -> ApprovalDecision:
        return ApprovalDecision.ALLOW

    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        approval_callback=allow,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="执行")

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    requested = [e for e in outcome.engine_events if e.type == "approval.requested"]
    resolved = [e for e in outcome.engine_events if e.type == "approval.resolved"]
    assert len(requested) == 1
    assert len(resolved) == 1


@pytest.mark.asyncio
async def test_native_engine_never_synthesizes_approval_after_tool_started(
    tmp_path,
) -> None:
    class NativeApprovalEngine(RecordingCodingEngine):
        native_preexecution_approval = True

    dialogue = FixedDialogueModel(
        CharacterTurn(
            speech="交给古代机械。",
            delegation=TaskRequestDraft(instructions="列出文件"),
        ),
        CharacterTurn(speech="完成了。"),
    )
    engine = NativeApprovalEngine(
        tool_payload={"tool_kind": "shell", "command": "ls"}
    )
    approval_calls = 0

    async def should_not_be_called(*args):
        nonlocal approval_calls
        approval_calls += 1
        return ApprovalDecision.ALLOW

    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        approval_callback=should_not_be_called,
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="列出文件"
    )

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    assert approval_calls == 0
    assert not any(
        event.type == EngineEventType.APPROVAL_REQUESTED
        for event in outcome.engine_events
    )


@pytest.mark.asyncio
async def test_allow_for_conversation_caches_same_signature(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="再执行")),
        CharacterTurn(speech="又完成了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    calls = []

    async def allow_once(op, approval_id: str, reason: str) -> ApprovalDecision:
        calls.append((op, approval_id, reason))
        if len(calls) == 1:
            return ApprovalDecision.ALLOW_FOR_CONVERSATION
        return ApprovalDecision.ALLOW

    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        approval_callback=allow_once,
    )

    outcome1 = await orchestrator.handle_character_input(conversation_id="c", text="执行")
    assert outcome1.receipt.status == "completed"

    # 同一签名不应再次请求审批
    outcome2 = await orchestrator.handle_character_input(conversation_id="c", text="再执行")
    assert outcome2.receipt.status == "completed"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_allow_for_conversation_shell_signature_needs_two_tokens() -> None:
    """O1.5：shell 签名取前两个词元。

    允许 ``git status`` 后，``git push --force origin main`` 的签名是
    ``git push``，不得命中缓存；且破坏性命令命中高风险规则，即便用户
    再次选择“本对话内允许”也不写缓存，第三次执行仍要求审批。
    """
    manager = ApprovalManager(
        mode=ApprovalMode.REQUEST_APPROVAL,
        rules=default_risk_rules(),
    )

    async def require(command: str) -> ApprovalRequired:
        op = PendingOperation(tool_kind="shell", command=command)
        with pytest.raises(ApprovalRequired) as exc:
            await manager.gate(
                op,
                conversation_id="c",
                task_id="t",
                engine_turn_id="e",
                sequence=1,
            )
        return exc.value

    first = await require("git status")
    manager.resolve(first.approval_id, ApprovalDecision.ALLOW_FOR_CONVERSATION)

    # 同一签名命中缓存直接放行
    cached = await manager.gate(
        PendingOperation(tool_kind="shell", command="git status"),
        conversation_id="c",
        task_id="t",
        engine_turn_id="e",
        sequence=2,
    )
    assert cached.decision == ApprovalDecision.ALLOW_FOR_CONVERSATION

    # 前两个词元不同（git push），仍需审批
    second = await require("git push --force origin main")
    assert second.approval_id != first.approval_id

    # 破坏性命令命中高风险规则，resolve 时不写缓存
    manager.resolve(second.approval_id, ApprovalDecision.ALLOW_FOR_CONVERSATION)
    third = await require("git push --force origin main")
    assert third.approval_id != second.approval_id


@pytest.mark.asyncio
async def test_allow_for_conversation_never_caches_sensitive_path() -> None:
    """O1.5：命中敏感路径的操作永不写入会话缓存。

    用户对 ``.env`` 写入选择“本对话内允许”后，同对话内再次执行同一
    操作仍必须重新审批。
    """
    manager = ApprovalManager(
        mode=ApprovalMode.REQUEST_APPROVAL,
        rules=default_risk_rules(),
    )
    op = PendingOperation(
        tool_kind="file_write",
        paths=["C:/proj/.env"],
        summary="写入环境变量",
    )

    with pytest.raises(ApprovalRequired) as exc:
        await manager.gate(
            op,
            conversation_id="c",
            task_id="t",
            engine_turn_id="e",
            sequence=1,
        )
    req = exc.value
    manager.resolve(req.approval_id, ApprovalDecision.ALLOW_FOR_CONVERSATION)

    with pytest.raises(ApprovalRequired) as exc2:
        await manager.gate(
            op,
            conversation_id="c",
            task_id="t",
            engine_turn_id="e",
            sequence=2,
        )
    assert exc2.value.approval_id != req.approval_id


@pytest.mark.asyncio
async def test_allow_for_conversation_file_signature_includes_parent_dir() -> None:
    """O1.5：file 类签名纳入父目录维度。

    允许 ``proj/src/a.py`` 后，同目录 ``proj/src/b.py`` 缓存命中直接
    放行；不同目录 ``proj/other/c.py`` 仍要求审批。
    """
    manager = ApprovalManager(
        mode=ApprovalMode.REQUEST_APPROVAL,
        rules=default_risk_rules(),
    )

    async def require(op: PendingOperation) -> ApprovalRequired:
        with pytest.raises(ApprovalRequired) as exc:
            await manager.gate(
                op,
                conversation_id="c",
                task_id="t",
                engine_turn_id="e",
                sequence=1,
            )
        return exc.value

    first = await require(
        PendingOperation(tool_kind="file_write", paths=["proj/src/a.py"])
    )
    manager.resolve(first.approval_id, ApprovalDecision.ALLOW_FOR_CONVERSATION)

    # 同父目录、同工具类型：缓存命中
    same_dir = await manager.gate(
        PendingOperation(tool_kind="file_write", paths=["proj/src/b.py"]),
        conversation_id="c",
        task_id="t",
        engine_turn_id="e",
        sequence=2,
    )
    assert same_dir.decision == ApprovalDecision.ALLOW_FOR_CONVERSATION

    # 不同父目录：仍需审批
    other = await require(
        PendingOperation(tool_kind="file_write", paths=["proj/other/c.py"])
    )
    assert other.approval_id != first.approval_id


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
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="执行")

    assert outcome.receipt is not None
    assert outcome.receipt.status == "failed"
    assert any("沙箱" in err or "越界" in err for err in outcome.receipt.errors)
    # 计划 A3：沙箱越界产生的 tool.finished 状态必须是 denied
    finished = [e for e in outcome.engine_events if e.type == "tool.finished"]
    assert finished and finished[-1].payload["status"] == "denied"


@pytest.mark.asyncio
async def test_review_mode_low_risk_allows_tool(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.REVIEW,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="执行")

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"


@pytest.mark.asyncio
async def test_review_mode_high_risk_calls_reviewer(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="被审查智能体否决了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "rm -rf build"})
    reviewer = ScriptedReviewer([ReviewerVerdict(allow=False, reason="危险", suggestion="用 shutil 替代")])
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.REVIEW,
        reviewer=reviewer,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="执行")

    assert outcome.receipt is not None
    assert outcome.receipt.status == "failed"
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
    # 计划 A3：审查模式下的审批请求 actor 也记为 reviewer
    assert requested[0].payload["actor"] == "reviewer"


# ---- B1：审批模式 → app-server 策略映射（设计 §14.6）----


@pytest.mark.asyncio
async def test_engine_policy_on_request_mode_maps_to_untrusted(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})

    async def allow(op, approval_id: str, reason: str) -> ApprovalDecision:
        return ApprovalDecision.ALLOW

    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        approval_callback=allow,
    )

    outcome = await orchestrator.handle_character_input(conversation_id="c", text="执行")
    assert outcome.receipt is not None
    policy = engine.opened_policies[-1]
    assert policy == {
        "approvalPolicy": "untrusted",
        "sandbox": "read-only",
        "approvalsReviewer": "user",
    }


@pytest.mark.asyncio
async def test_engine_policy_full_auto_maps_to_never(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    await orchestrator.handle_character_input(conversation_id="c", text="执行")

    assert engine.opened_policies[-1]["approvalPolicy"] == "never"
    assert engine.opened_policies[-1]["sandbox"] == "workspace-write"
    assert engine.opened_policies[-1]["approvalsReviewer"] == "user"


@pytest.mark.asyncio
async def test_engine_policy_review_maps_to_untrusted(tmp_path) -> None:
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )
    engine = RecordingCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.REVIEW,
        reviewer=ScriptedReviewer([ReviewerVerdict(allow=True)]),
    )

    await orchestrator.handle_character_input(conversation_id="c", text="执行")

    assert engine.opened_policies[-1]["approvalPolicy"] == "untrusted"
    assert engine.opened_policies[-1]["sandbox"] == "read-only"
    assert engine.opened_policies[-1]["approvalsReviewer"] == "user"


# ---- B1 联调加固：信息不足的操作在 REVIEW 模式不得按低风险放行 ----


@pytest.mark.asyncio
async def test_review_adjudicate_insufficient_info_routes_to_reviewer() -> None:
    """app-server 0.147.0 的 fileChange 审批请求不带路径（grantRoot/reason 均
    为 None），映射出的操作既无 command 也无 paths。REVIEW 模式下这类操作
    不得直接放行（删除会绕过审查），必须转审查智能体结合上下文裁决。"""
    reviewer = ScriptedReviewer([ReviewerVerdict(allow=False, reason="无法确认", suggestion="补充路径")])
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
        reviewer=reviewer,
    )
    op = PendingOperation(
        tool_kind="file_write",
        summary="工具操作",
    )
    requested = EngineEvent(
        conversation_id="c",
        task_id="t",
        engine_turn_id="e",
        sequence=1,
        type=EngineEventType.APPROVAL_REQUESTED,
        tool_call_id="tc-1",
        payload={"approval_id": "0"},
    )
    outcome = await manager.adjudicate(
        op,
        requested_event=requested,
        conversation_id="c",
        task_id="t",
        engine_turn_id="e",
        tool_call_id="tc-1",
        context=[],
    )
    assert len(reviewer.requests) == 1
    assert outcome.decision == ApprovalDecision.DENY
    resolved = [e for e in outcome.events if e.type == "approval.resolved"]
    assert resolved[0].payload["reason"] == "无法确认"


@pytest.mark.asyncio
async def test_review_adjudicate_insufficient_info_reviewer_may_allow() -> None:
    """信息不足转审查后，审查智能体结合上下文可以放行（如常规创建）。"""
    reviewer = ScriptedReviewer([ReviewerVerdict(allow=True)])
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
        reviewer=reviewer,
    )
    op = PendingOperation(tool_kind="file_write", summary="工具操作")
    requested = EngineEvent(
        conversation_id="c",
        task_id="t",
        engine_turn_id="e",
        sequence=1,
        type=EngineEventType.APPROVAL_REQUESTED,
        tool_call_id="tc-1",
        payload={"approval_id": "0"},
    )
    outcome = await manager.adjudicate(
        op,
        requested_event=requested,
        conversation_id="c",
        task_id="t",
        engine_turn_id="e",
        tool_call_id="tc-1",
        context=[],
    )
    assert outcome.decision == ApprovalDecision.ALLOW


@pytest.mark.asyncio
async def test_review_gate_insufficient_info_routes_to_reviewer() -> None:
    """gate 路径（无原生审批请求的引擎）同样对信息不足操作转审查。"""
    reviewer = ScriptedReviewer([ReviewerVerdict(allow=False, reason="信息不足", suggestion="补路径")])
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
        reviewer=reviewer,
    )
    op = PendingOperation(tool_kind="file_write", summary="工具操作")
    outcome = await manager.gate(
        op,
        conversation_id="c",
        task_id="t",
        engine_turn_id="e",
        sequence=1,
    )
    assert len(reviewer.requests) == 1
    assert outcome.decision == ApprovalDecision.DENY


@pytest.mark.asyncio
async def test_review_regular_file_write_with_path_still_low_risk() -> None:
    """带路径的常规 file_write 仍是低风险直接放行，不打扰审查智能体。"""
    reviewer = ScriptedReviewer([ReviewerVerdict(allow=False, reason="不应被调用", suggestion="")])
    manager = ApprovalManager(
        mode=ApprovalMode.REVIEW,
        rules=default_risk_rules(),
        reviewer=reviewer,
    )
    op = PendingOperation(tool_kind="file_write", paths=["proj/src/a.py"], summary="写入代码")
    outcome = await manager.gate(
        op,
        conversation_id="c",
        task_id="t",
        engine_turn_id="e",
        sequence=1,
    )
    assert len(reviewer.requests) == 0
    assert outcome.decision == ApprovalDecision.ALLOW
