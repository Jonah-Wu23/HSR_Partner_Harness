import pytest

from pair_harness.adapters.reviewer import ScriptedReviewer
from pair_harness.core.approval import ApprovalManager, ApprovalRequired
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
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
    # 计划 A3：审查智能体必须收到近期上下文，而不是空列表
    _, context = reviewer.requests[0]
    assert context, "审查智能体应收到近期上下文"
    assert any(message.source == "user" for message in context)
    resolved = [e for e in outcome.engine_events if e.type == "approval.resolved"]
    assert len(resolved) == 1
    assert resolved[0].payload["actor"] == "reviewer"
    requested = [e for e in outcome.engine_events if e.type == "approval.requested"]
    assert len(requested) == 1
    # 计划 A3：审查模式下的审批请求 actor 也记为 reviewer
    assert requested[0].payload["actor"] == "reviewer"
