import json
import sqlite3
from pathlib import Path

from pair_harness.core.contracts import (
    EngineSessionRef,
    Message,
    MessageKind,
    MessageSource,
    ToolRun,
)
from pair_harness.storage.sqlite_store import SCHEMA_VERSION, SQLiteStore


def _old_schema_connection(database: Path) -> sqlite3.Connection:
    """构造 O4.3 迁移前的旧库（user_version=0 的 v0 结构）。

    与历史 schema.sql 一致：projects 无 approval_mode 列；
    engine_sessions 带 last_turn_id / resume_status 死列。
    """
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            root_path TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_opened_at TEXT NOT NULL
        );
        CREATE TABLE conversations (
            conversation_id TEXT PRIMARY KEY,
            project_id TEXT REFERENCES projects(project_id),
            pair_id TEXT NOT NULL,
            title TEXT NOT NULL,
            last_mode TEXT NOT NULL DEFAULT 'chat',
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            message_json TEXT NOT NULL
        );
        CREATE TABLE tool_runs (
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            tool_call_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            engine_turn_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            status TEXT NOT NULL,
            tool_json TEXT NOT NULL,
            PRIMARY KEY (conversation_id, tool_call_id)
        );
        CREATE TABLE engine_sessions (
            conversation_id TEXT PRIMARY KEY REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            engine_type TEXT NOT NULL,
            session_ref TEXT NOT NULL,
            last_turn_id TEXT,
            resume_status TEXT NOT NULL DEFAULT 'ready',
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.commit()
    return connection


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


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
        payload={"reasoning": "先核对结果。"},
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


def test_legacy_message_turn_id_reads_back_as_engine_turn_id(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        store.create_conversation(
            project_id="p", pair_id="phainon_ancient_machine", conversation_id="c"
        )
        # O4.4 前 Message 字段名是 turn_id（extra="forbid" 下直接校验失败），
        # 旧聊天重开必须由 _parse_message 重映射后恢复
        legacy = {
            "message_id": "msg-1",
            "conversation_id": "c",
            "pair_id": "phainon_ancient_machine",
            "turn_id": "turn-3",
            "source": "assistant",
            "kind": "assistant.natural_language",
            "text": "旧消息",
        }
        store.connection.execute(
            "INSERT INTO messages(conversation_id, message_id, source, kind, created_at, message_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "c",
                "msg-1",
                "assistant",
                "assistant.natural_language",
                "2026-08-01T00:00:00+00:00",
                json.dumps(legacy),
            ),
        )
        store.connection.commit()

        snapshot = store.load_conversation("c")
        assert len(snapshot["messages"]) == 1
        message = snapshot["messages"][0]
        assert message.engine_turn_id == "turn-3"
        assert message.text == "旧消息"


def test_approval_mode_is_persisted_per_project(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    with SQLiteStore(database) as store:
        project = store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        # 计划 A6：默认“请求批准”
        assert project.approval_mode == "request_approval"
        store.update_project_approval_mode("p", "full_auto")
        assert store.get_project("p").approval_mode == "full_auto"
        # 重复注册项目只刷新路径与打开时间，不覆盖用户设置
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        assert store.get_project("p").approval_mode == "full_auto"

    # 重建 store（模拟关闭重开），审批模式必须恢复
    with SQLiteStore(database) as reopened:
        assert reopened.get_project("p").approval_mode == "full_auto"


def test_reasoning_effort_is_persisted_per_project(tmp_path: Path) -> None:
    database = tmp_path / "data" / "pair_harness.db"
    with SQLiteStore(database) as store:
        project = store.create_project(
            name="Repo", root_path=str(tmp_path), project_id="p"
        )
        assert project.reasoning_effort == "low"
        store.update_project_reasoning_effort("p", "high")
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p")
        assert store.get_project("p").reasoning_effort == "high"

    with SQLiteStore(database) as reopened:
        assert reopened.get_project("p").reasoning_effort == "high"


def test_project_can_be_reopened_by_normalized_root_path(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(
            name="Repo", root_path=str(project_root), project_id="stable-project"
        )

        reopened = store.find_project_by_root_path(str(project_root / "."))

        assert reopened is not None
        assert reopened.project_id == "stable-project"


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


def test_fresh_database_marks_schema_version(tmp_path: Path) -> None:
    """O4.3：新库由 schema.sql 一次建全，直接标记 SCHEMA_VERSION。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        version = store.connection.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        # 新库不再创建死列
        assert "last_turn_id" not in _table_columns(store.connection, "engine_sessions")
        assert "resume_status" not in _table_columns(store.connection, "engine_sessions")
        assert "approval_mode" in _table_columns(store.connection, "projects")
        assert "reasoning_effort" in _table_columns(store.connection, "projects")


def test_old_database_is_migrated_on_open(tmp_path: Path) -> None:
    """O4.3：旧库（user_version=0）打开时逐级升级，数据保持可用。

    迁移前：projects 无 approval_mode；engine_sessions 带死列。
    迁移后：补列、删列、user_version=SCHEMA_VERSION，且保存/加载照常。
    """
    database = tmp_path / "old.sqlite"
    old = _old_schema_connection(database)
    now = "2026-01-01T00:00:00+00:00"
    old.execute(
        """INSERT INTO projects(
            project_id, name, root_path, archived, created_at, last_opened_at
        ) VALUES (?, ?, ?, 0, ?, ?)""",
        ("p", "Repo", str(tmp_path), now, now),
    )
    old.execute(
        """INSERT INTO conversations(
            conversation_id, project_id, pair_id, title, last_mode, archived,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
        ("c", "p", "phainon_ancient_machine", "旧聊天", "chat", now, now),
    )
    old.execute(
        """INSERT INTO engine_sessions(
            conversation_id, engine_type, session_ref, last_turn_id, resume_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)""",
        ("c", "scripted", '{"engine_type": "scripted", "opaque_ref": "old-session"}', "old-turn", "ready", now),
    )
    old.commit()
    old.close()

    with SQLiteStore(database) as store:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        # 迁移 1：projects 补 approval_mode（默认 request_approval）
        assert store.get_project("p").approval_mode == "request_approval"
        assert store.get_project("p").reasoning_effort == "low"
        # 迁移 2：engine_sessions 死列已删除
        assert "last_turn_id" not in _table_columns(store.connection, "engine_sessions")
        assert "resume_status" not in _table_columns(store.connection, "engine_sessions")
        # 旧数据保持可读
        assert store.load_conversation("c")["conversation"].conversation_id == "c"
        # 迁移后写入照常（save_engine_session 不再引用 resume_status）
        store.save_engine_session(
            "c", EngineSessionRef(engine_type="scripted", opaque_ref="new-session")
        )
        assert store.load_conversation("c")["engine_session"] == EngineSessionRef(
            engine_type="scripted", opaque_ref="new-session"
        )

    # 再次打开：已是当前版本，迁移步骤不重复执行
    with SQLiteStore(database) as reopened:
        assert reopened.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert "resume_status" not in _table_columns(reopened.connection, "engine_sessions")
