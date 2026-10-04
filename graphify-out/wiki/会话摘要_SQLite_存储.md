# 会话摘要 SQLite 存储

> 13 nodes · cohesion 0.21

## Key Concepts

- **ConversationSummary** (26 connections) — `src/pair_harness/storage/records.py`
- **._summary_from_row()** (9 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.latest_completed_summary()** (5 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.list_summaries()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.load_conversation()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.upsert_summary()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.get_summary()** (3 connections) — `src/pair_harness/storage/sqlite_store.py`
- **summary()** (2 connections) — `tests/unit/test_sqlite_store.py`
- **聊天级摘要。 covers_* 描述连续、已最终落库的消息区间；content 是模型产出的结构化 摘要原文。失败保留原始错误。** (1 connections) — `src/pair_harness/storage/records.py`
- **ConversationSummary** (1 connections)
- **写入或更新一条摘要（按会话 + 覆盖区间幂等）。 区间已存在时保留原 summary_id 与 created_at，只更新内容与状态；…** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **列出该聊天的摘要，按覆盖区间起点消息的时间排序。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **覆盖终点最新的 completed 摘要（按覆盖终点消息的时间取）。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`

## Relationships

- [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md) (12 shared connections)
- [对话摘要与上下文投影](对话摘要与上下文投影.md) (4 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (4 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (2 shared connections)
- [回合指标记录与校验](回合指标记录与校验.md) (2 shared connections)
- [角色卡管理命令处理](角色卡管理命令处理.md) (1 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (1 shared connections)
- [角色卡提示词装配测试](角色卡提示词装配测试.md) (1 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (1 shared connections)
- [SQLite 会话仓储](SQLite_会话仓储.md) (1 shared connections)
- [SQLite 队列项持久化](SQLite_队列项持久化.md) (1 shared connections)

## Source Files

- `src/pair_harness/storage/records.py`
- `src/pair_harness/storage/sqlite_store.py`
- `tests/unit/test_sqlite_store.py`

## Audit Trail

- EXTRACTED: 37 (80%)
- INFERRED: 9 (20%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*