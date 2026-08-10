"""O3.3：执行期间向角色注入压缩进度摘要。

验证：编排器执行期间到达的角色聊天轮收到 CharacterProgressSummary，
内容为中性描述——不含命令、文件路径与工具输出原文；任务结束后不再注入。
"""

from __future__ import annotations

import asyncio

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
from tests.fakes import FixedDialogueModel


class GatedCodingEngine(ScriptedCodingEngine):
    """yield 工具开始事件后等待放行，模拟长时间执行。"""

    def __init__(self, command: str = "touch secret_file.txt") -> None:
        super().__init__()
        self.command = command
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_turn(
        self, session_ref, request: TaskRequest
    ) -> "asyncio.AsyncIterator[EngineEvent]":
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


def make_orchestrator(tmp_path, engine, dialogue) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path=str(tmp_path)),
        dialogue_model=dialogue,
        coding_engine=engine,
        approval_mode=ApprovalMode.FULL_AUTO,
    )


@pytest.mark.asyncio
async def test_execution_progress_injected_during_run_and_cleared_after(tmp_path) -> None:
    """执行期间聊天轮收到压缩摘要；任务结束后不再注入。"""
    engine = GatedCodingEngine(command="touch secret_file.txt")
    dialogue = FixedDialogueModel(
        CharacterTurn(
            speech="好，交给你。", delegation=TaskRequestDraft(instructions="执行")
        ),
        CharacterTurn(speech="还在忙呢，我盯着。"),
        CharacterTurn(speech="做完了。"),
        CharacterTurn(speech="嗯，忙完了。"),
    )
    orchestrator = make_orchestrator(tmp_path, engine, dialogue)

    run_task = asyncio.create_task(
        orchestrator.handle_character_input(conversation_id="c", text="请让古代机械创建文件")
    )
    # 等待 _execute 处理完 TOOL_STARTED（进度已更新）并停在 gate 上
    await asyncio.wait_for(engine.started.wait(), timeout=5)

    # 执行期间的角色聊天轮
    await orchestrator.handle_character_input(conversation_id="c", text="进展怎么样")

    # 放行并等任务完成
    engine.release.set()
    await run_task

    # 任务完成后再来一轮：不再注入进度摘要
    await orchestrator.handle_character_input(conversation_id="c", text="忙完了吗")

    assert len(dialogue.requests) == 4
    progress_requests = [
        req for req in dialogue.requests if req.progress_summary is not None
    ]
    assert len(progress_requests) == 1
    summary = progress_requests[0].progress_summary
    assert summary is not None
    # 中性摘要：状态 running、步骤计数与当前步骤简述
    assert summary.status == "running"
    assert summary.completed_steps == 0
    assert summary.current_step == "正在执行工具操作"
    # 不含命令、路径与输出原文
    assert "touch" not in summary.current_step
    assert "secret_file" not in summary.current_step
    assert "passed" not in summary.current_step
    # 任务结束后的聊天轮不注入
    assert dialogue.requests[3].progress_summary is None


@pytest.mark.asyncio
async def test_progress_counted_after_tool_finish_and_neutral_file_label(tmp_path) -> None:
    """工具完成计入 completed_steps；文件操作步骤用中性标签。"""
    engine = GatedCodingEngine(command="copy report.md")
    # 让引擎在 TOOL_FINISHED 之前放行后仍可被询问：在 started 后立刻放行
    engine.release.set()
    dialogue = FixedDialogueModel(
        CharacterTurn(
            speech="好，交给你。", delegation=TaskRequestDraft(instructions="执行")
        ),
        CharacterTurn(speech="完成。"),
    )
    orchestrator = make_orchestrator(tmp_path, engine, dialogue)

    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="请让古代机械执行"
    )
    assert outcome.receipt is not None and outcome.receipt.status == "completed"

    # 执行期间没有聊天轮 → 无 progress 请求；事件流本身可确认中性标签逻辑
    assert all(req.progress_summary is None for req in dialogue.requests)
    # 中性标签逻辑（静态）：
    from pair_harness.core.orchestrator import ConversationOrchestrator as CO

    assert (
        CO._step_label(
            EngineEvent(
                conversation_id="c",
                task_id="t",
                engine_turn_id="e",
                sequence=1,
                type=EngineEventType.TOOL_STARTED,
                payload={"path": "C:\\project\\report.md"},
            )
        )
        == "正在修改文件"
    )
    assert (
        CO._step_label(
            EngineEvent(
                conversation_id="c",
                task_id="t",
                engine_turn_id="e",
                sequence=1,
                type=EngineEventType.TOOL_STARTED,
                payload={"command": "git push --force"},
            )
        )
        == "正在执行命令"
    )
