"""V0.3.9 存储层定向测试（contract-v1 第 1/2/4/5 节）。

覆盖：批量增量落库与刷盘阈值、终态/退出刷盘语义、迁移 11 的原子性与
新旧库结构一致、聊天摘要、持久化投影、配对长期记忆作用域隔离、
回合指标空值语义与游标分页、长聊天分页装载。
"""

from __future__ import annotations

import gc
import math
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import pair_harness.storage.sqlite_store as store_module
from pair_harness.core.contracts import Message, MessageKind, MessageSource, ToolRun
from pair_harness.storage.records import (
    ConversationSummary,
    MemoryScope,
    PairMemory,
    ProjectionEntry,
    TurnMetric,
    TurnMetricQuery,
)
from pair_harness.storage.sqlite_store import (
    BATCH_MAX_WRITES,
    MIGRATIONS,
    SCHEMA_VERSION,
    SQLiteStore,
)

V039_TABLES = (
    "conversation_projections",
    "conversation_summaries",
    "pair_memories",
    "turn_metrics",
)


def _seed(store: SQLiteStore, *, conversation_id: str = "c1", project_id: str = "p1") -> str:
    store.create_project(name="Repo", root_path=str(store.database.parent), project_id=project_id)
    store.create_conversation(
        project_id=project_id,
        pair_id="phainon_ancient_machine",
        title="聊天",
        conversation_id=conversation_id,
        account_id="default-local",
    )
    return conversation_id


def _message(
    conversation_id: str,
    text: str,
    *,
    index: int = 0,
    source: MessageSource = MessageSource.USER,
    origin: str = "user",
    message_id: str | None = None,
) -> Message:
    return Message(
        message_id=message_id or f"m{index}",
        conversation_id=conversation_id,
        pair_id="phainon_ancient_machine",
        source=source,
        kind={
            MessageSource.USER: MessageKind.USER_TEXT,
            MessageSource.CHARACTER: MessageKind.CHARACTER_SPEECH,
        }.get(source, MessageKind.ASSISTANT_NATURAL_LANGUAGE),
        text=text,
        origin=origin,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
    )


def _metric(
    conversation_id: str,
    *,
    turn_id: str,
    index: int = 0,
    status: str = "completed",
    turn_kind: str = "character_turn",
    **overrides: object,
) -> TurnMetric:
    payload = {
        "account_id": "default-local",
        "project_id": "p1",
        "conversation_id": conversation_id,
        "pair_id": "phainon_ancient_machine",
        "character_ref": "builtin:phainon",
        "assistant_identity": "ancient_machine",
        "turn_kind": turn_kind,
        "turn_id": turn_id,
        "status": status,
        "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
    }
    payload.update(overrides)
    return TurnMetric(**payload)


def _scope(**overrides: str) -> MemoryScope:
    payload = {
        "account_id": "default-local",
        "project_id": "p1",
        "pair_id": "phainon_ancient_machine",
        "character_ref": "builtin:phainon",
        "assistant_identity": "ancient_machine",
    }
    payload.update(overrides)
    return MemoryScope(**payload)


# ---------------------------------------------------------------- 批量增量与刷盘


def test_batch_enqueue_flushes_one_transaction_and_coalesces(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        for index in range(10):
            store.enqueue_message(_message(cid, f"第{index}条", index=index))
        assert store.pending_writes == 10
        written = store.flush()

        assert written == 10
        assert store.pending_writes == 0
        stats = store.stats()
        assert stats["batch_transactions"] == 1
        assert stats["batch_rows"] == 10
        assert stats["max_batch_rows"] == 10
        assert [m.text for m in store.load_conversation(cid)["messages"]] == [
            f"第{index}条" for index in range(10)
        ]


def test_batch_same_key_keeps_last_state_and_first_position(tmp_path: Path) -> None:
    """同一主键保留最后状态，位置保持首次出现（契约第 4 节）。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        first = _message(cid, "草稿", index=0, message_id="m-fixed")
        second = _message(cid, "最终", index=0, message_id="m-fixed")
        other = _message(cid, "中间", index=1, message_id="m-other")
        store.enqueue_message(first)
        store.enqueue_message(other)
        store.enqueue_message(second)
        assert store.pending_writes == 2
        store.flush()

        messages = store.load_conversation(cid)["messages"]
        assert [m.message_id for m in messages] == ["m-fixed", "m-other"]
        assert messages[0].text == "最终"


def test_batch_touches_conversation_updated_at_once(tmp_path: Path) -> None:
    """整批只更新一次 updated_at（契约第 4 节）。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        store.connection.execute(
            "CREATE TABLE touch_log(conversation_id TEXT, touched_at TEXT)"
        )
        store.connection.execute(
            "CREATE TRIGGER log_touch AFTER UPDATE OF updated_at ON conversations "
            "BEGIN INSERT INTO touch_log(conversation_id, touched_at) "
            "VALUES (NEW.conversation_id, NEW.updated_at); END"
        )
        store.connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
            ("2020-01-01T00:00:00+00:00", cid),
        )
        store.connection.execute("DELETE FROM touch_log")
        store.connection.commit()
        for index in range(5):
            store.enqueue_message(_message(cid, f"第{index}条", index=index))
        store.flush()

        touches = store.connection.execute(
            "SELECT COUNT(*) AS n FROM touch_log WHERE conversation_id = ?", (cid,)
        ).fetchone()
        assert touches["n"] == 1
        assert store.get_conversation(cid).updated_at > datetime(
            2020, 1, 1, tzinfo=timezone.utc
        )


def test_flush_if_due_uses_50ms_window(tmp_path: Path) -> None:
    """定时样本：75ms 注入一条，每次到点都刷盘（契约第 4 节）。"""
    clock = [1000.0]
    with SQLiteStore(tmp_path / "db.sqlite", clock=lambda: clock[0]) as store:
        cid = _seed(store)
        flushes = 0
        for index in range(400):
            store.enqueue_message(_message(cid, f"第{index}条", index=index))
            clock[0] += 0.075
            deadline = store.next_flush_deadline()
            assert deadline == pytest.approx(clock[0] - 0.075 + 0.05)
            if store.flush_if_due():
                flushes += 1
        assert flushes == 400
        assert store.pending_writes == 0
        assert store.stats()["batch_transactions"] == 400


def test_flush_if_due_skips_before_deadline(tmp_path: Path) -> None:
    clock = [2000.0]
    with SQLiteStore(tmp_path / "db.sqlite", clock=lambda: clock[0]) as store:
        cid = _seed(store)
        store.enqueue_message(_message(cid, "一条", index=0))
        assert store.flush_if_due() is False
        assert store.pending_writes == 1
        clock[0] += 0.049
        assert store.flush_if_due() is False
        clock[0] += 0.002
        assert store.flush_if_due() is True
        assert store.pending_writes == 0


def test_burst_sample_transaction_bound(tmp_path: Path) -> None:
    """突发样本：每聊天 2000 个普通增量，事务数不超过 ceil(n/50)。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        for index in range(2000):
            store.enqueue_message(_message(cid, f"第{index}条", index=index))
        store.flush()
        stats = store.stats()
        assert stats["batch_transactions"] <= math.ceil(2000 / BATCH_MAX_WRITES)
        assert stats["max_batch_rows"] <= BATCH_MAX_WRITES
        assert len(store.load_conversation(cid)["messages"]) == 2000


def test_unflushed_increments_are_really_lost_on_hard_kill(tmp_path: Path) -> None:
    """强杀语义：未到 50ms 的普通增量真实丢失，重启不得合成（契约第 4 节）。"""
    database = tmp_path / "db.sqlite"
    store = SQLiteStore(database)
    cid = _seed(store)
    store.enqueue_message(_message(cid, "尚未刷盘", index=0))
    # 绕过 close()（close 会强制刷盘），直接丢弃连接模拟进程被强杀
    store.connection.close()

    with SQLiteStore(database) as reopened:
        assert reopened.load_conversation(cid)["messages"] == ()


def test_close_flushes_pending_increments(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    store = SQLiteStore(database)
    cid = _seed(store)
    store.enqueue_message(_message(cid, "退出前刷盘", index=0))
    store.close()

    with SQLiteStore(database) as reopened:
        assert [m.text for m in reopened.load_conversation(cid)["messages"]] == ["退出前刷盘"]


def test_immediate_save_still_durable_before_batch(tmp_path: Path) -> None:
    """用户提交确认走同步落库，不受批量窗口影响（V0.2 M1 契约）。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        store.save_message(_message(cid, "用户消息", index=0))
        store.enqueue_message(_message(cid, "角色回复", index=1, source=MessageSource.CHARACTER))
        rows = store.connection.execute(
            "SELECT message_id FROM messages WHERE conversation_id = ?", (cid,)
        ).fetchall()
        assert len(rows) == 1
        assert store.stats()["immediate_writes"] == 1
        assert store.pending_writes == 1


# ---------------------------------------------------------------- 迁移


def _drop_v039_objects(connection: sqlite3.Connection) -> None:
    for table in V039_TABLES:
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.commit()


def _schema_signature(connection: sqlite3.Connection) -> dict[str, object]:
    tables: dict[str, tuple[str, ...]] = {}
    for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ):
        tables[row[0]] = tuple(
            item[1] for item in connection.execute(f"PRAGMA table_info({row[0]})")
        )
    indexes = tuple(
        sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        )
    )
    return {"tables": tables, "indexes": indexes}


def test_migration_11_upgrades_v10_library_and_matches_fresh_schema(tmp_path: Path) -> None:
    """旧库（user_version=10）打开后补建 V0.3.9 表，结构与新库一致。"""
    database = tmp_path / "v10.sqlite"
    with SQLiteStore(database) as fresh_store:
        fresh_signature = _schema_signature(fresh_store.connection)
        cid = _seed(fresh_store)
        fresh_store.save_message(_message(cid, "旧消息", index=0))
    connection = sqlite3.connect(database)
    _drop_v039_objects(connection)
    connection.execute("PRAGMA user_version = 10")
    connection.commit()
    connection.close()

    with SQLiteStore(database) as store:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert _schema_signature(store.connection) == fresh_signature
        # 旧数据保持可读，新表可写
        assert [m.text for m in store.load_conversation(cid)["messages"]] == ["旧消息"]
        store.upsert_summary(
            ConversationSummary(
                conversation_id=cid,
                covers_from_message_id="m0",
                covers_to_message_id="m0",
                covers_message_count=1,
                content="摘要",
                status="completed",
            )
        )
        assert len(store.list_summaries(cid)) == 1


def test_migration_level_is_atomic_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """迁移中断：整级回滚（含 DDL）、user_version 不推进，重开可干净重试。

    用一级合成迁移验证：CREATE TABLE + INSERT + 失败语句。sqlite3 默认
    隔离级别下 DDL 不自动进事务，因此必须由 _migrate 显式 BEGIN，
    否则中断会留下半张表。
    """
    database = tmp_path / "v10.sqlite"
    with SQLiteStore(database) as store:
        _seed(store)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 10")
    connection.commit()
    connection.close()

    failing_level = (
        "CREATE TABLE probe_table(x TEXT)",
        "INSERT INTO probe_table(x) VALUES ('半截')",
        "THIS IS NOT SQL",
    )
    monkeypatch.setattr(
        store_module, "MIGRATIONS", MIGRATIONS[:10] + (failing_level,)
    )
    with pytest.raises(sqlite3.OperationalError):
        SQLiteStore(database)
    gc.collect()

    check = sqlite3.connect(database)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 10
    names = {
        row[0]
        for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "probe_table" not in names
    check.close()

    monkeypatch.undo()
    with SQLiteStore(database) as retried:
        assert retried.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert retried.list_summaries("c1") == []


def test_migrations_cover_every_version_level() -> None:
    assert len(MIGRATIONS) == SCHEMA_VERSION


# ---------------------------------------------------------------- 摘要


def test_summary_upsert_is_idempotent_by_range(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        first = store.upsert_summary(
            ConversationSummary(
                conversation_id=cid,
                covers_from_message_id="m1",
                covers_to_message_id="m80",
                covers_message_count=80,
                content="第一版",
                provider="deepseek",
                model="deepseek-v4-flash",
                status="running",
            )
        )
        second = store.upsert_summary(
            ConversationSummary(
                conversation_id=cid,
                covers_from_message_id="m1",
                covers_to_message_id="m80",
                covers_message_count=80,
                content="第二版",
                provider="deepseek",
                model="deepseek-v4-flash",
                status="completed",
            )
        )
        # 区间相同 → 保留原 summary_id，只更新内容与状态
        assert second.summary_id == first.summary_id
        assert second.content == "第二版"
        assert second.status == "completed"
        assert len(store.list_summaries(cid)) == 1
        assert store.latest_completed_summary(cid).summary_id == first.summary_id


def test_summary_failure_keeps_real_error(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        summary = store.upsert_summary(
            ConversationSummary(
                conversation_id=cid,
                covers_from_message_id="m1",
                covers_to_message_id="m9",
                covers_message_count=9,
                status="failed",
                error_code="summary_timeout",
                error="provider timeout",
            )
        )
        assert summary.content == ""
        assert summary.error_code == "summary_timeout"
        assert summary.error == "provider timeout"
        assert store.latest_completed_summary(cid) is None

        updated = store.update_summary(summary.summary_id, status="completed", content="补跑成功")
        assert updated.status == "completed"
        assert updated.content == "补跑成功"
        assert store.latest_completed_summary(cid).summary_id == summary.summary_id


def test_summary_rejects_unknown_status_and_missing_row(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        with pytest.raises(ValueError, match="未知摘要状态"):
            store.upsert_summary(
                ConversationSummary(
                    conversation_id=cid,
                    covers_from_message_id="m1",
                    covers_to_message_id="m2",
                    covers_message_count=2,
                    status="半途",
                )
            )
        with pytest.raises(KeyError):
            store.update_summary("不存在", status="completed")


# ---------------------------------------------------------------- 投影


def test_projection_order_and_collapse(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        entries = [
            ProjectionEntry(
                conversation_id=cid,
                position=index,
                kind="message",
                message_id=f"m{index}",
            )
            for index in range(5)
        ]
        store.append_projection_entries(entries)
        assert [e.position for e in store.list_projection(cid)] == [0, 1, 2, 3, 4]

        removed = store.collapse_projection_span(
            cid,
            covers_from_message_id="m0",
            covers_to_message_id="m2",
            summary_id="s1",
        )
        assert removed == 3
        projection = store.list_projection(cid)
        assert [e.position for e in projection] == [0, 1, 2]
        assert projection[0].kind == "summary"
        assert projection[0].summary_id == "s1"
        assert [e.message_id for e in projection[1:]] == ["m3", "m4"]


def test_projection_rejects_non_contiguous_span(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        store.append_projection_entries(
            [
                ProjectionEntry(conversation_id=cid, position=0, kind="message", message_id="m0"),
                ProjectionEntry(conversation_id=cid, position=1, kind="summary", summary_id="s0"),
                ProjectionEntry(conversation_id=cid, position=2, kind="message", message_id="m1"),
            ]
        )
        with pytest.raises(ValueError, match="连续"):
            store.collapse_projection_span(
                cid,
                covers_from_message_id="m0",
                covers_to_message_id="m1",
                summary_id="s1",
            )


def test_projection_position_conflict_raises(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        store.append_projection_entry(
            ProjectionEntry(conversation_id=cid, position=0, kind="message", message_id="m0")
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.append_projection_entry(
                ProjectionEntry(
                    conversation_id=cid, position=0, kind="message", message_id="m1"
                )
            )


def test_role_message_stats_since_filters_structurally(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        store.save_messages(
            [
                _message(cid, "用户一", index=0),
                _message(
                    cid,
                    "角色一",
                    index=1,
                    source=MessageSource.CHARACTER,
                    origin="user",
                ),
                _message(
                    cid,
                    "委派镜像",
                    index=2,
                    origin="character_delegation",
                ),
                _message(cid, "助手输出", index=3, source=MessageSource.ASSISTANT),
                _message(cid, "空正文", index=4, message_id="m-empty"),
                _message(cid, "用户二", index=5),
            ]
        )
        store.connection.execute("UPDATE messages SET message_json = json_set("
                                "message_json, '$.text', '') WHERE message_id = 'm-empty'")
        store.connection.commit()

        stats = store.role_message_stats_since(cid)
        assert stats["message_count"] == 3
        assert stats["text_bytes"] == len("用户一".encode()) + len("角色一".encode()) + len(
            "用户二".encode()
        )

        after = store.role_message_stats_since(cid, after_message_id="m1")
        assert after["message_count"] == 1


# ---------------------------------------------------------------- 长期记忆


def test_memory_scope_isolation_by_project_and_assistant(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        scope = _scope()
        store.upsert_memory(
            PairMemory(
                **scope.model_dump(),
                conversation_id=cid,
                content="喜欢安静地看星星",
            )
        )
        assert len(store.list_memories(scope)) == 1
        # 换项目、换角色、换助手身份都读不到（契约第 1 节）
        assert store.list_memories(_scope(project_id="p2")) == []
        assert store.list_memories(_scope(character_ref="card:other")) == []
        assert store.list_memories(_scope(assistant_identity="another_assistant")) == []
        assert store.list_memories(_scope(account_id="account-b")) == []


def test_memory_requires_complete_scope(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        _seed(store)
        with pytest.raises(ValueError, match="project_id"):
            MemoryScope(
                account_id="default-local",
                project_id="",
                pair_id="phainon_ancient_machine",
                character_ref="builtin:phainon",
                assistant_identity="ancient_machine",
            )


def test_memory_delete_is_soft_and_recreatable(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        scope = _scope()
        memory = store.upsert_memory(PairMemory(**scope.model_dump(), content="一条记忆"))
        deleted = store.delete_memory(memory.memory_id)
        assert deleted.status == "deleted"
        assert store.list_memories(scope) == []
        assert store.count_memories(scope) == 0
        assert store.count_memories(scope, status=None) == 1
        assert store.get_memory(memory.memory_id).status == "deleted"

        # 删除后同内容可以重新写入（partial unique index 只约束 active）
        recreated = store.upsert_memory(PairMemory(**scope.model_dump(), content="一条记忆"))
        assert recreated.status == "active"
        assert recreated.memory_id != memory.memory_id
        assert store.count_memories(scope) == 1
        assert store.count_memories(scope, status=None) == 2


def test_memory_same_content_in_scope_is_idempotent(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        scope = _scope()
        first = store.upsert_memory(PairMemory(**scope.model_dump(), content="同一条"))
        second = store.upsert_memory(
            PairMemory(**scope.model_dump(), conversation_id="c-other", content="同一条")
        )
        assert second.memory_id == first.memory_id
        assert second.conversation_id == "c-other"
        assert store.count_memories(scope) == 1


def test_memory_update_content_and_missing_row(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        scope = _scope()
        memory = store.upsert_memory(PairMemory(**scope.model_dump(), content="旧内容"))
        updated = store.update_memory(memory.memory_id, content="新内容")
        assert updated.content == "新内容"
        with pytest.raises(KeyError):
            store.update_memory("不存在", content="x")
        with pytest.raises(ValueError, match="不支持的记忆字段"):
            store.update_memory(memory.memory_id, keyword="x")


def test_memory_assistant_identity_unique_key_and_mutation_scope(tmp_path: Path) -> None:
    """记忆唯一键与所有查询/修改必须含 assistant_identity（契约第 1 节）。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        scope_a = _scope(assistant_identity="assistant_a")
        scope_b = _scope(assistant_identity="assistant_b")

        # 1. 唯一键含 assistant_identity：不同助手同内容同项目可并存
        mem_a = store.upsert_memory(PairMemory(**scope_a.model_dump(), content="重要约定"))
        mem_b = store.upsert_memory(PairMemory(**scope_b.model_dump(), content="重要约定"))
        assert mem_a.memory_id != mem_b.memory_id
        assert store.count_memories(scope_a) == 1
        assert store.count_memories(scope_b) == 1

        # 2. 查询隔离：各助手只查到各自的记忆
        assert [m.memory_id for m in store.list_memories(scope_a)] == [mem_a.memory_id]
        assert [m.memory_id for m in store.list_memories(scope_b)] == [mem_b.memory_id]
        assert store.get_memory_by_content(scope_a, content="重要约定").memory_id == mem_a.memory_id
        assert store.get_memory_by_content(scope_b, content="重要约定").memory_id == mem_b.memory_id

        # 3. 带 scope 校验的读取/修改/删除：跨助手操作报 memory_scope_mismatch
        with pytest.raises(KeyError, match="memory_scope_mismatch"):
            store.get_memory(mem_a.memory_id, scope=scope_b)
        with pytest.raises(KeyError, match="memory_scope_mismatch"):
            store.update_memory(mem_a.memory_id, scope=scope_b, content="恶意篡改")
        with pytest.raises(KeyError, match="memory_scope_mismatch"):
            store.delete_memory(mem_a.memory_id, scope=scope_b)

        # 4. 删除助手 A 记忆，助手 B 记忆保持 active 不受影响
        deleted_a = store.delete_memory(mem_a.memory_id, scope=scope_a)
        assert deleted_a.status == "deleted"
        assert store.count_memories(scope_a) == 0
        assert store.count_memories(scope_b) == 1
        assert store.get_memory(mem_b.memory_id, scope=scope_b).status == "active"


# ---------------------------------------------------------------- 指标


def test_metric_null_and_zero_semantics(tmp_path: Path) -> None:
    """契约第 5 节：未观测字段为 null 且键存在，真实零值使用 0。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        stored = store.upsert_turn_metric(_metric(cid, turn_id="t1", status="running"))
        assert stored.input_tokens is None
        assert stored.output_tokens is None
        assert stored.total_tokens is None
        assert stored.tool_rounds == 0
        assert stored.failure_type is None
        assert stored.origin == "desktop"
        assert stored.remote_device_key is None

        reloaded = store.get_turn_metric(stored.metric_id)
        assert reloaded == stored

        updated = store.update_turn_metric(
            stored.metric_id,
            status="failed",
            failure_type="provider_error",
            failure_message="HTTP 503",
            input_tokens=None,
        )
        assert updated.status == "failed"
        assert updated.failure_type == "provider_error"
        assert updated.input_tokens is None


def test_metric_upsert_keeps_one_row_per_turn(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        store.upsert_turn_metric(_metric(cid, turn_id="t1", status="running"))
        store.upsert_turn_metric(_metric(cid, turn_id="t1", status="completed", tool_rounds=3))
        rows = store.connection.execute(
            "SELECT COUNT(*) AS n FROM turn_metrics WHERE conversation_id = ?", (cid,)
        ).fetchone()
        assert rows["n"] == 1
        metric = store.get_turn_metric_by_turn(cid, turn_kind="character_turn", turn_id="t1")
        assert metric.status == "completed"
        assert metric.tool_rounds == 3

        bumped = store.bump_turn_metric(metric.metric_id, tool_rounds=1, compression_count=2)
        assert bumped.tool_rounds == 4
        assert bumped.compression_count == 2
        assert bumped.approval_count == 0


def test_metric_query_filters_and_cursor_pagination(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        for index in range(5):
            store.upsert_turn_metric(
                _metric(
                    cid,
                    turn_id=f"t{index}",
                    index=index,
                    status="completed" if index % 2 == 0 else "failed",
                )
            )
        store.upsert_turn_metric(
            _metric(cid, turn_id="task-1", index=9, turn_kind="assistant_task", origin="remote",
                    remote_device_key="device-1")
        )

        page = store.query_turn_metrics(TurnMetricQuery(conversation_id=cid, limit=2))
        assert [item.turn_id for item in page.items] == ["task-1", "t4"]
        assert page.next_cursor is not None
        second = store.query_turn_metrics(
            TurnMetricQuery(conversation_id=cid, limit=2, cursor=page.next_cursor)
        )
        assert [item.turn_id for item in second.items] == ["t3", "t2"]

        failed = store.query_turn_metrics(
            TurnMetricQuery(conversation_id=cid, status="failed")
        )
        assert {item.turn_id for item in failed.items} == {"t1", "t3"}

        remote = store.query_turn_metrics(TurnMetricQuery(origin="remote"))
        assert [item.turn_id for item in remote.items] == ["task-1"]
        assert remote.items[0].remote_device_key == "device-1"

        by_assistant = store.query_turn_metrics(
            TurnMetricQuery(assistant_identity="ancient_machine")
        )
        assert len(by_assistant.items) == 6
        assert store.count_turn_metrics(TurnMetricQuery(assistant_identity="unknown_assistant")) == 0

        assert store.count_turn_metrics(TurnMetricQuery(conversation_id=cid)) == 6


def test_find_active_conversation_with_pair_and_card(tmp_path: Path) -> None:
    """活跃会话复用支持按 project_id、pair_id、character_card_id 过滤（契约 §1）。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        store.create_project(name="Repo", root_path=str(tmp_path), project_id="p1")
        conv1 = store.create_conversation(
            project_id="p1",
            pair_id="pair_a",
            title="聊天1",
            character_card_id="card_x",
            account_id="acc1",
        )
        conv2 = store.create_conversation(
            project_id="p1",
            pair_id="pair_b",
            title="聊天2",
            character_card_id="card_x",
            account_id="acc1",
        )
        found_a = store.find_active_conversation(
            "p1", character_card_id="card_x", pair_id="pair_a", account_id="acc1"
        )
        assert found_a is not None and found_a.conversation_id == conv1.conversation_id
        found_b = store.find_active_conversation(
            "p1", character_card_id="card_x", pair_id="pair_b", account_id="acc1"
        )
        assert found_b is not None and found_b.conversation_id == conv2.conversation_id
        assert store.find_active_conversation("p1", pair_id="pair_c") is None


def test_metric_terminal_state_cannot_regress(tmp_path: Path) -> None:
    """契约第 5 节：终态不可回退（同状态幂等重写仍允许）。"""
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        metric = store.upsert_turn_metric(_metric(cid, turn_id="t1", status="completed"))
        # 同状态重写允许
        again = store.upsert_turn_metric(_metric(cid, turn_id="t1", status="completed"))
        assert again.metric_id == metric.metric_id
        with pytest.raises(ValueError, match="终态不可回退"):
            store.upsert_turn_metric(_metric(cid, turn_id="t1", status="running"))
        with pytest.raises(ValueError, match="终态不可回退"):
            store.update_turn_metric(metric.metric_id, status="running")
        # 非终态之间可以推进
        running = store.upsert_turn_metric(_metric(cid, turn_id="t2", status="running"))
        assert store.update_turn_metric(running.metric_id, status="cancelled").status == (
            "cancelled"
        )


def test_load_messages_page_rejects_foreign_anchor(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        _seed(store, conversation_id="c2")
        store.save_messages([_message(cid, f"第{index}条", index=index) for index in range(3)])
        store.save_message(_message("c2", "别的聊天", index=9, message_id="other"))
        with pytest.raises(KeyError, match="unknown message_id in conversation"):
            store.load_messages_page(cid, limit=2, before_message_id="other")


def test_metric_query_limit_is_capped_at_200(tmp_path: Path) -> None:
    query = TurnMetricQuery(limit=1000)
    assert query.limit == 200
    with pytest.raises(ValueError, match="limit"):
        TurnMetricQuery(limit=0)


def test_metric_query_rejects_bad_cursor(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        with pytest.raises(ValueError, match="游标"):
            store.query_turn_metrics(TurnMetricQuery(cursor="不是游标"))


def test_metric_rejects_unknown_status(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        with pytest.raises(ValueError, match="未知指标状态"):
            _metric(cid, turn_id="t1", status="半途")


# ---------------------------------------------------------------- 分页与性能样本


def test_load_messages_page_is_stable_without_rowid(tmp_path: Path) -> None:
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        store.save_messages([_message(cid, f"第{index}条", index=index) for index in range(10)])
        # 重存同一条消息不得改变顺序（ON CONFLICT 不改 rowid）
        store.save_message(_message(cid, "第0条改", index=0))

        latest = store.load_messages_page(cid, limit=3)
        assert [m.text for m in latest] == ["第7条", "第8条", "第9条"]
        older = store.load_messages_page(cid, limit=3, before_message_id=latest[0].message_id)
        assert [m.text for m in older] == ["第4条", "第5条", "第6条"]
        assert [m.text for m in store.load_conversation(cid)["messages"]][0] == "第0条改"


def test_batch_sample_stays_within_budget(tmp_path: Path) -> None:
    """统一样本的单聊天 500 条：批量写入一次事务，打开耗时记录在案。

    阈值放宽到契约目标的数倍，只用于拦住数量级回归；严格预算在真机
    验收记录里按三轮中位数填写。
    """
    with SQLiteStore(tmp_path / "db.sqlite") as store:
        cid = _seed(store)
        messages = [_message(cid, "内容" * 60 + str(index), index=index) for index in range(500)]
        started = time.perf_counter()
        store.save_messages(messages)
        write_seconds = time.perf_counter() - started
        assert store.stats()["batch_transactions"] == 1
        assert write_seconds / 500 <= 0.5

        started = time.perf_counter()
        snapshot = store.load_conversation(cid)
        open_seconds = time.perf_counter() - started
        assert len(snapshot["messages"]) == 500
        assert open_seconds <= 1.0
        print(
            f"[budget] 500 条批量写入 {write_seconds * 1000:.1f}ms "
            f"({write_seconds * 1000 / 500:.3f}ms/条)，打开 {open_seconds * 1000:.1f}ms"
        )
