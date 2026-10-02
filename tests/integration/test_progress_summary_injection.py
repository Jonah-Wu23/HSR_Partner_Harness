from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
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
from tests.fakes import FixedDialogueModel, make_context, unexpected_approval


class GatedCodingEngine(ScriptedCodingEngine):
    """发出工具开始事件后等待放行，模拟长时间执行。"""

    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_turn(
        self, session_ref, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        del session_ref
        self.requests.append(request)
        engine_turn_id = "demo-turn-progress"
        tool_call_id = "demo-tool-progress"
        common = {
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "engine_turn_id": engine_turn_id,
        }
        yield EngineEvent(sequence=0, type=EngineEventType.TURN_STARTED, **common)
        # 命令原文只存在于引擎事件 payload，不得进入角色进度摘要
        yield EngineEvent(
            sequence=1,
            type=EngineEventType.TOOL_STARTED,
            tool_call_id=tool_call_id,
            payload={"title": self.command, "details": self.command},
            **common,
        )
        self.started.set()
        await self.release.wait()
        yield EngineEvent(
            sequence=2,
            type=EngineEventType.TOOL_FINISHED,
            tool_call_id=tool_call_id,
            payload={
                "status": "succeeded",
                "title": self.command,
                "summary": "2 passed",
                "details": "2 passed",
            },
            **common,
        )
        yield EngineEvent(
            sequence=3,
            type=EngineEventType.ASSISTANT_FINAL,
            payload={"text": "完成"},
            **common,
        )
        yield EngineEvent(sequence=4, type=EngineEventType.TURN_COMPLETED, **common)


def make_orchestrator(engine, dialogue) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_callback=unexpected_approval,
    )


def make_ctx(tmp_path):
    return make_context(
        ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        conversation_id="c",
        approval_mode=ApprovalMode.FULL_AUTO,
    )


@pytest.mark.asyncio
async def test_execution_progress_injected_during_run_and_cleared_after(tmp_path) -> None:
    """执行期间的聊天轮收到压缩进度摘要，任务结束后不再注入。"""
    engine = GatedCodingEngine(command="touch secret_file.txt")
    dialogue = FixedDialogueModel(
        CharacterTurn(
            speech="好，交给你。", delegation=TaskRequestDraft(instructions="执行")
        ),
        CharacterTurn(speech="还在忙呢，我盯着。"),
        CharacterTurn(speech="做完了。"),
        CharacterTurn(speech="嗯，忙完了。"),
    )
    orchestrator = make_orchestrator(engine, dialogue)
    context = make_ctx(tmp_path)

    run_task = asyncio.create_task(
        orchestrator.handle_character_input(
            conversation_id="c", text="请让古代机械创建文件", context=context
        )
    )
    # 编排器已处理 tool.started（进度已更新），引擎停在放行点
    await asyncio.wait_for(engine.started.wait(), timeout=5)

    # 执行期间的角色聊天轮
    await orchestrator.handle_character_input(
        conversation_id="c", text="进展怎么样", context=context
    )

    # 放行并等任务完成
    engine.release.set()
    await run_task

    # 任务完成后再来一轮：不再注入进度摘要
    await orchestrator.handle_character_input(
        conversation_id="c", text="忙完了吗", context=context
    )

    assert len(dialogue.requests) == 4
    progress_requests = [
        req for req in dialogue.requests if req.progress_summary is not None
    ]
    assert len(progress_requests) == 1
    summary = progress_requests[0].progress_summary
    # 当前步骤是中性标签，不带命令、路径与输出原文
    assert summary.status == "running"
    assert summary.completed_steps == 0
    assert summary.current_step == "正在执行工具操作"
    # 任务结束后的聊天轮不注入
    assert dialogue.requests[3].progress_summary is None
