"""O2.1：orchestrator 流式事件通道测试。

验证消息与引擎事件在产生时即通过回调推送，顺序满足设计 §3.2：
角色接受委派的台词先于执行事件到达界面。
"""

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.approval import ApprovalManager
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    MessageKind,
    ProjectRef,
    TaskRequestDraft,
    enum_value,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel


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


def _make_orchestrator(engine, mode: ApprovalMode = ApprovalMode.FULL_AUTO):
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=FixedDialogueModel(
            CharacterTurn(
                speech="古代机械，交给你了。",
                delegation=TaskRequestDraft(instructions="跑一下测试"),
            ),
            CharacterTurn(speech="做完了，我们继续。", delegation=None),
        ),
        coding_engine=engine,
        store=None,
        approval_mode=mode,
    )


@pytest.mark.asyncio
async def test_stream_order_delegation_then_tools_then_summary_then_reply() -> None:
    """O2.1：流式顺序——委派台词 → 工具事件 → 助手总结 → 角色结果回应。"""
    engine = ScriptedCodingEngine()
    orchestrator = _make_orchestrator(engine)
    stream = _wire_stream(orchestrator)

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="跑一下测试"
    )

    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    # 委派台词（角色第一条消息）先于任何引擎事件
    first_character = stream.index(f"message:{enum_value(MessageKind.CHARACTER_SPEECH)}")
    first_tool_started = stream.index("event:tool.started")
    assert first_character < first_tool_started
    # 工具生命周期顺序
    assert stream.index("event:tool.started") < stream.index("event:tool.finished")
    # 助手总结（自然语言消息）在 assistant.final 之后
    assistant_msg = stream.index(f"message:{enum_value(MessageKind.ASSISTANT_NATURAL_LANGUAGE)}")
    assert stream.index("event:assistant.final") < assistant_msg
    # 角色结果回应是最后一条消息，位于助手总结之后
    character_msgs = [
        i for i, item in enumerate(stream) if item == f"message:{enum_value(MessageKind.CHARACTER_SPEECH)}"
    ]
    assert len(character_msgs) == 2
    assert character_msgs[1] > assistant_msg
    assert character_msgs[1] == len(stream) - 1


@pytest.mark.asyncio
async def test_stream_order_tool_started_before_approval_events() -> None:
    """O2.1：请求批准模式下 tool.started 先于 approval.requested 到达界面。"""
    engine = ScriptedCodingEngine(tool_payload={"tool_kind": "shell", "command": "ls"})
    orchestrator = _make_orchestrator(engine, mode=ApprovalMode.REQUEST_APPROVAL)

    async def allow(op, approval_id: str, reason: str) -> ApprovalDecision:
        return ApprovalDecision.ALLOW

    orchestrator.approval_callback = allow
    stream = _wire_stream(orchestrator)

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="跑一下测试"
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
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
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
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="跑一下测试"
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
