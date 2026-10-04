# serve 模式与配对鉴权

> 41 nodes · cohesion 0.10

## Key Concepts

- **test_serve_mode.py** (33 connections) — `tests/integration/test_serve_mode.py`
- **SidecarHarness** (13 connections) — `tests/integration/test_serve_mode.py`
- **test_serve_started_reports_address()** (11 connections) — `tests/integration/test_serve_mode.py`
- **_events()** (9 connections) — `tests/integration/test_serve_mode.py`
- **_stdio()** (9 connections) — `tests/integration/test_serve_mode.py`
- **_request()** (8 connections) — `tests/integration/test_serve_mode.py`
- **_responses()** (8 connections) — `tests/integration/test_serve_mode.py`
- **_run_args()** (8 connections) — `tests/integration/test_serve_mode.py`
- **.__init__()** (8 connections) — `tests/integration/test_serve_mode.py`
- **test_remote_submit_metric_records_origin_and_device()** (8 connections) — `tests/integration/test_serve_mode.py`
- **_recv_message()** (7 connections) — `tests/integration/test_serve_mode.py`
- **test_serve_port_conflict_degrades_to_stdin_only()** (7 connections) — `tests/integration/test_serve_mode.py`
- **test_undeclared_mode_without_key_reaches_onboarding()** (7 connections) — `tests/integration/test_serve_mode.py`
- **test_conflicting_mode_flags_fail_startup()** (6 connections) — `tests/integration/test_serve_mode.py`
- **test_explicit_demo_startup_uses_scripted_runtime()** (6 connections) — `tests/integration/test_serve_mode.py`
- **StringIO** (5 connections)
- **_messages()** (5 connections) — `tests/integration/test_serve_mode.py`
- **Any** (5 connections)
- **test_pairing_code_failure_budget_spans_connections()** (5 connections) — `tests/integration/test_serve_mode.py`
- **test_revoke_closes_established_connection()** (5 connections) — `tests/integration/test_serve_mode.py`
- **test_serve_mode_full_remote_path()** (5 connections) — `tests/integration/test_serve_mode.py`
- **_free_port()** (3 connections) — `tests/integration/test_serve_mode.py`
- **_isolate_from_dev_env()** (3 connections) — `tests/integration/test_serve_mode.py`
- **ClientWebSocketResponse** (2 connections)
- **metric()** (2 connections) — `tests/integration/test_serve_mode.py`
- *... and 16 more nodes in this community*

## Relationships

- [启动模式与局域网接入](启动模式与局域网接入.md) (12 shared connections)
- [Sidecar 主循环与停机](Sidecar_主循环与停机.md) (5 shared connections)
- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (3 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (3 shared connections)
- [角色卡绑定与命令测试](角色卡绑定与命令测试.md) (2 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (2 shared connections)
- [配对码与设备鉴权](配对码与设备鉴权.md) (2 shared connections)
- [事件扇出与订阅](事件扇出与订阅.md) (2 shared connections)
- [远程接入 WS 服务端](远程接入_WS_服务端.md) (2 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (1 shared connections)
- [pytest 夹具与事件记录](pytest_夹具与事件记录.md) (1 shared connections)
- [账号语音服务测试](账号语音服务测试.md) (1 shared connections)

## Source Files

- `tests/integration/test_serve_mode.py`

## Audit Trail

- EXTRACTED: 114 (95%)
- INFERRED: 6 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*