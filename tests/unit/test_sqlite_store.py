import json
from pathlib import Path

from pair_harness.core.contracts import (
    EngineSessionRef,
    Message,
    MessageKind,
    MessageSource,
    ToolRun,
)
from pair_harness.storage.sqlite_store import SQLiteStore


def test_store_persists_core_records(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "data" / "pair_harness.db")
    project = store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
    conversation = store.create_conversation(
        project_id=project.project_id,
        pair_id="phainon_ancient_machine",
        title="First",
        conversation_id="c",
    )
    message = Message(
        conversation_id=conversation.conversation_id,
        pair_id=conversation.pair_id,
        source=MessageSource.ASSISTANT,
        kind=MessageKind.ASSISTANT_NATURAL_LANGUAGE,
        text="完成",
        tts_eligible=True,
    )
    tool_run = ToolRun(
        tool_call_id="tool",
        conversation_id="c",
        task_id="task",
        engine_turn_id="turn",
        sequence=2,
        status="succeeded",
        title="pytest",
        summary="2 passed",
    )
    session = EngineSessionRef(engine_type="scripted", opaque_ref="private")
    store.save_message(message)
    store.save_tool_run(tool_run)
    store.save_engine_session("c", session)

    snapshot = store.load_conversation("c")
    assert snapshot["messages"] == (message,)
    assert snapshot["tool_runs"] == (tool_run,)
    assert snapshot["engine_session"] == session
    store.close()


def test_legacy_tool_run_status_completed_reads_back_as_succeeded(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="c"
        )
        # A1 对齐协议前，工具状态使用过 "completed"，旧聊天重开必须可恢复
        legacy = {
            "tool_call_id": "tool-1",
            "conversation_id": "c",
            "task_id": "t",
            "engine_turn_id": "turn",
            "sequence": 1,
            "status": "completed",
            "title": "旧工具",
            "summary": "旧记录",
        }
        store.connection.execute(
            """INSERT INTO tool_runs(
                conversation_id, tool_call_id, task_id, engine_turn_id,
                sequence, status, tool_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("c", "tool-1", "t", "turn", 1, "completed", json.dumps(legacy)),
        )
        store.connection.commit()

        snapshot = store.load_conversation("c")
        assert snapshot["tool_runs"][0].status == "succeeded"
        assert snapshot["tool_runs"][0].title == "旧工具"


def test_approval_mode_is_persisted_per_project(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    with SQLiteStore(database) as store:
        project = store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        # 计划 A6：默认“请求批准”
        assert project.approval_mode == "request_approval"
        store.update_project_approval_mode("p", "full_auto")
        assert store.get_project("p").approval_mode == "full_auto"

    # 重建 store（模拟关闭重开），审批模式必须恢复
    with SQLiteStore(database) as reopened:
        assert reopened.get_project("p").approval_mode == "full_auto"


def test_new_conversation_does_not_inherit_history_or_session(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="old"
        )
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="new"
        )
        store.save_engine_session(
            "old", EngineSessionRef(engine_type="scripted", opaque_ref="old-session")
        )

        snapshot = store.load_conversation("new")
        assert snapshot["messages"] == ()
        assert snapshot["tool_runs"] == ()
        assert snapshot["engine_session"] is None


def test_missing_project_path_keeps_history_readable(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Gone", root_path=str(missing), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="c"
        )
        assert not store.get_project("p").path_available
        assert store.load_conversation("c")["conversation"].conversation_id == "c"


def test_message_source_kind_columns_store_enum_values(tmp_path: Path) -> None:
    """O1.2：source/kind 列存枚举值（user / character.speech），不存枚举名。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="c"
        )
        message = Message(
            conversation_id="c",
            pair_id="phainon_ancient_machine",
            source=MessageSource.CHARACTER,
            kind=MessageKind.CHARACTER_SPEECH,
            text="我在。",
            tts_eligible=True,
        )
        store.save_message(message)
        row = store.connection.execute(
            "SELECT source, kind FROM messages WHERE message_id = ?",
            (message.message_id,),
        ).fetchone()
        assert row["source"] == "character"
        assert row["kind"] == "character.speech"
        assert row["source"] != "MessageSource.CHARACTER"

