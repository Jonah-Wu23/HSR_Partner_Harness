# ACP 事件映射编解码

> 26 nodes · cohesion 0.13

## Key Concepts

- **AcpCodec** (17 connections) — `src/pair_harness/adapters/acp/engine.py`
- **.map_notification()** (9 connections) — `src/pair_harness/adapters/acp/engine.py`
- **Any** (8 connections)
- **._tool_update_event()** (7 connections) — `src/pair_harness/adapters/acp/engine.py`
- **._permission_event()** (6 connections) — `src/pair_harness/adapters/acp/engine.py`
- **AcpProtocolError** (6 connections) — `src/pair_harness/adapters/acp/engine.py`
- **test_codec_only_completed_or_failed_finishes_tool()** (6 connections) — `tests/unit/test_acp_engine.py`
- **._op_fields()** (5 connections) — `src/pair_harness/adapters/acp/engine.py`
- **_codec_binding()** (5 connections) — `tests/unit/test_acp_engine.py`
- **test_codec_failed_tool_carries_command_and_output()** (5 connections) — `tests/unit/test_acp_engine.py`
- **._chunk_text()** (4 connections) — `src/pair_harness/adapters/acp/engine.py`
- **._next()** (4 connections) — `src/pair_harness/adapters/acp/engine.py`
- **._tool_text()** (4 connections) — `src/pair_harness/adapters/acp/engine.py`
- **test_codec_permission_paths_come_from_locations_and_write_access_directories()** (4 connections) — `tests/unit/test_acp_engine.py`
- **test_codec_move_file_paths_come_from_tool_arguments()** (3 connections) — `tests/unit/test_acp_engine.py`
- **.__init__()** (2 connections) — `src/pair_harness/adapters/acp/engine.py`
- **_tool_update()** (2 connections) — `tests/unit/test_acp_engine.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **RuntimeError** (1 connections)
- **把 session/update 通知与 session/request_permission 请求映射为 EngineEvent。** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **消息与思考 chunk 的 ContentBlock 文本；非文本块没有可展示的文字。** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **ToolCallContent 列表里文本内容块的拼接。** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **Reasonix 发来的 ACP 消息不符合协议。** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **从 ACP ToolCall 提取沙箱与审批字段。 路径取协议字段 ``locations[].path``；Reasonix 写权限审批申请的目录在…** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **binding 提供 conversation_id、task_id、engine_turn_id；界面辅助更新返回 None。** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- *... and 1 more nodes in this community*

## Relationships

- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (14 shared connections)
- [ACP 回合生命周期测试](ACP_回合生命周期测试.md) (6 shared connections)

## Source Files

- `src/pair_harness/adapters/acp/engine.py`
- `tests/unit/test_acp_engine.py`

## Audit Trail

- EXTRACTED: 53 (84%)
- INFERRED: 10 (16%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*