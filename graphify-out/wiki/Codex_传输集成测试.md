# Codex 传输集成测试

> 42 nodes · cohesion 0.09

## Key Concepts

- **QueueJsonLineConnection** (36 connections) — `tests/fixtures/fake_codex_app_server.py`
- **test_codex_transport.py** (25 connections) — `tests/integration/test_codex_transport.py`
- **test_codex_dialogue_cancel_interrupts_engine_and_cleans_session()** (14 connections) — `tests/integration/test_codex_transport.py`
- **asyncio** (12 connections)
- **test_offline_engine_opens_session_and_streams_mapped_events()** (11 connections) — `tests/integration/test_codex_transport.py`
- **test_run_turn_idle_timeout_requests_interrupt_then_fails()** (11 connections) — `tests/integration/test_codex_transport.py`
- **factory()** (11 connections) — `tests/integration/test_codex_transport.py`
- **test_open_session_sends_initialize_handshake_before_thread_start()** (10 connections) — `tests/integration/test_codex_transport.py`
- **test_cancel_turn_sends_interrupt_with_thread_and_turn_ids()** (9 connections) — `tests/integration/test_codex_transport.py`
- **test_engine_repeats_initialize_after_transport_reconnect()** (9 connections) — `tests/integration/test_codex_transport.py`
- **test_server_initiated_request_goes_to_notification_queue()** (8 connections) — `tests/integration/test_codex_transport.py`
- **test_transport_preserves_process_exit_diagnostics()** (8 connections) — `tests/integration/test_codex_transport.py`
- **test_old_reader_exception_does_not_poison_new_notification_queue()** (7 connections) — `tests/integration/test_codex_transport.py`
- **test_transport_normalizes_connection_reset_and_releases_connection()** (7 connections) — `tests/integration/test_codex_transport.py`
- **test_transport_correlates_requests_with_single_reader()** (6 connections) — `tests/integration/test_codex_transport.py`
- **ExitedConnection** (4 connections) — `tests/integration/test_codex_transport.py`
- **ResetOnWriteConnection** (4 connections) — `tests/integration/test_codex_transport.py`
- **.__init__()** (2 connections) — `tests/fixtures/fake_codex_app_server.py`
- **factory()** (2 connections) — `tests/integration/test_codex_transport.py`
- **.close()** (1 connections) — `tests/fixtures/fake_codex_app_server.py`
- **.__init__()** (1 connections) — `tests/fixtures/fake_codex_app_server.py`
- **.read_line()** (1 connections) — `tests/fixtures/fake_codex_app_server.py`
- **.write_line()** (1 connections) — `tests/fixtures/fake_codex_app_server.py`
- **.exit_description()** (1 connections) — `tests/integration/test_codex_transport.py`
- **app-server EOF 要保留退出码/启动 stderr，而不是只报泛化 EOF。** (1 connections) — `tests/integration/test_codex_transport.py`
- *... and 17 more nodes in this community*

## Relationships

- [Codex 审批流集成测试](Codex_审批流集成测试.md) (20 shared connections)
- [JSONL 子进程传输](JSONL_子进程传输.md) (15 shared connections)
- [Codex app-server 引擎](Codex_app-server_引擎.md) (8 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (5 shared connections)
- [test_codex_transport.py: EofConnection](test_codex_transport.py-_EofConnection.md) (3 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (3 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (3 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (3 shared connections)
- [test_codex_transport_robustness.py: test_codex_transpo…](test_codex_transport_robustness.py-_test_codex_transpo….md) (2 shared connections)
- [委派与契约模型](委派与契约模型.md) (2 shared connections)
- [fake_codex_app_server.py: .notify()](fake_codex_app_server.py-_.notify.md) (2 shared connections)
- [test_v032_baselines.py: _jsonl()](test_v032_baselines.py-__jsonl.md) (1 shared connections)

## Source Files

- `tests/fixtures/fake_codex_app_server.py`
- `tests/integration/test_codex_transport.py`

## Audit Trail

- EXTRACTED: 90 (63%)
- INFERRED: 53 (37%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*