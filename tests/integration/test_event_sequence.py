"""O4.1：事件序号统一 —— orchestrator 出口事件流序号连续无碰撞。

适配器（codec）不再自定序号（全部固定 0），编排器在出口处用单一
计数器重排所有事件——包括原生引擎事件与合成事件（approval.requested /
approval.resolved / 否决产生的 tool.finished(denied)）。

三个场景覆盖合成事件的三种来源：
1. 原生 requestApproval + 用户裁决（adjudicate 合成 resolved）；
2. 原生审批请求被沙箱拦截（合成否决 tool.finished）；
3. 门控路径请求批准被用户否决（合成 requested + resolved + 否决收尾）。
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    ProjectRef,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel
from tests.fixtures.fake_codex_app_server import FakeCodexAppServer, QueueJsonLineConnection

from test_codex_approval_flow import drive_approval_turn, make_transport


def assert_contiguous(events) -> None:
    """断言事件流序号从 0 连续递增、无碰撞。"""
    sequences = [e.sequence for e in events]
    assert sequences == list(range(len(sequences))), f"序号不连续: {sequences}"


def make_orchestrator(
    tmp_path,
    engine,
    *,
    approval_mode: ApprovalMode,
    dialogue,
    approval_callback=None,
) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=approval_mode,
        approval_callback=approval_callback,
    )


@pytest.mark.asyncio
async def test_native_approval_flow_sequence_contiguous(tmp_path) -> None:
    """原生 requestApproval 裁决通过：请求/裁决/工具/收尾事件序号连续。"""
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="执行")),
        CharacterTurn(speech="完成了。"),
    )

    async def allow(op, approval_id: str, reason: str) -> ApprovalDecision:
        return ApprovalDecision.ALLOW

    orchestrator = make_orchestrator(
        tmp_path,
        engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        dialogue=dialogue,
        approval_callback=allow,
    )
    step = await drive_approval_turn(orchestrator, server)
    assert step["reply"]["result"] == {"decision": "accept"}

    await server.notify("item/started", {"turnId": "turn-1", "item": {"id": "tool-1", "type": "commandExecution", "command": "pytest"}})
    await server.notify("item/completed", {"turnId": "turn-1", "item": {"id": "tool-1", "type": "commandExecution", "command": "pytest", "status": "completed", "aggregatedOutput": "2 passed"}})
    await server.notify("item/completed", {"turnId": "turn-1", "item": {"id": "msg", "type": "agentMessage", "text": "完成"}})
    await server.notify("turn/completed", {"turn": {"id": "turn-1", "status": "completed"}})
    outcome = await step["run_task"]

    events = list(outcome.engine_events)
    assert [e.type for e in events] == [
        "approval.requested",  # codec 映射（sequence 固定 0，出口重排）
        "approval.resolved",   # adjudicate 合成
        "tool.started",
        "tool.finished",
        "assistant.final",
        "turn.completed",
    ]
    assert_contiguous(events)
    await transport.close()


@pytest.mark.asyncio
async def test_sandbox_deny_sequence_contiguous(tmp_path) -> None:
    """原生审批请求被沙箱拦截：合成否决事件与后续收尾序号连续。"""
    connection = QueueJsonLineConnection()
    transport = make_transport(connection)
    engine = CodexAppServerEngine(transport)
    server = FakeCodexAppServer(connection)
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="写文件")),
        CharacterTurn(speech="失败了。"),
    )
    orchestrator = make_orchestrator(
        tmp_path,
        engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        dialogue=dialogue,
    )
    run_task = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="写文件")
    )
    await server.serve_request({"thread": {"id": "thread-1"}})
    await server.serve_request({"turn": {"id": "turn-1"}})
    # 越界写路径：grantRoot 在项目根之外 → 沙箱直接否决
    await server.connection.send(
        {
            "id": 42,
            "method": "item/fileChange/requestApproval",
            "params": {"itemId": "tool-out", "grantRoot": "C:\\outside", "reason": "写文件"},
        }
    )
    reply = await server.connection.receive_request()
    assert reply["id"] == 42
    assert reply["result"] == {"decision": "decline"}

    await server.notify("turn/completed", {"turn": {"id": "turn-1", "status": "completed"}})
    outcome = await run_task

    events = list(outcome.engine_events)
    assert [e.type for e in events] == [
        "approval.requested",   # codec 映射
        "tool.finished",        # 沙箱否决合成（status=denied）
        "turn.completed",
    ]
    assert events[1].payload["status"] == "denied"
    assert_contiguous(events)
    await transport.close()


class _GateDenyEngine(ScriptedCodingEngine):
    """门控路径引擎：TOOL_STARTED 后立刻给出收尾事件（若未被 break 消费）。

    被否决时编排器在 TOOL_STARTED 处 break，剩余事件不会被消费。
    """

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self.requests.append(request)
        common = {
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "engine_turn_id": "turn-gate-1",
        }
        yield EngineEvent(sequence=0, type=EngineEventType.TURN_STARTED, **common)
        yield EngineEvent(
            sequence=1,
            type=EngineEventType.TOOL_STARTED,
            tool_call_id="tool-gate-1",
            payload={"title": "删除构建目录", "details": "rm -rf build", "command": "rm -rf build"},
            **common,
        )
        yield EngineEvent(
            sequence=2,
            type=EngineEventType.ASSISTANT_FINAL,
            payload={"text": "尝试删除"},
            **common,
        )
        yield EngineEvent(
            sequence=3,
            type=EngineEventType.TURN_COMPLETED,
            payload={"summary": "结束"},
            **common,
        )


@pytest.mark.asyncio
async def test_gate_path_user_deny_sequence_contiguous(tmp_path) -> None:
    """门控路径用户否决：requested + resolved + 否决收尾全部连续。"""
    engine = _GateDenyEngine()
    dialogue = FixedDialogueModel(
        CharacterTurn(speech="交给古代机械。", delegation=TaskRequestDraft(instructions="删目录")),
        CharacterTurn(speech="被否决了。"),
    )

    async def deny(op, approval_id: str, reason: str) -> ApprovalDecision:
        return ApprovalDecision.DENY

    orchestrator = make_orchestrator(
        tmp_path,
        engine,
        approval_mode=ApprovalMode.REQUEST_APPROVAL,
        dialogue=dialogue,
        approval_callback=deny,
    )
    outcome = await orchestrator.handle_character_input(conversation_id="c", text="删目录")

    events = list(outcome.engine_events)
    assert [e.type for e in events] == [
        "turn.started",          # 引擎事件（原序号 0，出口重排）
        "tool.started",          # 引擎事件
        "approval.requested",    # gate 合成（ApprovalRequired）
        "approval.resolved",     # 用户裁决合成
        "tool.finished",         # 否决收尾合成（status=denied）
    ]
    assert events[-1].payload["status"] == "denied"
    assert outcome.receipt is not None
    assert outcome.receipt.status == "failed"
    assert_contiguous(events)
