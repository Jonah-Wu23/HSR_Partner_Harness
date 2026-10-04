# SQLite 存储与队列恢复

> 67 nodes · cohesion 0.07

## Key Concepts

- **SQLiteStore** (175 connections) — `src/pair_harness/storage/sqlite_store.py`
- **test_sqlite_store.py** (40 connections) — `tests/unit/test_sqlite_store.py`
- **Path** (30 connections)
- **store()** (14 connections) — `tests/unit/test_accounts_store.py`
- **_seed()** (11 connections) — `tests/unit/test_sqlite_store.py`
- **_scope()** (9 connections) — `tests/unit/test_sqlite_store.py`
- **test_latest_summary_follows_coverage_end_time()** (9 connections) — `tests/unit/test_sqlite_store.py`
- **_metric()** (8 connections) — `tests/unit/test_sqlite_store.py`
- **_message()** (7 connections) — `tests/unit/test_sqlite_store.py`
- **test_memory_scope_isolation_by_project_and_assistant()** (7 connections) — `tests/unit/test_sqlite_store.py`
- **test_metric_null_and_zero_semantics()** (7 connections) — `tests/unit/test_sqlite_store.py`
- **test_metric_query_filters_and_cursor_pagination()** (7 connections) — `tests/unit/test_sqlite_store.py`
- **test_metric_upsert_keeps_one_row_per_turn()** (7 connections) — `tests/unit/test_sqlite_store.py`
- **test_summary_failure_keeps_real_error()** (7 connections) — `tests/unit/test_sqlite_store.py`
- **test_summary_upsert_is_idempotent_by_range()** (7 connections) — `tests/unit/test_sqlite_store.py`
- **test_message_source_kind_columns_store_enum_values()** (6 connections) — `tests/unit/test_sqlite_store.py`
- **test_message_with_lone_surrogates_can_be_persisted()** (6 connections) — `tests/unit/test_sqlite_store.py`
- **test_metric_terminal_state_cannot_regress()** (6 connections) — `tests/unit/test_sqlite_store.py`
- **test_summary_rejects_unknown_status_and_missing_row()** (6 connections) — `tests/unit/test_sqlite_store.py`
- **test_memory_assistant_identity_unique_key_and_mutation_scope()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_memory_delete_is_soft_and_recreatable()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_memory_same_content_in_scope_is_idempotent()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_memory_update_content_and_missing_row()** (5 connections) — `tests/unit/test_sqlite_store.py`
- **test_clear_engine_sessions_invalidates_only_target_account()** (4 connections) — `tests/unit/test_sqlite_store.py`
- **test_metric_query_rejects_bad_cursor()** (4 connections) — `tests/unit/test_sqlite_store.py`
- *... and 42 more nodes in this community*

## Relationships

- [长期记忆与指标记录](长期记忆与指标记录.md) (30 shared connections)
- [SQLite 项目与会话存储](SQLite_项目与会话存储.md) (26 shared connections)
- [SQLite 队列项持久化](SQLite_队列项持久化.md) (12 shared connections)
- [会话摘要 SQLite 存储](会话摘要_SQLite_存储.md) (12 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (10 shared connections)
- [账号存储与密码校验](账号存储与密码校验.md) (9 shared connections)
- [PBKDF2 密码派生与校验](PBKDF2_密码派生与校验.md) (8 shared connections)
- [SQLite 迁移测试](SQLite_迁移测试.md) (8 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (5 shared connections)
- [回合指标记录与校验](回合指标记录与校验.md) (5 shared connections)
- [SQLite 会话仓储](SQLite_会话仓储.md) (5 shared connections)
- [角色卡资产存储](角色卡资产存储.md) (4 shared connections)

## Source Files

- `src/pair_harness/storage/sqlite_store.py`
- `tests/unit/test_accounts_store.py`
- `tests/unit/test_sqlite_store.py`

## Audit Trail

- EXTRACTED: 243 (76%)
- INFERRED: 78 (24%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*