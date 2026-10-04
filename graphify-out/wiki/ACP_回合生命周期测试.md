# ACP 回合生命周期测试

> 20 nodes · cohesion 0.23

## Key Concepts

- **test_acp_engine.py** (37 connections) — `tests/unit/test_acp_engine.py`
- **open_session()** (13 connections) — `tests/unit/test_acp_engine.py`
- **asyncio** (11 connections)
- **test_silent_turn_alerts_then_cancels_with_stderr_tail()** (11 connections) — `tests/unit/test_acp_engine.py`
- **run_turn()** (10 connections) — `tests/unit/test_acp_engine.py`
- **test_aclose_mid_turn_releases_session_subscription()** (8 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_terminal_follows_stop_reason_after_successful_tools()** (8 connections) — `tests/unit/test_acp_engine.py`
- **test_open_session_creates_session_and_resumes_after_reasonix_restart()** (7 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_maps_acp_updates_to_engine_events()** (7 connections) — `tests/unit/test_acp_engine.py`
- **test_run_turn_reports_prompt_json_rpc_error_as_turn_failed()** (7 connections) — `tests/unit/test_acp_engine.py`
- **test_amend_turn_uses_steer_extension()** (6 connections) — `tests/unit/test_acp_engine.py`
- **test_cancel_turn_sends_session_cancel()** (6 connections) — `tests/unit/test_acp_engine.py`
- **task_request()** (5 connections) — `tests/unit/test_acp_engine.py`
- **session_update()** (4 connections) — `tests/unit/test_acp_engine.py`
- **agent_message_chunk()** (3 connections) — `tests/unit/test_acp_engine.py`
- **parametrize** (2 connections)
- **MonkeyPatch** (1 connections)
- **session/update 通知；sessionId 由 FakeReasonixAcp 发送时填入。** (1 connections) — `tests/unit/test_acp_engine.py`
- **Reasonix 静默时按间隔告警，达到空闲超时后取消回合，失败回执带 stderr 尾部。** (1 connections) — `tests/unit/test_acp_engine.py`
- **消费方在 TOOL_STARTED 后关闭回合，同一 session 能再次订阅并完整跑完下一轮。** (1 connections) — `tests/unit/test_acp_engine.py`

## Relationships

- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (25 shared connections)
- [Reasonix ACP 假进程](Reasonix_ACP_假进程.md) (10 shared connections)
- [测试替身与集成夹具](测试替身与集成夹具.md) (9 shared connections)
- [ACP 事件映射编解码](ACP_事件映射编解码.md) (6 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (4 shared connections)
- [JSONL 传输测试夹具](JSONL_传输测试夹具.md) (2 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (2 shared connections)
- [审批裁决与审查智能体](审批裁决与审查智能体.md) (1 shared connections)
- [pytest 夹具与事件记录](pytest_夹具与事件记录.md) (1 shared connections)
- [JSONL 连接协议抽象](JSONL_连接协议抽象.md) (1 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (1 shared connections)
- [JSONL JSON-RPC 传输](JSONL_JSON-RPC_传输.md) (1 shared connections)

## Source Files

- `tests/unit/test_acp_engine.py`

## Audit Trail

- EXTRACTED: 85 (80%)
- INFERRED: 21 (20%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*