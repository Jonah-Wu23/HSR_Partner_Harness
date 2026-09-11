# WebSocket 服务测试

> 36 nodes · cohesion 0.14

## Key Concepts

- **test_ws_server.py** (28 connections) — `tests/unit/test_ws_server.py`
- **_start()** (22 connections) — `tests/unit/test_ws_server.py`
- **asyncio** (14 connections)
- **_recv_text()** (14 connections) — `tests/unit/test_ws_server.py`
- **_req()** (9 connections) — `tests/unit/test_ws_server.py`
- **_auth_ws()** (8 connections) — `tests/unit/test_ws_server.py`
- **Any** (8 connections)
- **FakeDispatch** (7 connections) — `tests/unit/test_ws_server.py`
- **test_events_fanout_and_continuity_after_client_disconnect()** (7 connections) — `tests/unit/test_ws_server.py`
- **test_authenticated_connection_cannot_switch_token()** (6 connections) — `tests/unit/test_ws_server.py`
- **test_disconnect_invokes_on_disconnect_with_connection_key()** (6 connections) — `tests/unit/test_ws_server.py`
- **test_ping_command_dispatched_after_auth()** (6 connections) — `tests/unit/test_ws_server.py`
- **test_authenticated_command_dispatched_and_response_back_on_same_connection()** (5 connections) — `tests/unit/test_ws_server.py`
- **test_remote_pair_passes_to_dispatch()** (5 connections) — `tests/unit/test_ws_server.py`
- **test_unauthenticated_command_rejected()** (5 connections) — `tests/unit/test_ws_server.py`
- **_free_port()** (4 connections) — `tests/unit/test_ws_server.py`
- **test_disconnect_unsubscribes_connection()** (4 connections) — `tests/unit/test_ws_server.py`
- **test_static_serves_index_and_file()** (4 connections) — `tests/unit/test_ws_server.py`
- **test_static_traversal_rejected()** (4 connections) — `tests/unit/test_ws_server.py`
- **_event()** (3 connections) — `tests/unit/test_ws_server.py`
- **.__call__()** (3 connections) — `tests/unit/test_ws_server.py`
- **._reply()** (3 connections) — `tests/unit/test_ws_server.py`
- **test_invalid_json_frame_returns_protocol_error()** (3 connections) — `tests/unit/test_ws_server.py`
- **test_no_static_root_returns_404()** (3 connections) — `tests/unit/test_ws_server.py`
- **test_non_object_frame_returns_protocol_error()** (3 connections) — `tests/unit/test_ws_server.py`
- *... and 11 more nodes in this community*

## Relationships

- [事件扇出](事件扇出.md) (6 shared connections)
- [PWA 静态资源路由](PWA_静态资源路由.md) (6 shared connections)
- [test_v038_t2_device_mutex.py: test_v038_t2_devic…](test_v038_t2_device_mutex.py-_test_v038_t2_devic….md) (4 shared connections)
- [边车协议解析](边车协议解析.md) (1 shared connections)

## Source Files

- `tests/unit/test_ws_server.py`

## Audit Trail

- EXTRACTED: 106 (99%)
- INFERRED: 1 (1%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*