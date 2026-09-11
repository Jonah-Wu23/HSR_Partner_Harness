# PWA 静态资源路由

> 30 nodes · cohesion 0.09

## Key Concepts

- **WSServerMode** (19 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **ws_server.py** (18 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **add_static_routes()** (8 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **StubAuthenticator** (8 connections) — `tests/unit/test_ws_server.py`
- **AuthDecision** (7 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **_not_found()** (5 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **RemoteAuthenticator** (5 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._build_app()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.__init__()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **pwa_static.py** (3 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **test_ws_response_configures_heartbeat()** (3 connections) — `tests/unit/test_ws_server.py`
- **index()** (2 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **.authorize()** (2 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.close_connections_for_token()** (2 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.start()** (2 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.authorize()** (2 connections) — `tests/unit/test_ws_server.py`
- **Response** (1 connections)
- **Application** (1 connections)
- **Path** (1 connections)
- **Request** (1 connections)
- **装配 PWA 静态路由。 - static_root 为 None 时，GET / 及任意静态路径统一返回 404，如实报错、不合成页面； -…** (1 connections) — `src/pair_harness/desktop_backend/pwa_static.py`
- **Application** (1 connections)
- **Path** (1 connections)
- **Protocol** (1 connections)
- **WS 服务器模式：同一 aiohttp 应用承载 PWA 静态路由与 GET /ws 升级。 构造参数冻结；dispatch 由批 3 主控接到…** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- *... and 5 more nodes in this community*

## Relationships

- [事件扇出](事件扇出.md) (7 shared connections)
- [WebSocket 服务测试](WebSocket_服务测试.md) (6 shared connections)
- [desktop_backend: _extract_frame_id(…](desktop_backend-__extract_frame_id….md) (4 shared connections)
- [边车协议解析](边车协议解析.md) (3 shared connections)
- [边车入口与信号处理](边车入口与信号处理.md) (3 shared connections)
- [desktop_backend: pairing.py](desktop_backend-_pairing.py.md) (3 shared connections)
- [服务模式集成测试](服务模式集成测试.md) (3 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (1 shared connections)
- [test_pairing.py: test_pairing.py](test_pairing.py-_test_pairing.py.md) (1 shared connections)
- [desktop_backend: ._audit_log()](desktop_backend-_._audit_log.md) (1 shared connections)
- [配对与鉴权服务](配对与鉴权服务.md) (1 shared connections)
- [test_v038_t2_device_mutex.py: test_v038_t2_devic…](test_v038_t2_device_mutex.py-_test_v038_t2_devic….md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/pwa_static.py`
- `src/pair_harness/desktop_backend/ws_server.py`
- `tests/unit/test_ws_server.py`

## Audit Trail

- EXTRACTED: 62 (87%)
- INFERRED: 9 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*