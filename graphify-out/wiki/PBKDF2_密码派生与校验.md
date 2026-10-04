# PBKDF2 密码派生与校验

> 9 nodes · cohesion 0.28

## Key Concepts

- **.create_account()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._derive_password()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.get_account()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.change_password()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._new_salt()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.update_last_login()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.verify_password()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.update_account_profile()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- **PBKDF2-SHA256 派生（200k 迭代），与 salt 一起存库。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`

## Relationships

- [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md) (8 shared connections)
- [SQLite 项目与会话存储](SQLite_项目与会话存储.md) (2 shared connections)
- [SQLite 队列项持久化](SQLite_队列项持久化.md) (1 shared connections)

## Source Files

- `src/pair_harness/storage/sqlite_store.py`

## Audit Trail

- EXTRACTED: 21 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*