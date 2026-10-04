# SQLite 队列项持久化

> 17 nodes · cohesion 0.12

## Key Concepts

- **.get_queue_item()** (7 connections) — `src/pair_harness/storage/sqlite_store.py`
- **Row** (6 connections)
- **._account_dict()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **._queue_item_dict()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.enqueue_queue_item()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.edit_queue_item()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.list_queue_items()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.mark_queue_item_failed()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.withdraw_queue_item()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.get_account_by_username()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.list_accounts()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.peek_queue_item()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.set_queue_item_status()** (2 connections) — `src/pair_harness/storage/sqlite_store.py`
- **入队（先持久化，再向前端确认）。steer 置队首并重排其余 queued 项。 ``origin`` 与 ``remote_device_*``…** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **会话内按 position 升序的队列快照（含 withdrawn 历史）。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **撤回队列项（状态置 withdrawn，不再派发）。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **派发失败：状态置 failed 并保留原因，不再自动派发。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`

## Relationships

- [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md) (12 shared connections)
- [SQLite 项目与会话存储](SQLite_项目与会话存储.md) (3 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (1 shared connections)
- [回合指标记录与校验](回合指标记录与校验.md) (1 shared connections)
- [会话摘要 SQLite 存储](会话摘要_SQLite_存储.md) (1 shared connections)
- [PBKDF2 密码派生与校验](PBKDF2_密码派生与校验.md) (1 shared connections)

## Source Files

- `src/pair_harness/storage/sqlite_store.py`

## Audit Trail

- EXTRACTED: 35 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*