# ACP 引擎测试

> 31 nodes · cohesion 0.13

## Key Concepts

- **test_acp_engine.py** (34 connections) — `tests/unit/test_acp_engine.py`
- **asyncio** (19 connections)
- **ScriptedStopReasonServer** (13 connections) — `tests/unit/test_acp_engine.py`
- **_run_scripted_turn()** (10 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_accepts_snake_case_fields_and_rejected_status()** (7 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_drains_tool_completion_after_prompt_response()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_maps_permission_request()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_reports_cancelled_for_cancelled_stop_reason_after_success()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_reports_failed_for_blank_stop_reason()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_reports_failed_for_error_stop_reason_after_successful_tools()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_reports_failed_for_missing_stop_reason()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_reports_failed_for_result_error_field()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_reports_failed_for_unknown_stop_reason()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_reports_failed_for_unsuccessful_stop_reason()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_maps_acp_events_to_engine_events()** (5 connections) — `tests/unit/test_acp_engine.py`
- **test_amend_turn_uses_steer_extension()** (4 connections) — `tests/unit/test_acp_engine.py`
- **test_approval_resolve_responds_to_acp_request()** (4 connections) — `tests/unit/test_acp_engine.py`
- **test_cancel_turn_sends_notification()** (3 connections) — `tests/unit/test_acp_engine.py`
- **test_open_session_initializes_and_creates_acp_session()** (3 connections) — `tests/unit/test_acp_engine.py`
- **V0.2 M3：DeepSeek 编程助手（Reasonix ACP）适配器（方案 §M3-5）。 用内存 JSONL 连接模拟 ``reasonix…** (1 connections) — `tests/unit/test_acp_engine.py`
- **prompt 响应先到时，短暂延后的工具回执仍进入事件流。** (1 connections) — `tests/unit/test_acp_engine.py`
- **codec 兼容分支：snake_case 字段、dict 结果文本、rejected → failed。** (1 connections) — `tests/unit/test_acp_engine.py`
- **按脚本改写 session/prompt 响应：指定 stopReason、去掉它或注入 error。…** (1 connections) — `tests/unit/test_acp_engine.py`
- **V039-S4-009：工具与正文全部成功后 stopReason=error，终态仍必须是 failed。…** (1 connections) — `tests/unit/test_acp_engine.py`
- **stopReason=cancelled 是协议终态，既不是 failed 也不伪装成 completed。** (1 connections) — `tests/unit/test_acp_engine.py`
- *... and 6 more nodes in this community*

## Relationships

- [ACP 编码引擎](ACP_编码引擎.md) (17 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (15 shared connections)
- [test_acp_engine.py: engine_and_server(…](test_acp_engine.py-_engine_and_server….md) (7 shared connections)
- [委派与契约模型](委派与契约模型.md) (3 shared connections)
- [test_acp_engine.py: FakeTransport](test_acp_engine.py-_FakeTransport.md) (2 shared connections)
- [test_acp_engine.py: V0.3.3：消费方在 TOOL_S…](test_acp_engine.py-_V0.3.3：消费方在_TOOL_S….md) (2 shared connections)
- [JSONL 子进程传输](JSONL_子进程传输.md) (1 shared connections)
- [test_acp_engine.py: FakeAcpConnection](test_acp_engine.py-_FakeAcpConnection.md) (1 shared connections)
- [adapters: AcpCodec](adapters-_AcpCodec.md) (1 shared connections)
- [审批管理器](审批管理器.md) (1 shared connections)

## Source Files

- `tests/unit/test_acp_engine.py`

## Audit Trail

- EXTRACTED: 82 (75%)
- INFERRED: 27 (25%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*