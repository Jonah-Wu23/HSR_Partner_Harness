# SQLite 存储与 schema 迁移

> 32 nodes · cohesion 0.11

## Key Concepts

- **test_sqlite_store.py** (24 connections) — `tests/unit/test_sqlite_store.py`
- **Path** (21 connections)
- **test_old_database_is_migrated_on_open()** (7 connections) — `tests/unit/test_sqlite_store.py`
- **_old_schema_connection()** (6 connections) — `tests/unit/test_sqlite_store.py`
- **_table_columns()** (6 connections) — `tests/unit/test_sqlite_store.py`
- **test_message_with_lone_surrogates_can_be_persisted()** (6 connections) — `tests/unit/test_sqlite_store.py`
- **test_clear_engine_sessions_invalidates_only_target_account()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_conversation_character_card_id_roundtrip()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_fresh_database_marks_schema_version()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_migration_v10_adds_character_card_id_without_data_loss()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_migration_v7_backfills_conversation_account_from_project()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_conversation_account_id_is_written_and_filters()** (4 connections) — `tests/unit/test_sqlite_store.py`
- **test_migration_v8_repairs_message_pair_id_from_conversation()** (4 connections) — `tests/unit/test_sqlite_store.py`
- **test_new_conversation_does_not_inherit_history_or_session()** (4 connections) — `tests/unit/test_sqlite_store.py`
- **test_set_configs_and_secrets_is_atomic_on_failure()** (4 connections) — `tests/unit/test_sqlite_store.py`
- **test_approval_mode_is_persisted_per_project()** (3 connections) — `tests/unit/test_sqlite_store.py`
- **test_desktop_conversation_mode_and_archive_preserve_project()** (3 connections) — `tests/unit/test_sqlite_store.py`
- **test_legacy_message_turn_id_reads_back_as_engine_turn_id()** (3 connections) — `tests/unit/test_sqlite_store.py`
- **test_legacy_tool_run_status_completed_reads_back_as_succeeded()** (3 connections) — `tests/unit/test_sqlite_store.py`
- **test_missing_project_path_keeps_history_readable()** (3 connections) — `tests/unit/test_sqlite_store.py`
- **test_project_can_be_reopened_by_normalized_root_path()** (3 connections) — `tests/unit/test_sqlite_store.py`
- **test_reasoning_effort_is_persisted_per_project()** (3 connections) — `tests/unit/test_sqlite_store.py`
- **Connection** (2 connections)
- **构造 O4.3 迁移前的旧库（user_version=0 的 v0 结构）。 与历史 schema.sql 一致：projects 无…** (1 connections) — `tests/unit/test_sqlite_store.py`
- **O4.3：新库由 schema.sql 一次建全，直接标记 SCHEMA_VERSION。** (1 connections) — `tests/unit/test_sqlite_store.py`
- *... and 7 more nodes in this community*

## Relationships

- [存储增量缓冲与刷盘](存储增量缓冲与刷盘.md) (18 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (8 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (3 shared connections)
- [委派与契约模型](委派与契约模型.md) (2 shared connections)

## Source Files

- `tests/unit/test_sqlite_store.py`

## Audit Trail

- EXTRACTED: 62 (71%)
- INFERRED: 25 (29%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*