# SQLite 迁移测试

> 28 nodes · cohesion 0.21

## Key Concepts

- **test_sqlite_migrations.py** (22 connections) — `tests/unit/test_sqlite_migrations.py`
- **create_legacy_database()** (13 connections) — `tests/fixtures/legacy_database.py`
- **test_release_database_upgrades_to_fresh_schema()** (11 connections) — `tests/unit/test_sqlite_migrations.py`
- **test_v0_4_1_messages_and_tools_are_renumbered_on_one_timeline()** (11 connections) — `tests/unit/test_sqlite_migrations.py`
- **_insert_conversation()** (9 connections) — `tests/unit/test_sqlite_migrations.py`
- **_insert_project()** (9 connections) — `tests/unit/test_sqlite_migrations.py`
- **Path** (9 connections)
- **_insert_message()** (8 connections) — `tests/unit/test_sqlite_migrations.py`
- **Connection** (8 connections)
- **test_failed_migration_level_rolls_back_and_retries_on_next_open()** (8 connections) — `tests/unit/test_sqlite_migrations.py`
- **test_migration_repairs_message_pair_id_from_conversation()** (8 connections) — `tests/unit/test_sqlite_migrations.py`
- **test_pre_release_database_gains_project_settings_and_drops_dead_session_columns()** (8 connections) — `tests/unit/test_sqlite_migrations.py`
- **_message()** (7 connections) — `tests/unit/test_sqlite_migrations.py`
- **test_v0_1_0_projects_and_chats_join_default_account()** (6 connections) — `tests/unit/test_sqlite_migrations.py`
- **test_v0_4_1_named_chats_keep_user_titles_after_upgrade()** (6 connections) — `tests/unit/test_sqlite_migrations.py`
- **_columns()** (5 connections) — `tests/unit/test_sqlite_migrations.py`
- **legacy_database.py** (4 connections) — `tests/fixtures/legacy_database.py`
- **_insert_tool_run()** (4 connections) — `tests/unit/test_sqlite_migrations.py`
- **_pre_release_database()** (4 connections) — `tests/unit/test_sqlite_migrations.py`
- **_schema_signature()** (4 connections) — `tests/unit/test_sqlite_migrations.py`
- **test_newer_database_version_refuses_to_open()** (4 connections) — `tests/unit/test_sqlite_migrations.py`
- **_tool_run()** (4 connections) — `tests/unit/test_sqlite_migrations.py`
- **_user_version()** (4 connections) — `tests/unit/test_sqlite_migrations.py`
- **Connection** (1 connections)
- **Path** (1 connections)
- *... and 3 more nodes in this community*

## Relationships

- [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md) (8 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (3 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (2 shared connections)
- [角色卡编解码与导入](角色卡编解码与导入.md) (2 shared connections)
- [消息契约与会话编排](消息契约与会话编排.md) (2 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (2 shared connections)
- [角色卡库旧库升级测试](角色卡库旧库升级测试.md) (1 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (1 shared connections)
- [对话摘要与上下文投影](对话摘要与上下文投影.md) (1 shared connections)
- [SQLite 版本迁移](SQLite_版本迁移.md) (1 shared connections)

## Source Files

- `tests/fixtures/legacy_database.py`
- `tests/unit/test_sqlite_migrations.py`

## Audit Trail

- EXTRACTED: 86 (84%)
- INFERRED: 16 (16%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*