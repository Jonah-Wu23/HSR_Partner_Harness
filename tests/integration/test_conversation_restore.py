from pathlib import Path

import pytest

from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.core.contracts import (
    ApprovalMode,
    CharacterTurn,
    EngineSessionRef,
    MessageOrigin,
    MessageSource,
    ProjectRef,
    TaskRequestDraft,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.desktop_backend.application_service import build_demo_service
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.storage.sqlite_store import SQLiteStore
from tests.fakes import FixedDialogueModel


def _desktop_command(request_id: str, method: str, **params) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


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
    # 助手、系统消息与委派镜像卡），角色不失忆
    await orchestrator.handle_character_input(conversation_id="c", text="还记得刚才的事吗")
    request = model.requests[0]
    historical = [
        m
        for m in snapshot["messages"]
        if m.source in (MessageSource.USER, MessageSource.CHARACTER)
        and m.origin != MessageOrigin.CHARACTER_DELEGATION
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


def test_restore_drops_session_from_a_different_engine(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "data.db")
    store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
    store.create_conversation(
        project_id="p",
        pair_id="phainon_ancient_machine",
        title="Demo",
        conversation_id="c",
    )
    store.save_engine_session(
        "c",
        EngineSessionRef(engine_type="codex-app-server", opaque_ref="private"),
    )
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="p", name="Repo", root_path=str(tmp_path)),
        dialogue_model=ScriptedDialogueModel(),
        coding_engine=ScriptedCodingEngine(),
        store=store,
        approval_mode=ApprovalMode.FULL_AUTO,
    )

    orchestrator.restore_conversation(store.load_conversation("c"))

    assert "c" not in orchestrator._sessions
    store.close()


@pytest.mark.asyncio
async def test_desktop_service_restores_each_conversation_pair_without_crossing(
    tmp_path: Path,
) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    service = build_demo_service(database=database, project_root=tmp_path)
    try:
        project_id = service.current_project_id
        firefly = await service.handle_command(
            _desktop_command(
                "create-firefly",
                "conversation.create",
                project_id=project_id,
                pair_id="firefly_sam",
            )
        )
        firefly_id = firefly["current_conversation_id"]
        march = await service.handle_command(
            _desktop_command(
                "create-march",
                "conversation.create",
                project_id=project_id,
                pair_id="march7_fourth_mirror",
            )
        )
        march_id = march["current_conversation_id"]
    finally:
        await service.shutdown()

    restored = build_demo_service(database=database, project_root=tmp_path)
    try:
        firefly_after_restart = await restored.handle_command(
            _desktop_command(
                "select-firefly",
                "conversation.select",
                conversation_id=firefly_id,
            )
        )
        assert firefly_after_restart["current_conversation"]["pair_id"] == "firefly_sam"
        assert firefly_after_restart["pair"]["character"]["name"] == "流萤"
        assert firefly_after_restart["pair"]["assistant"]["name"] == "萨姆"

        march_after_restart = await restored.handle_command(
            _desktop_command(
                "select-march",
                "conversation.select",
                conversation_id=march_id,
            )
        )
        assert march_after_restart["current_conversation"]["pair_id"] == "march7_fourth_mirror"
        assert march_after_restart["pair"]["character"]["name"] == "三月七"
        assert march_after_restart["pair"]["assistant"]["name"] == "第四面镜"
    finally:
        await restored.shutdown()

