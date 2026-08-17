"""O3.1：审批体系统一 —— 适配器层全链路测试。

场景：orchestrator 经 CodexAppServerEngine 跑真实传输协议，
app-server 以“服务端发起请求”（item/commandExecution/requestApproval，
带 JSON-RPC id）的形式挂起工具操作；orchestrator 裁决后必须调用
resolve_approval 并以 {"decision": ...} 回复，且参数正确。
"""

import asyncio

import pytest

from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.adapters.reviewer import ScriptedReviewer
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    ProjectRef,
    ReviewerVerdict,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel
from tests.fixtures.fake_codex_app_server import FakeCodexAppServer, QueueJsonLineConnection


def make_transport(connection: QueueJsonLineConnection) -> JsonlProcessTransport:
    """连接工厂必须是协程（transport.start 会 await 它），否则任务直接
    TypeError 失败、测试侧 serve_request 永久挂起。"""

    async def factory() -> QueueJsonLineConnection:
        return connection

    return JsonlProcessTransport("unused", connection_factory=factory)


def make_orchestrator(
    tmp_path,
    engine,
    *,
    approval_mode: ApprovalMode,
    dialogue,
    reviewer=None,
    approval_callback=None,
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=approval_mode,
        reviewer=reviewer,
        approval_callback=approval_callback,
    )


async def drive_approval_turn(
    orchestrator: ConversationOrchestrator,
    server: FakeCodexAppServer,
    *,
    approval_id: int = 100,
    command: str = "pytest",
) -> dict:
    """跑一轮带原生审批请求的完整任务，返回 thread/start、turn/start、
    审批回复与最终回执。调用方负责提供裁决回调并等待返回。"""
    run_task = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="执行")
    )
    start_req = await server.serve_request({"thread": {"id": "thread-1"}})
    turn_req = await server.serve_request({"turn": {"id": "turn-1"}})
    # app-server 挂起工具操作，发起带 id 的审批请求
    await server.connection.send(
        {
            "id": approval_id,
            "method": "item/commandExecution/requestApproval",
            "params": {
                "itemId": "tool-1",
                "command": command,
                "cwd": "C:\\project",
                "reason": "需要用户审批",
            },
        }
    )
    # 等待 orchestrator 的裁决回复（resolve_approval → respond）
    reply = await server.connection.receive_request()
    return {
        "start_req": start_req,
        "turn_req": turn_req,
        "reply": reply,
        "run_task": run_task,
    }


@pytest.mark.asyncio
async def test_request_approval_forwards_decision_via_resolve_approval(tmp_path) -> None:
    """请求批准模式：approval_callback 裁决 ALLOW，回复 accept 且参数正确。"""
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )
    calls = []

    async def allow(op, approval_id: str, reason: str, conversation_id: str = "", task_id: str = "") -> ApprovalDecision:
        calls.append((approval_id, reason))
        return ApprovalDecision.ALLOW

    orchestrator = make_orchestrator(
        tmp_path,
        engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        dialogue=dialogue,
        approval_callback=allow,
    )
    step = await drive_approval_turn(orchestrator, server)

    # 裁决回调收到引擎的 approval_id（JSON-RPC 请求 id）与真实理由
    assert calls == [("100", "需要用户审批")]
    # resolve_approval 以 {id, result.decision} 回复挂起的请求
    assert step["reply"]["id"] == 100
    assert step["reply"]["result"] == {"decision": "accept"}

    # 引擎继续执行并正常收尾
    await server.notify("item/started", {"turnId": "turn-1", "item": {"id": "tool-1", "type": "commandExecution", "command": "pytest"}})
    await server.notify("item/completed", {"turnId": "turn-1", "item": {"id": "tool-1", "type": "commandExecution", "command": "pytest", "status": "completed", "aggregatedOutput": "2 passed"}})
    await server.notify("item/completed", {"turnId": "turn-1", "item": {"id": "msg", "type": "agentMessage", "text": "完成"}})
    await server.notify("turn/completed", {"turn": {"id": "turn-1", "status": "completed"}})
    outcome = await step["run_task"]

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    # 事件流包含请求与裁决（actor=user）
    requested = [e for e in outcome.engine_events if e.type == "approval.requested"]
    resolved = [e for e in outcome.engine_events if e.type == "approval.resolved"]
    assert len(requested) == 1
    assert requested[0].payload["approval_id"] == "100"
    assert len(resolved) == 1
    assert resolved[0].payload["actor"] == "user"
    assert resolved[0].payload["decision"] == "allow"
    await transport.close()


@pytest.mark.asyncio
async def test_full_auto_replies_accept_without_callback(tmp_path) -> None:
    """完全允许运行：引擎仍发起请求时直接回复 accept，无需用户交互。"""
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )
    orchestrator = make_orchestrator(
        tmp_path,
        engine,
        approval_mode=ApprovalMode.FULL_AUTO,
        dialogue=dialogue,
    )
    step = await drive_approval_turn(orchestrator, server)

    assert step["reply"]["id"] == 100
    assert step["reply"]["result"] == {"decision": "accept"}

    await server.notify("item/started", {"turnId": "turn-1", "item": {"id": "tool-1", "type": "commandExecution", "command": "pytest"}})
    await server.notify("item/completed", {"turnId": "turn-1", "item": {"id": "tool-1", "type": "commandExecution", "command": "pytest", "status": "completed"}})
    await server.notify("item/completed", {"turnId": "turn-1", "item": {"id": "msg", "type": "agentMessage", "text": "完成"}})
    await server.notify("turn/completed", {"turn": {"id": "turn-1", "status": "completed"}})
    outcome = await step["run_task"]

    assert outcome.receipt.status == "completed"
    # 设计 §9：完全允许运行模式不拦截操作，工具与审批事件照常持久化——
    # 原始 requestApproval 事件保留在流中（透明记录），但无用户交互、
    # 不合成 resolved 事件（无 actor 裁决）。
    requested = [e for e in outcome.engine_events if e.type == "approval.requested"]
    resolved = [e for e in outcome.engine_events if e.type == "approval.resolved"]
    assert len(requested) == 1
    assert requested[0].payload["approval_id"] == "100"
    assert resolved == []
    await transport.close()


@pytest.mark.asyncio
async def test_review_mode_high_risk_reviewer_denies_and_replies_decline(tmp_path) -> None:
    """帮我审核模式：高风险操作交审查智能体，否决后回复 decline。"""
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="被否决了，但模型继续调整。"),
    )
    reviewer = ScriptedReviewer(
        [ReviewerVerdict(allow=False, reason="危险", suggestion="用 shutil 替代")]
    )
    orchestrator = make_orchestrator(
        tmp_path,
        engine,
        approval_mode=ApprovalMode.REVIEW,
        dialogue=dialogue,
        reviewer=reviewer,
    )
    step = await drive_approval_turn(orchestrator, server, command="rm -rf build")

    assert len(reviewer.requests) == 1
    assert step["reply"]["id"] == 100
    assert step["reply"]["result"] == {"decision": "decline"}

    # 被否决后引擎继续 turn，任务成败由终态决定
    await server.notify("item/completed", {"turnId": "turn-1", "item": {"id": "msg", "type": "agentMessage", "text": "已更换方案"}})
    await server.notify("turn/completed", {"turn": {"id": "turn-1", "status": "completed"}})
    outcome = await step["run_task"]

    assert outcome.receipt.status == "completed"
    resolved = [e for e in outcome.engine_events if e.type == "approval.resolved"]
    assert resolved[0].payload["actor"] == "reviewer"
    assert resolved[0].payload["decision"] == "deny"
    await transport.close()


@pytest.mark.asyncio
async def test_open_session_maps_policy_params_to_thread_start(tmp_path) -> None:
    """O3.1：open_session 预留策略映射位置——thread/start 参数携带
    approvalPolicy / sandbox / approvalsReviewer（仅非 None 时发送）。"""
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    project = ProjectRef(project_id="p", name="p", root_path="C:\\project")

    open_task = asyncio.create_task(
        engine.open_session(
            project,
            approval_policy="on-request",
            sandbox="workspace-write",
            approvals_reviewer="user",
        )
    )
    request = await server.serve_request({"thread": {"id": "thread-1"}})
    assert request["method"] == "thread/start"
    assert request["params"] == {
        "cwd": "C:\\project",
        "approvalPolicy": "on-request",
        "sandbox": "workspace-write",
        "approvalsReviewer": "user",
    }
    await open_task
    await transport.close()


@pytest.mark.asyncio
async def test_open_session_omits_policy_params_when_none(tmp_path) -> None:
    """默认 None 不发送策略字段，保持既有协议形态。"""
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    project = ProjectRef(project_id="p", name="p", root_path="C:\\project")

    open_task = asyncio.create_task(engine.open_session(project))
    request = await server.serve_request({"thread": {"id": "thread-1"}})
    assert request["params"] == {"cwd": "C:\\project"}
    await open_task
    await transport.close()
