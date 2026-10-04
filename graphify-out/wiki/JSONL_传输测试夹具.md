# JSONL 传输测试夹具

> 30 nodes · cohesion 0.14

## Key Concepts

- **QueueJsonLineConnection** (27 connections) — `tests/fixtures/jsonl_connection.py`
- **test_jsonl_transport.py** (17 connections) — `tests/integration/test_jsonl_transport.py`
- **TransportClosed** (12 connections) — `src/pair_harness/adapters/codex/transport.py`
- **make_transport()** (11 connections) — `tests/integration/test_jsonl_transport.py`
- **asyncio** (9 connections)
- **test_reconnect_does_not_deliver_stale_reader_failure()** (8 connections) — `tests/integration/test_jsonl_transport.py`
- **ResetOnWriteConnection** (6 connections) — `tests/integration/test_jsonl_transport.py`
- **test_session_notifications_route_by_session_id()** (6 connections) — `tests/integration/test_jsonl_transport.py`
- **test_eof_fails_pending_request_with_exit_diagnostics()** (5 connections) — `tests/integration/test_jsonl_transport.py`
- **test_request_without_response_times_out()** (5 connections) — `tests/integration/test_jsonl_transport.py`
- **test_unparseable_line_fails_all_pending_requests()** (5 connections) — `tests/integration/test_jsonl_transport.py`
- **test_write_failure_closes_connection()** (5 connections) — `tests/integration/test_jsonl_transport.py`
- **test_server_request_reaches_session_subscriber_and_gets_reply()** (4 connections) — `tests/integration/test_jsonl_transport.py`
- **test_transport_correlates_responses_by_id()** (4 connections) — `tests/integration/test_jsonl_transport.py`
- **jsonl_connection.py** (3 connections) — `tests/fixtures/jsonl_connection.py`
- **agent_message_chunk()** (2 connections) — `tests/integration/test_jsonl_transport.py`
- **factory()** (2 connections) — `tests/integration/test_jsonl_transport.py`
- **.write_line()** (2 connections) — `tests/integration/test_jsonl_transport.py`
- **factory()** (2 connections) — `tests/integration/test_jsonl_transport.py`
- **.close()** (1 connections) — `tests/fixtures/jsonl_connection.py`
- **.exit_description()** (1 connections) — `tests/fixtures/jsonl_connection.py`
- **.__init__()** (1 connections) — `tests/fixtures/jsonl_connection.py`
- **.read_line()** (1 connections) — `tests/fixtures/jsonl_connection.py`
- **.stderr_tail()** (1 connections) — `tests/fixtures/jsonl_connection.py`
- **.write_line()** (1 connections) — `tests/fixtures/jsonl_connection.py`
- *... and 5 more nodes in this community*

## Relationships

- [JSONL JSON-RPC 传输](JSONL_JSON-RPC_传输.md) (5 shared connections)
- [Reasonix ACP 假进程](Reasonix_ACP_假进程.md) (5 shared connections)
- [JSONL 连接协议抽象](JSONL_连接协议抽象.md) (4 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (2 shared connections)
- [ACP 回合生命周期测试](ACP_回合生命周期测试.md) (2 shared connections)
- [JSON-RPC 行连接夹具](JSON-RPC_行连接夹具.md) (2 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (2 shared connections)
- [子进程传输与进程回收](子进程传输与进程回收.md) (1 shared connections)
- [pytest 夹具与事件记录](pytest_夹具与事件记录.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/codex/transport.py`
- `tests/fixtures/jsonl_connection.py`
- `tests/integration/test_jsonl_transport.py`

## Audit Trail

- EXTRACTED: 75 (88%)
- INFERRED: 10 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*