# DashScope 任务脚本

> 22 nodes · cohesion 0.13

## Key Concepts

- **DashScopeTask** (32 connections) — `tests/fixtures/dashscope_ws.py`
- **._send()** (6 connections) — `tests/fixtures/dashscope_ws.py`
- **.receive()** (5 connections) — `tests/fixtures/dashscope_ws.py`
- **._handle()** (4 connections) — `tests/fixtures/dashscope_ws.py`
- **.expect()** (4 connections) — `tests/fixtures/dashscope_ws.py`
- **.__init__()** (3 connections) — `tests/fixtures/dashscope_ws.py`
- **.sentence()** (3 connections) — `tests/fixtures/dashscope_ws.py`
- **Any** (3 connections)
- **.failed()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **.finish_directives()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **.finished()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **.next_audio()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **.started()** (2 connections) — `tests/fixtures/dashscope_ws.py`
- **Request** (2 connections)
- **.audio_out()** (1 connections) — `tests/fixtures/dashscope_ws.py`
- **StreamResponse** (1 connections)
- **WebSocketResponse** (1 connections)
- **一条推理连接的服务端：记录客户端发来的指令与音频，按脚本回放服务端事件。** (1 connections) — `tests/fixtures/dashscope_ws.py`
- **每条 finish-task 的 payload.input.directive（取消合成时为 cancel）。** (1 connections) — `tests/fixtures/dashscope_ws.py`
- **读取客户端下一条消息；二进制帧是音频，文本帧是 JSON 指令。** (1 connections) — `tests/fixtures/dashscope_ws.py`
- **读到下一条 JSON 指令并校验 action，其间的音频帧照常记录。** (1 connections) — `tests/fixtures/dashscope_ws.py`
- **识别结果：同一 begin_time 的后续结果是同一句的更新。** (1 connections) — `tests/fixtures/dashscope_ws.py`

## Relationships

- [手机端 TTS 中继测试](手机端_TTS_中继测试.md) (5 shared connections)
- [千问事件映射测试](千问事件映射测试.md) (5 shared connections)
- [千问识别事件映射测试](千问识别事件映射测试.md) (4 shared connections)
- [DashScope 模拟服务端](DashScope_模拟服务端.md) (2 shared connections)
- [手机端 ASR 会话测试](手机端_ASR_会话测试.md) (1 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (1 shared connections)
- [手机 PTT 语音往返测试](手机_PTT_语音往返测试.md) (1 shared connections)
- [千问流式 ASR 识别器](千问流式_ASR_识别器.md) (1 shared connections)

## Source Files

- `tests/fixtures/dashscope_ws.py`

## Audit Trail

- EXTRACTED: 35 (70%)
- INFERRED: 15 (30%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*