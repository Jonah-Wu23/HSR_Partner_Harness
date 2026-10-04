# JSONL JSON-RPC 传输

> 31 nodes · cohesion 0.11

## Key Concepts

- **JsonlProcessTransport** (24 connections) — `src/pair_harness/adapters/codex/transport.py`
- **Any** (10 connections)
- **SessionSubscription** (9 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._read_loop()** (7 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._write_message()** (7 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._close_connection()** (6 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._route_session_message()** (5 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._broadcast_failure_to_subscriptions()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.notify()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.request()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.respond()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.start()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._deliver()** (3 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.next_nowait()** (3 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.close()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.generation()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._release_subscription()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.stderr_tail()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **BaseException** (2 connections)
- **.next()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.is_running()** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **单个 ACP session 的消息订阅器。 读循环按 stdout 顺序把消息同步放进队列；transport 断开时所有订阅器收到…** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **取出已到达的下一条消息；队列为空时抛 asyncio.QueueEmpty。** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **单读循环的 JSONL JSON-RPC 传输，按 id 关联请求与响应，按 sessionId 投递会话消息。** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **连接代次，每次建立新连接后递增，引擎据此判断是否需要重新 initialize。** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- *... and 6 more nodes in this community*

## Relationships

- [JSONL 连接协议抽象](JSONL_连接协议抽象.md) (10 shared connections)
- [JSONL 传输测试夹具](JSONL_传输测试夹具.md) (5 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (1 shared connections)
- [Reasonix 环境装配](Reasonix_环境装配.md) (1 shared connections)
- [Reasonix ACP 假进程](Reasonix_ACP_假进程.md) (1 shared connections)
- [ACP 回合生命周期测试](ACP_回合生命周期测试.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/codex/transport.py`

## Audit Trail

- EXTRACTED: 66 (97%)
- INFERRED: 2 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*