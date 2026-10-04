# 远端 WebSocket 连接管理

> 14 nodes · cohesion 0.20

## Key Concepts

- **_RemoteConnection** (13 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._handle_ws()** (5 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.__init__()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._teardown()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._writer_loop()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.close()** (3 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.detach()** (3 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **WebSocketResponse** (2 connections)
- **.send()** (2 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **Request** (1 connections)
- **同步退订并停写（幂等），撤销时立即切断事件下发。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **一条远端 WS 连接：下行队列、事件扇出订阅与写任务。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **同步入队，供 dispatch 回写与事件扇出共用。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.subscribe()** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`

## Relationships

- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (5 shared connections)
- [远程接入 WS 服务端](远程接入_WS_服务端.md) (2 shared connections)
- [事件扇出与订阅](事件扇出与订阅.md) (2 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/ws_server.py`

## Audit Trail

- EXTRACTED: 26 (96%)
- INFERRED: 1 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*