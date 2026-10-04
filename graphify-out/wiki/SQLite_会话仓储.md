# SQLite 会话仓储

> 7 nodes · cohesion 0.43

## Key Concepts

- **Conversation** (18 connections) — `src/pair_harness/core/repository.py`
- **.get_conversation()** (7 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.create_conversation()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.find_active_conversation()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **.list_conversations()** (4 connections) — `src/pair_harness/storage/sqlite_store.py`
- **列出项目下的会话；``account_id`` 给定时按账号过滤。 账号是完整隔离边界：即使会话挂到了不属于当前账号的项目， 带账号过滤的列表也不会泄露。** (1 connections) — `src/pair_harness/storage/sqlite_store.py`
- **按项目、角色卡与搭档找最新的未归档会话。 conversation.create 的 ``reuse_active`` 复用键；只匹配 archived=0…** (1 connections) — `src/pair_harness/storage/sqlite_store.py`

## Relationships

- [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md) (5 shared connections)
- [会话身份与记忆命令](会话身份与记忆命令.md) (3 shared connections)
- [对话摘要与上下文投影](对话摘要与上下文投影.md) (3 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (2 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (2 shared connections)
- [账号与对话生命周期](账号与对话生命周期.md) (2 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (1 shared connections)
- [测试替身与集成夹具](测试替身与集成夹具.md) (1 shared connections)
- [SQLite 项目与会话存储](SQLite_项目与会话存储.md) (1 shared connections)
- [会话摘要 SQLite 存储](会话摘要_SQLite_存储.md) (1 shared connections)

## Source Files

- `src/pair_harness/core/repository.py`
- `src/pair_harness/storage/sqlite_store.py`

## Audit Trail

- EXTRACTED: 27 (90%)
- INFERRED: 3 (10%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*