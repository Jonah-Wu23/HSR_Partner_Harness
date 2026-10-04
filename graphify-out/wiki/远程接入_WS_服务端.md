# 远程接入 WS 服务端

> 15 nodes · cohesion 0.15

## Key Concepts

- **WSServerMode** (20 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._disconnect_unauthorized()** (5 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **RemoteAuthenticator** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._build_app()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.__init__()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.close_connections_for_device()** (3 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.authorize()** (2 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.start()** (2 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **Application** (1 connections)
- **Path** (1 connections)
- **Protocol** (1 connections)
- **同一 aiohttp 应用承载 PWA 静态路由与 GET /ws 升级。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **断开以该令牌键鉴权的已建立连接，返回断开数。必须在事件循环线程内调用。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **令牌失效的连接：同步退订（事件扇出立即停止），再调度 4401 关闭。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.stop()** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`

## Relationships

- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (4 shared connections)
- [启动模式与局域网接入](启动模式与局域网接入.md) (3 shared connections)
- [WebSocket 服务器测试](WebSocket_服务器测试.md) (3 shared connections)
- [serve 模式与配对鉴权](serve_模式与配对鉴权.md) (2 shared connections)
- [远端 WebSocket 连接管理](远端_WebSocket_连接管理.md) (2 shared connections)
- [事件扇出与订阅](事件扇出与订阅.md) (2 shared connections)
- [配对码与设备鉴权](配对码与设备鉴权.md) (1 shared connections)
- [Sidecar 主循环与停机](Sidecar_主循环与停机.md) (1 shared connections)
- [PWA 静态资源路由](PWA_静态资源路由.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/ws_server.py`

## Audit Trail

- EXTRACTED: 30 (86%)
- INFERRED: 5 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*