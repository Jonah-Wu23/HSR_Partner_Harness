# Sidecar JSONL 协议路由

> 41 nodes · cohesion 0.10

## Key Concepts

- **ws_server.py** (23 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **router.py** (22 connections) — `src/pair_harness/desktop_backend/router.py`
- **DesktopCommand** (17 connections) — `src/pair_harness/desktop_backend/commands.py`
- **protocol.py** (16 connections) — `src/pair_harness/desktop_backend/protocol.py`
- **encode_message()** (16 connections) — `src/pair_harness/desktop_backend/protocol.py`
- **commands.py** (13 connections) — `src/pair_harness/desktop_backend/commands.py`
- **event_fanout.py** (12 connections) — `src/pair_harness/desktop_backend/event_fanout.py`
- **parse_request()** (9 connections) — `src/pair_harness/desktop_backend/protocol.py`
- **protocol_error()** (8 connections) — `src/pair_harness/desktop_backend/protocol.py`
- **ProtocolError** (8 connections) — `src/pair_harness/desktop_backend/protocol.py`
- **response_error()** (8 connections) — `src/pair_harness/desktop_backend/protocol.py`
- **response_ok()** (8 connections) — `src/pair_harness/desktop_backend/protocol.py`
- **.handle_line()** (8 connections) — `src/pair_harness/desktop_backend/router.py`
- **CommandValidationError** (7 connections) — `src/pair_harness/desktop_backend/commands.py`
- **._handle_frame()** (7 connections) — `src/pair_harness/desktop_backend/ws_server.py`
- **test_desktop_protocol.py** (7 connections) — `tests/unit/test_desktop_protocol.py`
- **test_desktop_router.py** (5 connections) — `tests/unit/test_desktop_router.py`
- **test_prompt_assembly_reports_why_no_module_was_assembled()** (5 connections) — `tests/unit/test_prompt_assembly.py`
- **.from_payload()** (4 connections) — `src/pair_harness/desktop_backend/commands.py`
- **Any** (4 connections)
- **test_bad_lines_are_structured_protocol_errors()** (4 connections) — `tests/unit/test_desktop_protocol.py`
- **test_parse_request_and_encode_jsonl()** (4 connections) — `tests/unit/test_desktop_protocol.py`
- **test_memory_commands_persist_and_broadcast()** (4 connections) — `tests/unit/test_summary_memory_commands.py`
- **.__init__()** (3 connections) — `src/pair_harness/desktop_backend/commands.py`
- **.__init__()** (3 connections) — `src/pair_harness/desktop_backend/protocol.py`
- *... and 16 more nodes in this community*

## Relationships

- [Sidecar 主循环与停机](Sidecar_主循环与停机.md) (11 shared connections)
- [语音设备抢占互斥](语音设备抢占互斥.md) (7 shared connections)
- [事件扇出与订阅](事件扇出与订阅.md) (7 shared connections)
- [pytest 夹具与事件记录](pytest_夹具与事件记录.md) (5 shared connections)
- [启动模式与局域网接入](启动模式与局域网接入.md) (5 shared connections)
- [角色卡提示词装配测试](角色卡提示词装配测试.md) (5 shared connections)
- [远端 WebSocket 连接管理](远端_WebSocket_连接管理.md) (5 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (4 shared connections)
- [角色卡管理命令处理](角色卡管理命令处理.md) (4 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (4 shared connections)
- [远程接入 WS 服务端](远程接入_WS_服务端.md) (4 shared connections)
- [手机端 ASR 会话测试](手机端_ASR_会话测试.md) (3 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/commands.py`
- `src/pair_harness/desktop_backend/event_fanout.py`
- `src/pair_harness/desktop_backend/protocol.py`
- `src/pair_harness/desktop_backend/router.py`
- `src/pair_harness/desktop_backend/ws_server.py`
- `tests/unit/test_desktop_protocol.py`
- `tests/unit/test_desktop_router.py`
- `tests/unit/test_prompt_assembly.py`
- `tests/unit/test_summary_memory_commands.py`

## Audit Trail

- EXTRACTED: 156 (92%)
- INFERRED: 14 (8%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*