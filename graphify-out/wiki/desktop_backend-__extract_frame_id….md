# desktop_backend: _extract_frame_id(…

> 19 nodes · cohesion 0.14

## Key Concepts

- **_RemoteConnection** (12 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._handle_frame()** (6 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._writer_loop()** (5 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._handle_ws()** (5 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **_extract_frame_id()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.__init__()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **._teardown()** (4 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.detach()** (3 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **Any** (2 connections)
- **.close()** (2 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.send()** (2 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **Request** (1 connections)
- **从已解析的帧里提取请求 id；解析失败或非对象时返回 None。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **管理一条远端 WS 连接：上行队列 + 扇出订阅 + 下行写任务。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **消费下行队列并把每个 envelope 编码成 WS 文本帧下发。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **同步入队（作为 dispatch reply_sink 与 fanout 订阅写回调共用）。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **同步退订并停写（幂等）：撤销联动时立即切断事件下发。** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **.subscribe()** (1 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **WebSocketResponse** (1 connections)

## Relationships

- [PWA 静态资源路由](PWA_静态资源路由.md) (4 shared connections)
- [事件扇出](事件扇出.md) (2 shared connections)
- [边车协议解析](边车协议解析.md) (2 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/ws_server.py`

## Audit Trail

- EXTRACTED: 32 (97%)
- INFERRED: 1 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*