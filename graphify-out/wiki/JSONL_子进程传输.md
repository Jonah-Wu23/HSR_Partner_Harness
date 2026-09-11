# JSONL 子进程传输

> 39 nodes · cohesion 0.09

## Key Concepts

- **JsonlProcessTransport** (46 connections) — `src/pair_harness/adapters/codex/transport.py`
- **transport.py** (16 connections) — `src/pair_harness/adapters/codex/transport.py`
- **TransportClosed** (10 connections) — `src/pair_harness/adapters/codex/transport.py`
- **Any** (9 connections)
- **SessionSubscription** (8 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._close_connection()** (7 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._read_loop()** (7 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.request()** (7 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._write_message()** (6 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._broadcast_failure_to_subscriptions()** (5 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._route_session_message()** (5 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.start()** (5 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.notify()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.respond()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.subscribe_session()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **_session_route_key()** (4 connections) — `src/pair_harness/adapters/codex/transport.py`
- **RuntimeError** (3 connections)
- **._deliver()** (3 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.next()** (3 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.close()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.__init__()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.next_notification()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **._release_subscription()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **.stderr_tail()** (2 connections) — `src/pair_harness/adapters/codex/transport.py`
- **BaseException** (2 connections)
- *... and 14 more nodes in this community*

## Relationships

- [Codex 传输集成测试](Codex_传输集成测试.md) (15 shared connections)
- [Codex app-server 引擎](Codex_app-server_引擎.md) (5 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (4 shared connections)
- [子进程启动与终止](子进程启动与终止.md) (4 shared connections)
- [desktop_backend: DiagnosticCallback](desktop_backend-_DiagnosticCallback.md) (3 shared connections)
- [Codex 审批流集成测试](Codex_审批流集成测试.md) (3 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (2 shared connections)
- [test_codex_transport_robustness.py: test_codex_transpo…](test_codex_transport_robustness.py-_test_codex_transpo….md) (2 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [ACP 引擎测试](ACP_引擎测试.md) (1 shared connections)
- [委派与契约模型](委派与契约模型.md) (1 shared connections)
- [adapters: JsonLineConnection](adapters-_JsonLineConnection.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/codex/transport.py`
- `tests/integration/test_codex_transport.py`

## Audit Trail

- EXTRACTED: 92 (80%)
- INFERRED: 23 (20%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*