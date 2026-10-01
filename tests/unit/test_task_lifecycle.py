from collections.abc import AsyncIterator

import pytest

from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    EngineEvent,
    EngineEventType,
    ProjectRef,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import (
    FixedDialogueModel,
    RecordingCodingEngine,
    direct_input,
    make_context,
    unexpected_approval,
)

PROJECT = ProjectRef(project_id="p", name="p", root_path="C:\\work")


class RecoveringCodingEngine(RecordingCodingEngine):
    """工具步骤失败后仍由引擎正常结束 turn。"""

    async def run_turn(
        self, session_ref, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        async for event in super().run_turn(session_ref, request):
            if event.type == EngineEventType.TURN_FAILED:
                yield event.model_copy(update={"type": EngineEventType.TURN_COMPLETED})
            else:
                yield event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("engine_type", "status"),
    [(RecordingCodingEngine, "failed"), (RecoveringCodingEngine, "completed")],
    ids=["turn-failed", "turn-completed"],
)
async def test_turn_terminal_event_decides_receipt_and_keeps_tool_error(
    engine_type: type[RecordingCodingEngine], status: str
) -> None:
    """回执状态由 turn 终态决定，工具步骤的失败原因保留在 errors。"""
    orchestrator = ConversationOrchestrator(
        dialogue_model=FixedDialogueModel(
            CharacterTurn(
                speech="交给古代机械。",
                delegation=TaskRequestDraft(instructions="执行演示"),
            ),
            CharacterTurn(speech="收到结果。"),
        ),
        coding_engine=engine_type(fail_tool=True),
        approval_callback=unexpected_approval,
    )

    outcome = await orchestrator.handle_character_input(
        conversation_id="c",
        text="请执行",
        context=make_context(
            PROJECT, conversation_id="c", approval_mode=ApprovalMode.FULL_AUTO
        ),
    )

    assert outcome.receipt is not None
    assert outcome.receipt.status == status
    assert outcome.receipt.errors == ("模拟工具失败",)
    # 角色结果轮拿到同一状态
    assert outcome.messages[-1].payload["execution_status"] == status


@pytest.mark.asyncio
async def test_direct_input_becomes_same_formal_task() -> None:
    dialogue = FixedDialogueModel(CharacterTurn(speech="完成了。"))
    engine = RecordingCodingEngine()
    orchestrator = ConversationOrchestrator(
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_callback=unexpected_approval,
    )

    outcome = await direct_input(
        orchestrator,
        conversation_id="c",
        text="运行测试",
        context=make_context(
            PROJECT, conversation_id="c", approval_mode=ApprovalMode.FULL_AUTO
        ),
    )

    assert outcome.task == engine.requests[0]
    assert outcome.task.origin_message_id == outcome.messages[0].message_id
