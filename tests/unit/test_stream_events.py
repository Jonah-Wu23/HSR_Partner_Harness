from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    DialogueEvent,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    MessageKind,
    MessageSource,
    ProjectRef,
    TaskRequest,
    TaskRequestDraft,
    enum_value,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import (
    FixedDialogueModel,
    allow_approval,
    direct_input,
    make_context,
    unexpected_approval,
)

PROJECT = ProjectRef(project_id="p", name="p", root_path="C:\\project")


def _context(mode: ApprovalMode = ApprovalMode.FULL_AUTO):
    return make_context(PROJECT, conversation_id="c", approval_mode=mode)


def _wire_stream(orchestrator: ConversationOrchestrator) -> list[str]:
    """挂接流式回调，返回统一时间序的记录列表。"""
    stream: list[str] = []

    def on_message(message) -> None:
        stream.append(f"message:{enum_value(message.kind)}")

    def on_event(event) -> None:
        stream.append(f"event:{event.type}")

    orchestrator.on_message = on_message
    orchestrator.on_engine_event = on_event
    return stream


def _make_orchestrator(engine):
    return ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(
            CharacterTurn(
                speech="古代机械，交给你了。",
                delegation=TaskRequestDraft(instructions="跑一下测试"),
            ),
            CharacterTurn(speech="做完了，我们继续。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_callback=unexpected_approval,
    )


@pytest.mark.asyncio
async def test_stream_order_delegation_then_tools_then_summary_then_reply() -> None:
    """流式推送顺序：委派台词、工具事件、助手总结、角色结果回应。"""
    engine = ScriptedCodingEngine()
    orchestrator = _make_orchestrator(engine)
    stream = _wire_stream(orchestrator)

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="跑一下测试", context=_context()
    )

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    # 委派台词（角色第一条消息）先于任何引擎事件
    first_character = stream.index(f"message:{enum_value(MessageKind.CHARACTER_SPEECH)}")
    first_tool_started = stream.index("event:tool.started")
    assert first_character < first_tool_started
    # 工具生命周期顺序
    assert stream.index("event:tool.started") < stream.index("event:tool.finished")
    # 助手输出按工具边界拆段：工具前的说明段在 tool.started 之前定稿，
    # 工具后的最终正文段在 assistant.final 之后定稿
    assistant_msgs = [
        i
        for i, item in enumerate(stream)
        if item == f"message:{enum_value(MessageKind.ASSISTANT_NATURAL_LANGUAGE)}"
    ]
    assert len(assistant_msgs) == 2
    assert assistant_msgs[0] < stream.index("event:tool.started")
    assert stream.index("event:assistant.final") < assistant_msgs[1]
    # 角色结果回应是最后一条消息，位于助手总结之后
    character_msgs = [
        i for i, item in enumerate(stream) if item == f"message:{enum_value(MessageKind.CHARACTER_SPEECH)}"
    ]
    assert len(character_msgs) == 2
    assert character_msgs[1] > assistant_msgs[1]
    assert character_msgs[1] == len(stream) - 1


@pytest.mark.asyncio
async def test_stream_order_tool_started_before_approval_events() -> None:
    engine = ScriptedCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    orchestrator = _make_orchestrator(engine)
    orchestrator.approval_callback = allow_approval
    stream = _wire_stream(orchestrator)

    outcome = await orchestrator.handle_character_input(
        conversation_id="c",
        text="跑一下测试",
        context=_context(ApprovalMode.REQUEST_APPROVAL),
    )

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    assert stream.index("event:tool.started") < stream.index("event:approval.requested")
    assert stream.index("event:approval.requested") < stream.index("event:approval.resolved")
    assert stream.index("event:approval.resolved") < stream.index("event:tool.finished")


@pytest.mark.asyncio
async def test_returned_reasoning_is_attached_to_final_messages() -> None:
    engine = ScriptedCodingEngine(reasoning="先检查再执行。")
    orchestrator = ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(
            CharacterTurn(
                speech="古代机械，交给你了。",
                delegation=TaskRequestDraft(instructions="跑一下测试"),
                reasoning="需要交给搭档。",
            ),
            CharacterTurn(
                speech="做完了，我们继续。",
                reasoning="回执状态是 completed。",
            ),
        ),
        coding_engine=engine,
        store=None,
        approval_callback=unexpected_approval,
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="跑一下测试", context=_context()
    )

    character_messages = [
        message for message in outcome.messages if message.kind == MessageKind.CHARACTER_SPEECH
    ]
    assistant_messages = [
        message
        for message in outcome.messages
        if message.kind == MessageKind.ASSISTANT_NATURAL_LANGUAGE
    ]
    assert character_messages[0].payload["reasoning"] == "需要交给搭档。"
    assert character_messages[-1].payload["reasoning"] == "回执状态是 completed。"
    assert assistant_messages[0].payload["reasoning"] == "先检查再执行。"


@pytest.mark.asyncio
async def test_dialogue_delta_events_forwarded_to_ui_bridge() -> None:
    """角色对话增量与 final 事件按产生顺序经 on_dialogue_event 转发。"""
    engine = ScriptedCodingEngine()
    orchestrator = _make_orchestrator(engine)
    forwarded: list[tuple[str, str, object]] = []

    def on_dialogue_event(conversation_id, user_message, event, timeline_order) -> None:
        forwarded.append((conversation_id, user_message.message_id, event))

    orchestrator.on_dialogue_event = on_dialogue_event

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="请古代机械跑一下测试", context=_context()
    )
    assert outcome.messages
    assert forwarded, "on_dialogue_event 必须收到角色对话增量"
    assert [item[0] for item in forwarded] == ["c", "c"]
    assert forwarded[0][1] == outcome.messages[0].message_id
    # 事件按产生顺序：speech.delta（带流式文本）→ character.final
    assert [item[2].type for item in forwarded] == ["speech.delta", "character.final"]
    assert forwarded[0][2].delta == "古代机械，交给你了。"
    assert forwarded[1][2].turn.speech == "古代机械，交给你了。"


@pytest.mark.parametrize("event_type", ["speech.delta", "reasoning.delta", "character.final"])
def test_dialogue_event_requires_payload_of_its_type(event_type: str) -> None:
    with pytest.raises(ValidationError):
        DialogueEvent(type=event_type)


class _ReplayEngine(ScriptedCodingEngine):
    """按给定脚本回放引擎事件。"""

    def __init__(self, events: list[EngineEvent]) -> None:
        super().__init__()
        self._script = events

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self.requests.append(request)
        for event in self._script:
            yield event.model_copy(
                update={"conversation_id": request.conversation_id, "task_id": request.task_id}
            )


def _engine_event(
    event_type: EngineEventType,
    payload: dict | None = None,
    tool_call_id: str | None = None,
) -> EngineEvent:
    return EngineEvent(
        conversation_id="c",
        task_id="replay",
        engine_turn_id="replay-turn",
        sequence=0,
        type=event_type,
        tool_call_id=tool_call_id,
        payload=payload or {},
    )


@pytest.mark.asyncio
async def test_interleaved_output_forms_ordered_assistant_segments() -> None:
    """思考、正文与工具交错时按工具边界分段，分段与工具卡共享单调时间线序号。"""
    engine = _ReplayEngine(
        [
            _engine_event(EngineEventType.TURN_STARTED),
            _engine_event(EngineEventType.ASSISTANT_REASONING_DELTA, {"text": "先看目录结构。"}),
            _engine_event(EngineEventType.ASSISTANT_DELTA, {"text": "我先查看 src 目录。"}),
            _engine_event(
                EngineEventType.TOOL_STARTED,
                {"title": "list", "command": "Get-ChildItem src"},
                "tool-1",
            ),
            _engine_event(
                EngineEventType.TOOL_FINISHED,
                {"status": "succeeded", "title": "list", "summary": "列出 12 个文件"},
                "tool-1",
            ),
            _engine_event(EngineEventType.ASSISTANT_REASONING_DELTA, {"text": "再看测试分层。"}),
            _engine_event(
                EngineEventType.TOOL_STARTED,
                {"title": "list", "command": "Get-ChildItem tests"},
                "tool-2",
            ),
            _engine_event(
                EngineEventType.TOOL_FINISHED,
                {"status": "succeeded", "title": "list", "summary": "列出 3 个目录"},
                "tool-2",
            ),
            _engine_event(EngineEventType.ASSISTANT_DELTA, {"text": "src 分为 core 和 adapters。"}),
            _engine_event(
                EngineEventType.ASSISTANT_FINAL,
                {"text": "src 分为 core 和 adapters，tests 分三层。"},
            ),
            _engine_event(EngineEventType.TURN_COMPLETED, {"status": "completed"}),
        ]
    )
    orchestrator = ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(CharacterTurn(speech="结果收到。")),
        coding_engine=engine,
        approval_callback=unexpected_approval,
    )
    deltas: list[dict] = []

    def on_engine_event(event: EngineEvent) -> None:
        if event.type in (
            EngineEventType.ASSISTANT_DELTA,
            EngineEventType.ASSISTANT_REASONING_DELTA,
        ):
            deltas.append(dict(event.payload))

    orchestrator.on_engine_event = on_engine_event

    outcome = await direct_input(
        orchestrator, conversation_id="c", text="检查 src 和 tests 目录", context=_context()
    )

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    task_id = outcome.task.task_id
    segments = [
        m
        for m in outcome.messages
        if m.source == MessageSource.ASSISTANT
        and m.kind == MessageKind.ASSISTANT_NATURAL_LANGUAGE
    ]
    assert [m.message_id for m in segments] == [
        f"assistant:c:{task_id}:{index}" for index in range(3)
    ]
    # 工具前的阶段性说明、工具之间只有思考的段、final 覆盖流式累积的最终正文
    assert [m.text for m in segments] == [
        "我先查看 src 目录。",
        "",
        "src 分为 core 和 adapters，tests 分三层。",
    ]
    orders = [m.timeline_order for m in segments]
    tool_orders = [run.timeline_order for run in outcome.tool_runs]
    assert orders[0] < tool_orders[0] < orders[1] < tool_orders[1] < orders[2]
    # 流式 delta 携带所属分段的消息 id 与时间线序号，界面据此与落库消息对账
    assert [(delta["message_id"], delta["timeline_order"]) for delta in deltas] == [
        (segments[0].message_id, orders[0]),
        (segments[0].message_id, orders[0]),
        (segments[1].message_id, orders[1]),
        (segments[2].message_id, orders[2]),
    ]
