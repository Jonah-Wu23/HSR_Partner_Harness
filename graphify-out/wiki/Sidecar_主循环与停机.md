# Sidecar 主循环与停机

> 34 nodes · cohesion 0.07

## Key Concepts

- **JsonlWriter** (25 connections) — `src/pair_harness/desktop_backend/router.py`
- **SidecarRouter** (21 connections) — `src/pair_harness/desktop_backend/router.py`
- **run_stdin()** (9 connections) — `src/pair_harness/desktop_backend/router.py`
- **test_ws_authenticated_identity_survives_reconnect()** (9 connections) — `tests/unit/test_voice_device_mutex.py`
- **_install_sigint_stop()** (8 connections) — `src/pair_harness/desktop_backend/__main__.py`
- **test_sigint_requests_orderly_stop()** (5 connections) — `tests/integration/test_serve_mode.py`
- **test_router_reports_unserializable_response_instead_of_timeout()** (5 connections) — `tests/unit/test_desktop_router.py`
- **.dispatch()** (4 connections) — `src/pair_harness/desktop_backend/router.py`
- **test_sidecar_router_accepts_cancel_while_chat_request_is_running()** (4 connections) — `tests/unit/test_desktop_router.py`
- **.write()** (3 connections) — `src/pair_harness/desktop_backend/router.py`
- **Any** (3 connections)
- **.__init__()** (3 connections) — `src/pair_harness/desktop_backend/router.py`
- **.__init__()** (2 connections) — `src/pair_harness/desktop_backend/event_fanout.py`
- **.__init__()** (2 connections) — `src/pair_harness/desktop_backend/router.py`
- **.request_stop()** (2 connections) — `src/pair_harness/desktop_backend/router.py`
- **TextIO** (2 connections)
- **remove_loop_handler()** (1 connections) — `src/pair_harness/desktop_backend/__main__.py`
- **request_stop()** (1 connections) — `src/pair_harness/desktop_backend/__main__.py`
- **restore_signal()** (1 connections) — `src/pair_harness/desktop_backend/__main__.py`
- **Ctrl+C 与 app.shutdown 同路径：转为有序停机请求，不硬打断事件循环。 事件循环原生信号处理（Unix）不可用时退回进程级同步…** (1 connections) — `src/pair_harness/desktop_backend/__main__.py`
- **.closed()** (1 connections) — `src/pair_harness/desktop_backend/router.py`
- **通知主循环退出（stdout 断开等传输级关闭路径）。** (1 connections) — `src/pair_harness/desktop_backend/router.py`
- **运行 Sidecar 主循环。 Windows 控制台 stdin 不是 asyncio 原生异步流，使用线程读取单行，…** (1 connections) — `src/pair_harness/desktop_backend/router.py`
- **stdout 协议写入器；每次写入都是一行完整 JSON。 整个 Sidecar 只允许创建一个实例，事件发射器与 Router 共用同一把锁。…** (1 connections) — `src/pair_harness/desktop_backend/router.py`
- **提交一条请求，不等待它完成，以便后续请求可以继续进入。 ``reply_sink`` 把 response 额外写回发起该请求的远程连接；stdout 始终…** (1 connections) — `src/pair_harness/desktop_backend/router.py`
- *... and 9 more nodes in this community*

## Relationships

- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (11 shared connections)
- [启动模式与局域网接入](启动模式与局域网接入.md) (9 shared connections)
- [事件扇出与订阅](事件扇出与订阅.md) (7 shared connections)
- [serve 模式与配对鉴权](serve_模式与配对鉴权.md) (5 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (3 shared connections)
- [语音设备抢占互斥](语音设备抢占互斥.md) (3 shared connections)
- [手机 PTT 语音往返测试](手机_PTT_语音往返测试.md) (1 shared connections)
- [手机端 TTS 中继测试](手机端_TTS_中继测试.md) (1 shared connections)
- [WebSocket 服务器测试](WebSocket_服务器测试.md) (1 shared connections)
- [角色卡管理命令处理](角色卡管理命令处理.md) (1 shared connections)
- [远程接入 WS 服务端](远程接入_WS_服务端.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/__main__.py`
- `src/pair_harness/desktop_backend/event_fanout.py`
- `src/pair_harness/desktop_backend/router.py`
- `tests/integration/test_serve_mode.py`
- `tests/unit/test_desktop_router.py`
- `tests/unit/test_voice_device_mutex.py`

## Audit Trail

- EXTRACTED: 53 (63%)
- INFERRED: 31 (37%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*