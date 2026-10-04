# SQLite 项目与会话存储

> 36 nodes · cohesion 0.08

## Key Concepts

- **_now()** (17 connections) — `src/pair_harness/storage/sqlite_store.py`
- **Project** (12 connections) — `src/pair_harness/core/repository.py`
- **._update_existing()** (10 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.get_project()** (7 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._update_project_column()** (7 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._project_from_row()** (6 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.find_project_by_root_path()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.mark_project_opened()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.save_message()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.save_tool_run()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.unarchive_project()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.create_project()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.list_projects()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.rename_conversation()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._touch_conversation()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.update_conversation_mode()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.archive_conversation()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.list_projects_for_account()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.save_engine_session()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.set_auto_title()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._write_tool_run_row()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.archive_project()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.set_onboarding_complete()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.update_project_approval_mode()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.update_project_name()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- *... and 11 more nodes in this community*

## Relationships

- [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md) (26 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (5 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (4 shared connections)
- [SQLite 队列项持久化](SQLite_队列项持久化.md) (3 shared connections)
- [PBKDF2 密码派生与校验](PBKDF2_密码派生与校验.md) (2 shared connections)
- [SQLite 会话仓储](SQLite_会话仓储.md) (1 shared connections)
- [SQLite 版本迁移](SQLite_版本迁移.md) (1 shared connections)
- [对话摘要与上下文投影](对话摘要与上下文投影.md) (1 shared connections)
- [消息契约与会话编排](消息契约与会话编排.md) (1 shared connections)

## Source Files

- `src/pair_harness/core/repository.py`
- `src/pair_harness/storage/sqlite_store.py`

## Audit Trail

- EXTRACTED: 91 (99%)
- INFERRED: 1 (1%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*