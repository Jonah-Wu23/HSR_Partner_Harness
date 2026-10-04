# SQLite 版本迁移

> 7 nodes · cohesion 0.29

## Key Concepts

- **.__init__()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **DatabaseVersionError** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._migrate()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **Path** (2 connections)
- **RuntimeError** (1 connections)
- **打开数据库：新库按 schema.sql 建表，已有库按 user_version 逐级迁移。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **从 version 逐级执行 MIGRATIONS，每完成一级立即写入对应 user_version。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`

## Relationships

- [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md) (2 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (1 shared connections)
- [SQLite 迁移测试](SQLite_迁移测试.md) (1 shared connections)
- [SQLite 项目与会话存储](SQLite_项目与会话存储.md) (1 shared connections)

## Source Files

- `src/pair_harness/storage/sqlite_store.py`

## Audit Trail

- EXTRACTED: 10 (91%)
- INFERRED: 1 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*