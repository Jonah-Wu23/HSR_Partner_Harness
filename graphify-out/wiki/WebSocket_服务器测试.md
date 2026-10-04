# WebSocket 服务器测试

> 38 nodes · cohesion 0.12

## Key Concepts

- **test_ws_server.py** (25 connections) — `tests/unit/test_ws_server.py`
- **_start()** (22 connections) — `tests/unit/test_ws_server.py`
- **_recv_text()** (13 connections) — `tests/unit/test_ws_server.py`
- **_auth_ws()** (10 connections) — `tests/unit/test_ws_server.py`
- **_req()** (9 connections) — `tests/unit/test_ws_server.py`
- **Harness** (8 connections) — `tests/unit/test_ws_server.py`
- **Any** (7 connections)
- **test_token_failure_on_authenticated_connection_unsubscribes_and_closes()** (7 connections) — `tests/unit/test_ws_server.py`
- **EchoDispatch** (6 connections) — `tests/unit/test_ws_server.py`
- **.__init__()** (6 connections) — `tests/unit/test_ws_server.py`
- **test_events_fanout_and_continuity_after_client_disconnect()** (6 connections) — `tests/unit/test_ws_server.py`
- **_Clock** (5 connections) — `tests/unit/test_ws_server.py`
- **test_authenticated_command_dispatched_with_transport_identity()** (5 connections) — `tests/unit/test_ws_server.py`
- **test_command_without_token_rejected()** (5 connections) — `tests/unit/test_ws_server.py`
- **test_authenticated_connection_cannot_switch_token()** (4 connections) — `tests/unit/test_ws_server.py`
- **test_control_plane_method_rejected_with_forbidden_scope()** (4 connections) — `tests/unit/test_ws_server.py`
- **test_disconnect_unsubscribes_and_reports_connection_key()** (4 connections) — `tests/unit/test_ws_server.py`
- **test_malformed_frame_returns_protocol_error()** (4 connections) — `tests/unit/test_ws_server.py`
- **test_remote_pair_passes_to_dispatch_without_token()** (4 connections) — `tests/unit/test_ws_server.py`
- **_event()** (3 connections) — `tests/unit/test_ws_server.py`
- **parametrize** (3 connections)
- **test_static_serves_index_and_file()** (3 connections) — `tests/unit/test_ws_server.py`
- **test_static_traversal_rejected()** (3 connections) — `tests/unit/test_ws_server.py`
- **.__call__()** (2 connections) — `tests/unit/test_ws_server.py`
- **_free_port()** (2 connections) — `tests/unit/test_ws_server.py`
- *... and 13 more nodes in this community*

## Relationships

- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (3 shared connections)
- [远程接入 WS 服务端](远程接入_WS_服务端.md) (3 shared connections)
- [事件扇出与订阅](事件扇出与订阅.md) (3 shared connections)
- [配对服务与令牌快照](配对服务与令牌快照.md) (3 shared connections)
- [配对码与设备鉴权](配对码与设备鉴权.md) (2 shared connections)
- [Sidecar 主循环与停机](Sidecar_主循环与停机.md) (1 shared connections)

## Source Files

- `tests/unit/test_ws_server.py`

## Audit Trail

- EXTRACTED: 96 (96%)
- INFERRED: 4 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*