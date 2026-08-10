from pathlib import Path

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    MessageSource,
    ProjectRef,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.storage.sqlite_store import SQLiteStore
from tests.fakes import FixedDialogueModel


@pytest.mark.asyncio
async def test_completed_demo_conversation_restores_after_reopen(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    store = SQLiteStore(database)
    store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
    store.create_conversation(
        project_id="p",
        pair_id="phainon_ancient_machine",
        title="Demo",
        conversation_id="c",
    )
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="Repo", root_path=str(tmp_path)),
        dialogue_model=ScriptedDialogueModel(),
        coding_engine=ScriptedCodingEngine(),
        store=store,
        approval_mode=ApprovalMode.FULL_AUTO,
    )
    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="请让古代机械创建 hello.txt"
    )
    store.close()

    reopened = SQLiteStore(database)
    snapshot = reopened.load_conversation("c")
    assert snapshot["messages"] == outcome.messages
    assert snapshot["tool_runs"] == outcome.tool_runs
    assert snapshot["engine_session"].engine_type == "scripted"
    reopened.close()


@pytest.mark.asyncio
async def test_restored_orchestrator_backfills_history_and_session_ref(
    tmp_path: Path,
) -> None:
    """O2.2：restore_conversation 回填消息历史与 EngineSessionRef。

    恢复后再发消息：角色模型收到的近期上下文包含历史消息；
    再次委派执行时 open_session 收到已保存的 stored_ref（可 thread/resume）。
    """
    database = tmp_path / "data" / "pair_harness.db"
    store = SQLiteStore(database)
    store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
    store.create_conversation(
        project_id="p",
        pair_id="phainon_ancient_machine",
        title="Demo",
        conversation_id="c",
    )
    first = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="Repo", root_path=str(tmp_path)),
        dialogue_model=ScriptedDialogueModel(),
        coding_engine=ScriptedCodingEngine(),
        store=store,
        approval_mode=ApprovalMode.FULL_AUTO,
    )
    await first.handle_character_input(conversation_id="c", text="请让古代机械创建 hello.txt")
    store.close()

    # 重建 orchestrator 并恢复旧聊天
    reopened = SQLiteStore(database)
    snapshot = reopened.load_conversation("c")
    assert snapshot["engine_session"] is not None
    engine = ScriptedCodingEngine()
    model = FixedDialogueModel(
        CharacterTurn(speech="我在，慢慢说。", delegation=None),
        CharacterTurn(
            speech="古代机械，继续。",
            delegation=TaskRequestDraft(instructions="再跑一次"),
        ),
        CharacterTurn(speech="完成了。", delegation=None),
    )
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="Repo", root_path=str(tmp_path)),
        dialogue_model=model,
        coding_engine=engine,
        store=reopened,
        approval_mode=ApprovalMode.FULL_AUTO,
    )
    orchestrator.restore_conversation(snapshot)

    # 纯聊天轮：近期上下文包含全部历史角色对话（USER/CHARACTER，排除
    # 助手与系统消息），角色不失忆
    await orchestrator.handle_character_input(conversation_id="c", text="还记得刚才的事吗")
    request = model.requests[0]
    historical = [
        m
        for m in snapshot["messages"]
        if m.source in (MessageSource.USER, MessageSource.CHARACTER)
    ]
    assert [m.message_id for m in request.recent_messages] == [
        m.message_id for m in historical
    ]

    # 委派轮：open_session 收到已保存的 stored_ref
    outcome = await orchestrator.handle_character_input(
        conversation_id="c", text="再跑一次"
    )
    assert outcome.receipt is not None
    assert outcome.receipt.status == "completed"
    _, stored_ref = engine.opened_sessions[-1]
    assert stored_ref is not None
    assert stored_ref == snapshot["engine_session"]
    reopened.close()

