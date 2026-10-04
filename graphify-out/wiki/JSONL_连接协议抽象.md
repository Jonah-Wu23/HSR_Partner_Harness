# JSONL 连接协议抽象

> 20 nodes · cohesion 0.11

## Key Concepts

- **transport.py** (12 connections) — `src/pair_harness/adapters/codex/transport.py`
- **JsonLineConnection** (7 connections) — `src/pair_harness/adapters/codex/transport.py`
- **JsonRpcError** (7 connections) — `src/pair_harness/adapters/codex/transport.py`
- **JsonlProtocolError** (5 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.subscribe_session()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **RuntimeError** (4 connections)
- **_session_route_key()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.__init__()** (3 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.__init__()** (3 connections) — `src/pair_harness/adapters/codex/transport.py`
- **ConnectionFactory** (1 connections)
- **.close()** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.exit_description()** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.read_line()** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.stderr_tail()** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.write_line()** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **Protocol** (1 connections)
- **ACP 会话消息（session/update、session/request_permission 等）的 sessionId。** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **服务端对请求返回的 JSON-RPC error 对象，保留 code、message、data 原值。** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **订阅指定 ACP session 的消息；同一 session 重复订阅是路由缺陷，直接抛错。** (1 connections) — `src/pair_harness/adapters/codex/transport.py`
- **子进程输出了无法解析的 JSONL 行，连接上的协议状态不再可信。** (1 connections) — `src/pair_harness/adapters/codex/transport.py`

## Relationships

- [JSONL JSON-RPC 传输](JSONL_JSON-RPC_传输.md) (10 shared connections)
- [JSONL 传输测试夹具](JSONL_传输测试夹具.md) (4 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (3 shared connections)
- [Reasonix 环境装配](Reasonix_环境装配.md) (1 shared connections)
- [ACP 回合生命周期测试](ACP_回合生命周期测试.md) (1 shared connections)
- [子进程传输与进程回收](子进程传输与进程回收.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/codex/transport.py`

## Audit Trail

- EXTRACTED: 38 (95%)
- INFERRED: 2 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*