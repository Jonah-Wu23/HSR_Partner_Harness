"""V0.3.2 M0：三个核心问题的复现基线（先调查、再冻结契约）。

这些测试描述 V0.3.2 目标行为，在 0.3.1 实现上按预期失败：
1. 工作台把多段思考/正文/工具压平成单条消息；
2. `GlobalEngineState` 只允许一个全局活动任务；
3. 共享通知队列无法按 Reasonix session 路由，两个 session 的
   事件会被错误消费者拿走。
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    MessageKind,
    MessageOrigin,
    MessageSource,
    MessageStatus,
    ProjectRef,
    TaskRequest,
    TaskRequestDraft,
    ToolRun,
)
from pair_harness.core.engine_state import GlobalEngineState
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.adapters.demo import ScriptedCodingEngine
from tests.fakes import FixedDialogueModel
from tests.fixtures.fake_codex_app_server import QueueJsonLineConnection


class SequenceEngine(ScriptedCodingEngine):
    """按固定脚本回放引擎事件的引擎（M0 复现用）。"""

    engine_type = "sequence"

    def __init__(self, events: list[EngineEvent]) -> None:
        super().__init__()
        self._script = events

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self.requests.append(request)
        for event in self._script:
            yield event.model_copy(
                update={
                    "conversation_id": request.conversation_id,
                    "task_id": request.task_id,
                    "engine_turn_id": "seq-turn-1",
                }
            )


def _event(
    event_type: EngineEventType,
    payload: dict | None = None,
    tool_call_id: str | None = None,
) -> EngineEvent:
    return EngineEvent(
        conversation_id="conv",
        task_id="unused",
        engine_turn_id="seq-turn-1",
        sequence=0,
        type=event_type,
        tool_call_id=tool_call_id,
        payload=payload or {},
    )


INTERLEAVED_EVENTS = [
    _event(EngineEventType.TURN_STARTED),
    # 第一段：思考 + 阶段性正文
    _event(EngineEventType.ASSISTANT_REASONING_DELTA, {"text": "先看目录结构。"}),
    _event(EngineEventType.ASSISTANT_DELTA, {"text": "我先查看 src 目录。"}),
    # 工具 1
    _event(
        EngineEventType.TOOL_STARTED,
        {"title": "list", "command": "Get-ChildItem src"},
        tool_call_id="tool-1",
    ),
    _event(
        EngineEventType.TOOL_FINISHED,
        {"status": "succeeded", "title": "list", "summary": "列出 12 个文件"},
        tool_call_id="tool-1",
    ),
    # 第二段：工具后再思考
    _event(EngineEventType.ASSISTANT_REASONING_DELTA, {"text": "再看测试分层。"}),
    # 工具 2
    _event(
        EngineEventType.TOOL_STARTED,
        {"title": "list", "command": "Get-ChildItem tests"},
        tool_call_id="tool-2",
    ),
    _event(
        EngineEventType.TOOL_FINISHED,
        {"status": "succeeded", "title": "list", "summary": "列出 3 个目录"},
        tool_call_id="tool-2",
    ),
    # 最终正文
    _event(EngineEventType.ASSISTANT_DELTA, {"text": "src 分为 core 和 adapters。"}),
    _event(EngineEventType.ASSISTANT_FINAL, {"text": "src 分为 core 和 adapters，tests 分三层。"}),
    _event(EngineEventType.TURN_COMPLETED, {"status": "completed"}),
]


def _make_orchestrator(engine: ScriptedCodingEngine) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(
            CharacterTurn(speech="交给古代机械。", delegation=None),
            CharacterTurn(speech="做完了。", delegation=None),
            CharacterTurn(speech="结果收到。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )


def _assistant_messages(history) -> list:
    return [
        m
        for m in history
        if m.source == MessageSource.ASSISTANT
        and m.kind == MessageKind.ASSISTANT_NATURAL_LANGUAGE
    ]


@pytest.mark.asyncio
async def test_multisegment_timeline_preserves_interleaved_order() -> None:
    """M1 目标：思考 → 工具 → 再思考 → 工具 → 正文形成两个助手 segment。

    消息 id 带 segment index（assistant:{conv}:{task}:{index}），并与工具卡
    共享单调 timeline_order；0.3.1 把整轮压成一条无序号消息，本测试失败。
    """
    engine = SequenceEngine(INTERLEAVED_EVENTS)
    orchestrator = _make_orchestrator(engine)
    outcome = await orchestrator.handle_direct_input(
        conversation_id="conv", text="检查 src 和 tests 目录"
    )
    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    task_id = outcome.task.task_id

    segments = _assistant_messages(orchestrator._history["conv"])
    assert [m.message_id for m in segments] == [
        f"assistant:conv:{task_id}:0",
        f"assistant:conv:{task_id}:1",
        f"assistant:conv:{task_id}:2",
    ]
    # segment 0 = 工具前的阶段性说明；segment 1 = 工具后仅思考；
    # segment 2 = 最终正文（ASSISTANT_FINAL 覆盖流式累积）
    assert segments[0].text == "我先查看 src 目录。"
    assert segments[1].text == ""
    assert segments[2].text == "src 分为 core 和 adapters，tests 分三层。"
    # segment 与工具共享同一聊天的单调工作台序号，交错顺序保留
    orders = [m.timeline_order for m in segments]
    tool_orders = [run.timeline_order for run in outcome.tool_runs]
    assert all(order is not None for order in orders)
    assert all(order is not None for order in tool_orders)
    assert orders[0] < tool_orders[0] < orders[1] < tool_orders[1] < orders[2]


@pytest.mark.asyncio
async def test_multisegment_streaming_emits_segmented_message_delta() -> None:
    """M1 目标：message.delta 携带 segment_index 与 timeline_order。"""
    engine = SequenceEngine(INTERLEAVED_EVENTS)
    orchestrator = _make_orchestrator(engine)
    deltas: list[dict] = []

    def on_engine_event(event: EngineEvent) -> None:
        # 由 application_service 层转发；M0 直接在此断言编排器暴露的信息
        deltas.append({"type": event.type, "payload": dict(event.payload)})

    orchestrator.on_engine_event = on_engine_event
    await orchestrator.handle_direct_input(
        conversation_id="conv", text="检查 src 和 tests 目录"
    )
    assert deltas, "engine events should be forwarded during the turn"


def test_engine_state_allows_different_conversations_concurrently() -> None:
    """M4 目标：并发单位是 conversation，A/B 可同时 active；同聊天第二个被拒。

    0.3.1 的 GlobalEngineState 只有一个全局槽位，B start 直接失败。
    """
    state = GlobalEngineState()
    a = state.start(project_id="p", conversation_id="conv-a", task_id="task-a")
    b = state.start(project_id="p", conversation_id="conv-b", task_id="task-b")
    assert a.task_id == "task-a"
    assert b.task_id == "task-b"
    with pytest.raises(Exception):
        state.start(project_id="p", conversation_id="conv-a", task_id="task-a2")
    state.finish("task-a")
    # B 仍然 active，A 的结束不影响 B
    assert state.get_for_conversation("conv-b") is not None
    assert state.get_for_conversation("conv-a") is None


@pytest.mark.asyncio
async def test_transport_routes_session_notifications_by_session_id() -> None:
    """M3 目标：subscribe_session 按 params.sessionId 路由通知。

    0.3.1 所有通知共用一个队列，两个消费者互相抢事件，本测试失败。
    """
    connection = QueueJsonLineConnection()

    async def factory():
        return connection

    transport = JsonlProcessTransport("unused", connection_factory=factory)
    await transport.start()

    sub_a = transport.subscribe_session("session-a")
    sub_b = transport.subscribe_session("session-b")
    try:
        await connection.server_to_client.put(
            _jsonl(
                {
                    "method": "session/update",
                    "params": {"sessionId": "session-a", "update": {"sessionUpdate": {"updateType": "agent_message_chunk", "content": {"type": "text", "text": "A1"}}}},
                }
            )
        )
        await connection.server_to_client.put(
            _jsonl(
                {
                    "method": "session/update",
                    "params": {"sessionId": "session-b", "update": {"sessionUpdate": {"updateType": "agent_message_chunk", "content": {"type": "text", "text": "B1"}}}},
                }
            )
        )
        await connection.server_to_client.put(
            _jsonl(
                {
                    "method": "session/update",
                    "params": {"sessionId": "session-a", "update": {"sessionUpdate": {"updateType": "agent_message_chunk", "content": {"type": "text", "text": "A2"}}}},
                }
            )
        )

        first_a = await asyncio.wait_for(sub_a.next(), timeout=2)
        first_b = await asyncio.wait_for(sub_b.next(), timeout=2)
        second_a = await asyncio.wait_for(sub_a.next(), timeout=2)
        text = lambda notification: notification["params"]["update"]["sessionUpdate"]["updateType"]
        assert text(first_a) == "agent_message_chunk"
        assert first_a["params"]["sessionId"] == "session-a"
        assert first_b["params"]["sessionId"] == "session-b"
        assert second_a["params"]["sessionId"] == "session-a"
    finally:
        sub_a.close()
        sub_b.close()
        await transport.close()


def _jsonl(message: dict) -> bytes:
    import json

    return (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
