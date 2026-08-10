from pathlib import Path

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.core.contracts import ProjectRef
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.storage.sqlite_store import SQLiteStore


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

