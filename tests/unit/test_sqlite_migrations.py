import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pair_harness.core.contracts import (
    EngineSessionRef,
    Message,
    MessageKind,
    MessageSource,
    ToolRun,
    enum_value,
)
from pair_harness.storage.sqlite_store import (
    SCHEMA_VERSION,
    DatabaseVersionError,
    SQLiteStore,
)
from tests.fixtures.legacy_database import RELEASE_SCHEMAS, create_legacy_database

NOW = "2026-01-01T00:00:00+00:00"
PAIR_ID = "phainon_ancient_machine"

_KINDS = {
    MessageSource.USER: MessageKind.USER_TEXT,
    MessageSource.CHARACTER: MessageKind.CHARACTER_SPEECH,
    MessageSource.ASSISTANT: MessageKind.ASSISTANT_NATURAL_LANGUAGE,
}


def _user_version(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA user_version").fetchone()[0]


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _schema_signature(connection: sqlite3.Connection) -> dict[str, object]:
    # 迁移用 ALTER 补的列排在表尾，列顺序与新库不同，只比较列集合
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
    }
    return {"tables": {table: _columns(connection, table) for table in tables}, "indexes": indexes}


def _message(
    conversation_id: str,
    message_id: str,
    *,
    index: int,
    source: MessageSource = MessageSource.USER,
    pair_id: str = PAIR_ID,
    task_id: str | None = None,
    timeline_order: int | None = None,
) -> Message:
    return Message(
        message_id=message_id,
        conversation_id=conversation_id,
        pair_id=pair_id,
        source=source,
        kind=_KINDS[source],
        text="旧消息",
        task_id=task_id,
        timeline_order=timeline_order,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
    )


def _tool_run(
    tool_call_id: str, *, task_id: str, sequence: int, timeline_order: int | None = None
) -> ToolRun:
    return ToolRun(
        tool_call_id=tool_call_id,
        conversation_id="c",
        task_id=task_id,
        engine_turn_id=f"turn-{task_id}",
        sequence=sequence,
        status="succeeded",
        title="pytest",
        timeline_order=timeline_order,
    )


# 以下写入只用各发布版共有的列，缺省列取旧库自己的默认值。


def _insert_project(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO projects(project_id, name, root_path, created_at, last_opened_at) "
        "VALUES ('p', '旧项目', 'C:/legacy', ?, ?)",
        (NOW, NOW),
    )


def _insert_conversation(
    connection: sqlite3.Connection,
    conversation_id: str,
    *,
    title: str = "旧聊天",
    pair_id: str = PAIR_ID,
) -> None:
    connection.execute(
        "INSERT INTO conversations(conversation_id, project_id, pair_id, title, "
        "created_at, updated_at) VALUES (?, 'p', ?, ?, ?, ?)",
        (conversation_id, pair_id, title, NOW, NOW),
    )


def _insert_message(connection: sqlite3.Connection, message: Message) -> None:
    connection.execute(
        "INSERT INTO messages(message_id, conversation_id, source, kind, created_at, "
        "message_json) VALUES (?, ?, ?, ?, ?, ?)",
        (
            message.message_id,
            message.conversation_id,
            enum_value(message.source),
            enum_value(message.kind),
            message.created_at.isoformat(),
            message.model_dump_json(),
        ),
    )


def _insert_tool_run(connection: sqlite3.Connection, tool_run: ToolRun) -> None:
    connection.execute(
        "INSERT INTO tool_runs(conversation_id, tool_call_id, task_id, engine_turn_id, "
        "sequence, status, tool_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            tool_run.conversation_id,
            tool_run.tool_call_id,
            tool_run.task_id,
            tool_run.engine_turn_id,
            tool_run.sequence,
            tool_run.status,
            tool_run.model_dump_json(),
        ),
    )


def _pre_release_database(database: Path) -> sqlite3.Connection:
    # 引入 user_version 之前的开发版结构：projects 没有 approval_mode，
    # engine_sessions 带 last_turn_id 与 resume_status
    connection = sqlite3.connect(database)
    connection.executescript(
        """
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
    return connection


@pytest.mark.parametrize("version", sorted(RELEASE_SCHEMAS))
def test_release_database_upgrades_to_fresh_schema(tmp_path: Path, version: int) -> None:
    with SQLiteStore(tmp_path / "fresh.sqlite") as fresh:
        expected = _schema_signature(fresh.connection)
    database = tmp_path / "release.sqlite"
    connection = create_legacy_database(database, version)
    _insert_project(connection)
    _insert_conversation(connection, "c")
    _insert_message(connection, _message("c", "m1", index=1))
    connection.commit()
    connection.close()

    with SQLiteStore(database) as store:
        assert _user_version(store.connection) == SCHEMA_VERSION
        assert _schema_signature(store.connection) == expected
        assert [m.message_id for m in store.load_conversation("c").messages] == ["m1"]


def test_pre_release_database_gains_project_settings_and_drops_dead_session_columns(
    tmp_path: Path,
) -> None:
    database = tmp_path / "pre-release.sqlite"
    connection = _pre_release_database(database)
    _insert_project(connection)
    _insert_conversation(connection, "c")
    connection.execute(
        "INSERT INTO engine_sessions(conversation_id, engine_type, session_ref, "
        "last_turn_id, resume_status, updated_at) VALUES ('c', 'scripted', ?, 'old-turn', "
        "'ready', ?)",
        (EngineSessionRef(engine_type="scripted", opaque_ref="old-session").model_dump_json(), NOW),
    )
    connection.commit()
    connection.close()

    with SQLiteStore(database) as store:
        project = store.get_project("p")
        assert (project.approval_mode, project.reasoning_effort) == ("request_approval", "low")
        assert {"last_turn_id", "resume_status"}.isdisjoint(
            _columns(store.connection, "engine_sessions")
        )
        assert store.load_conversation("c").engine_session == EngineSessionRef(
            engine_type="scripted", opaque_ref="old-session"
        )
        store.save_engine_session(
            "c", EngineSessionRef(engine_type="scripted", opaque_ref="new-session")
        )
        assert store.load_conversation("c").engine_session == EngineSessionRef(
            engine_type="scripted", opaque_ref="new-session"
        )


def test_v0_1_0_projects_and_chats_join_default_account(tmp_path: Path) -> None:
    database = tmp_path / "v0.1.0.sqlite"
    connection = create_legacy_database(database, 3)
    _insert_project(connection)
    _insert_conversation(connection, "c")
    connection.commit()
    connection.close()

    with SQLiteStore(database) as store:
        # 迁移建出的默认账号没有密码，空密码可登录
        assert store.verify_password("default-local", "") is True
        assert [p.project_id for p in store.list_projects_for_account("default-local")] == ["p"]
        assert [
            c.conversation_id
            for c in store.list_conversations("p", account_id="default-local")
        ] == ["c"]


def test_migration_repairs_message_pair_id_from_conversation(tmp_path: Path) -> None:
    database = tmp_path / "v0.2.5.sqlite"
    connection = create_legacy_database(database, 7)
    _insert_project(connection)
    _insert_conversation(connection, "c", pair_id="march7_fourth_mirror")
    _insert_message(connection, _message("c", "m1", index=1, pair_id="firefly_sam"))
    connection.commit()
    connection.close()

    with SQLiteStore(database) as store:
        assert [m.pair_id for m in store.load_conversation("c").messages] == [
            "march7_fourth_mirror"
        ]


def test_v0_4_1_named_chats_keep_user_titles_after_upgrade(tmp_path: Path) -> None:
    database = tmp_path / "v0.4.1.sqlite"
    connection = create_legacy_database(database, 11)
    _insert_project(connection)
    _insert_conversation(connection, "unnamed", title="新聊天")
    _insert_conversation(connection, "named", title="周报整理")
    connection.execute(
        "INSERT INTO conversation_inbox(queue_item_id, account_id, conversation_id, "
        "target, text, created_at) VALUES ('q1', 'default-local', 'named', 'character', "
        "'稍后再说', ?)",
        (NOW,),
    )
    connection.commit()
    connection.close()

    with SQLiteStore(database) as store:
        assert store.get_conversation("unnamed").title_source == "default"
        assert store.get_conversation("named").title_source == "user"
        assert store.set_auto_title("named", "自动标题") is False
        assert store.get_conversation("named").title == "周报整理"
        assert store.set_auto_title("unnamed", "自动标题") is True
        queued = store.get_queue_item("q1")
        assert (queued["text"], queued["origin"], queued["remote_device_key"], queued["error"]) == (
            "稍后再说",
            "desktop",
            None,
            None,
        )


def test_v0_4_1_messages_and_tools_are_renumbered_on_one_timeline(tmp_path: Path) -> None:
    database = tmp_path / "v0.4.1.sqlite"
    connection = create_legacy_database(database, 11)
    _insert_project(connection)
    _insert_conversation(connection, "c")
    _insert_conversation(connection, "other")
    # v0.4.1 只给助手分段和工具记录分配序号，用户与角色消息没有序号
    for message in (
        _message("c", "m1", index=1),
        _message(
            "c", "m2", index=2, source=MessageSource.ASSISTANT, task_id="task-1", timeline_order=1
        ),
        _message(
            "c", "m3", index=3, source=MessageSource.ASSISTANT, task_id="task-1", timeline_order=3
        ),
        _message("c", "m4", index=4, source=MessageSource.CHARACTER),
        _message("other", "o1", index=1),
    ):
        _insert_message(connection, message)
    for tool_run in (
        _tool_run("tool-a", task_id="task-1", sequence=1, timeline_order=2),
        _tool_run("tool-b", task_id="task-1", sequence=2, timeline_order=4),
        # 没有序号、所属任务也没有消息的工具记录排到聊天末尾
        _tool_run("tool-legacy", task_id="task-0", sequence=1),
    ):
        _insert_tool_run(connection, tool_run)
    connection.commit()
    connection.close()

    with SQLiteStore(database) as store:
        snapshot = store.load_conversation("c")
        orders = {m.message_id: m.timeline_order for m in snapshot.messages}
        orders.update({run.tool_call_id: run.timeline_order for run in snapshot.tool_runs})
        assert sorted(orders, key=orders.__getitem__) == [
            "m1",
            "m2",
            "tool-a",
            "m3",
            "tool-b",
            "m4",
            "tool-legacy",
        ]
        assert sorted(orders.values()) == list(range(1, 8))
        assert [m.timeline_order for m in store.load_conversation("other").messages] == [1]


def test_failed_migration_level_rolls_back_and_retries_on_next_open(tmp_path: Path) -> None:
    database = tmp_path / "v0.4.1.sqlite"
    connection = create_legacy_database(database, 11)
    _insert_project(connection)
    _insert_conversation(connection, "c", title="周报整理")
    # 让迁移 12 在补列之后的回填语句上真实失败
    connection.execute(
        "CREATE TRIGGER block_backfill BEFORE UPDATE ON conversations "
        "BEGIN SELECT RAISE(ABORT, 'backfill blocked'); END"
    )
    connection.commit()
    connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="backfill blocked"):
        SQLiteStore(database)

    check = sqlite3.connect(database)
    assert _user_version(check) == 11
    assert "title_source" not in _columns(check, "conversations")
    check.execute("DROP TRIGGER block_backfill")
    check.commit()
    check.close()

    with SQLiteStore(database) as retried:
        assert _user_version(retried.connection) == SCHEMA_VERSION
        assert retried.get_conversation("c").title_source == "user"


def test_newer_database_version_refuses_to_open(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    SQLiteStore(database).close()
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(DatabaseVersionError, match=str(SCHEMA_VERSION + 1)):
        SQLiteStore(database)
