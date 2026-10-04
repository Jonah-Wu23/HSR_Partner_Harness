# DashScope 模拟服务端

> 17 nodes · cohesion 0.13

## Key Concepts

- **DashScopeServer** (11 connections) — `tests/fixtures/dashscope_ws.py`
- **dashscope_ws.py** (6 connections) — `tests/fixtures/dashscope_ws.py`
- **dashscope_server()** (4 connections) — `tests/fixtures/dashscope_ws.py`
- **._build_app()** (3 connections) — `tests/fixtures/dashscope_ws.py`
- **_sync_download()** (2 connections) — `src/pair_harness/desktop_backend/tunnel.py`
- **.__init__()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **.reject_handshake()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **.serve()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **.url()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **Script** (1 connections)
- **.close()** (1 connections) — `tests/fixtures/dashscope_ws.py`
- **.start()** (1 connections) — `tests/fixtures/dashscope_ws.py`
- **Application** (1 connections)
- **fixture** (1 connections)
- **MonkeyPatch** (1 connections)
- **127.0.0.1 上的推理端点；每条连接按到达顺序取用一个已登记的脚本。** (1 connections) — `tests/fixtures/dashscope_ws.py`
- **下一次 WebSocket 握手直接返回该 HTTP 状态（例如 Key 无效的 401）。** (1 connections) — `tests/fixtures/dashscope_ws.py`

## Relationships

- [DashScope 任务脚本](DashScope_任务脚本.md) (2 shared connections)
- [隧道进程与事件出口](隧道进程与事件出口.md) (1 shared connections)
- [手机端 ASR 会话测试](手机端_ASR_会话测试.md) (1 shared connections)
- [手机端 TTS 中继测试](手机端_TTS_中继测试.md) (1 shared connections)
- [千问事件映射测试](千问事件映射测试.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/tunnel.py`
- `tests/fixtures/dashscope_ws.py`

## Audit Trail

- EXTRACTED: 22 (92%)
- INFERRED: 2 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*