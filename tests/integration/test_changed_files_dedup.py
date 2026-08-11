"""O4.3：changed_files 去重 —— 同一文件多次 patch 只记一次。

回执的 changed_files 与角色结果摘要的 user_visible_changes 都应保持
首次出现顺序并去重；不同文件不受影响。
"""

from collections.abc import AsyncIterator

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    ProjectRef,
    TaskRequest,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from tests.fakes import FixedDialogueModel


class _DupPatchEngine(ScriptedCodingEngine):
    """同一个文件 patch 三次，另一个文件 patch 一次。"""

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        self.requests.append(request)
        common = {
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "engine_turn_id": "turn-dup-1",
        }
        yield EngineEvent(sequence=0, type=EngineEventType.TURN_STARTED, **common)
        for sequence in (1, 2, 3):
            yield EngineEvent(
                sequence=sequence,
                type=EngineEventType.FILE_PATCH,
                payload={"path": "src/app.py", "patch": "改第 N 次"},
                **common,
            )
        yield EngineEvent(
            sequence=4,
            type=EngineEventType.FILE_PATCH,
            payload={"path": "src/main.py", "patch": "新文件"},
            **common,
        )
        yield EngineEvent(
            sequence=5,
            type=EngineEventType.ASSISTANT_FINAL,
            payload={"text": "改好了。"},
            **common,
        )
        yield EngineEvent(
            sequence=6,
            type=EngineEventType.TURN_COMPLETED,
            payload={"summary": "完成"},
            **common,
        )


@pytest.mark.asyncio
async def test_changed_files_deduped_in_receipt_and_result_summary() -> None:
    dialogue = FixedDialogueModel(CharacterTurn(speech="改好了。"))
    engine = _DupPatchEngine()
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="p", root_path="C:\\project"),
        dialogue_model=dialogue,
        coding_engine=engine,
        store=None,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    outcome = await orchestrator.handle_direct_input(
        conversation_id="c", text="改文件"
    )

    # 回执：同文件多次 patch 只记一次，顺序为首次出现顺序
    assert outcome.receipt is not None
    assert outcome.receipt.changed_files == ("src/app.py", "src/main.py")

    # 角色结果摘要：可见变更与回执一致（不含重复）
    summary_request = dialogue.requests[-1]
    assert summary_request.result_summary is not None
    assert summary_request.result_summary.user_visible_changes == ("app.py", "main.py")
