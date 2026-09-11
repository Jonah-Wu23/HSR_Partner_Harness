# storage: 打开数据库并完成迁移。 clock …

> 7 nodes · cohesion 0.29

## Key Concepts

- **.__init__()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._migrate()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._apply_migration()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **Path** (2 connections)
- **打开数据库并完成迁移。 clock 只用于批量刷盘的 50ms 判定（默认 time.monotonic）； 注入固定时钟后测试可以确定性地断言刷新时机。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **旧库版本化迁移：按 ``PRAGMA user_version`` 逐级升级。 schema.sql 用 CREATE TABLE IF NOT…** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **执行单条迁移语句；ALTER TABLE ADD/DROP COLUMN 按现状跳过。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`

## Relationships

- [存储增量缓冲与刷盘](存储增量缓冲与刷盘.md) (3 shared connections)
- [存储批量写入](存储批量写入.md) (1 shared connections)

## Source Files

- `src/pair_harness/storage/sqlite_store.py`

## Audit Trail

- EXTRACTED: 10 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*