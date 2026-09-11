# Codex 审批流集成测试

> 29 nodes · cohesion 0.14

## Key Concepts

- **FakeCodexAppServer** (23 connections) — `tests/fixtures/fake_codex_app_server.py`
- **test_codex_approval_flow.py** (21 connections) — `tests/integration/test_codex_approval_flow.py`
- **test_event_sequence.py** (21 connections) — `tests/integration/test_event_sequence.py`
- **test_native_approval_flow_sequence_contiguous()** (16 connections) — `tests/integration/test_event_sequence.py`
- **make_transport()** (13 connections) — `tests/integration/test_codex_approval_flow.py`
- **test_full_auto_replies_accept_without_callback()** (13 connections) — `tests/integration/test_codex_approval_flow.py`
- **test_sandbox_deny_sequence_contiguous()** (13 connections) — `tests/integration/test_event_sequence.py`
- **test_gate_path_user_deny_sequence_contiguous()** (12 connections) — `tests/integration/test_event_sequence.py`
- **drive_approval_turn()** (9 connections) — `tests/integration/test_codex_approval_flow.py`
- **test_open_session_maps_policy_params_to_thread_start()** (8 connections) — `tests/integration/test_codex_approval_flow.py`
- **test_open_session_omits_policy_params_when_none()** (8 connections) — `tests/integration/test_codex_approval_flow.py`
- **fake_codex_app_server.py** (7 connections) — `tests/fixtures/fake_codex_app_server.py`
- **make_orchestrator()** (7 connections) — `tests/integration/test_event_sequence.py`
- **asyncio** (6 connections)
- **assert_contiguous()** (4 connections) — `tests/integration/test_event_sequence.py`
- **asyncio** (4 connections)
- **factory()** (1 connections) — `tests/integration/test_codex_approval_flow.py`
- **O3.1：审批体系统一 —— 适配器层全链路测试。 场景：orchestrator 经 CodexAppServerEngine 跑真实传输协议， app-…** (1 connections) — `tests/integration/test_codex_approval_flow.py`
- **完全允许运行：引擎仍发起请求时直接回复 accept，无需用户交互。** (1 connections) — `tests/integration/test_codex_approval_flow.py`
- **O3.1：open_session 预留策略映射位置——thread/start 参数携带 approvalPolicy / sandbox /…** (1 connections) — `tests/integration/test_codex_approval_flow.py`
- **默认 None 不发送策略字段，保持既有协议形态。** (1 connections) — `tests/integration/test_codex_approval_flow.py`
- **连接工厂必须是协程（transport.start 会 await 它），否则任务直接 TypeError 失败、测试侧 serve_request 永久挂起。** (1 connections) — `tests/integration/test_codex_approval_flow.py`
- **跑一轮带原生审批请求的完整任务，返回 thread/start、turn/start、 审批回复与最终回执。调用方负责提供裁决回调并等待返回。** (1 connections) — `tests/integration/test_codex_approval_flow.py`
- **O4.1：事件序号统一 —— orchestrator 出口事件流序号连续无碰撞。 适配器（codec）不再自定序号（全部固定 0），编排器在出口处用单一…** (1 connections) — `tests/integration/test_event_sequence.py`
- **原生审批请求被沙箱拦截：合成否决事件与后续收尾序号连续。** (1 connections) — `tests/integration/test_event_sequence.py`
- *... and 4 more nodes in this community*

## Relationships

- [规划式评审测试夹具](规划式评审测试夹具.md) (34 shared connections)
- [Codex 传输集成测试](Codex_传输集成测试.md) (20 shared connections)
- [委派与契约模型](委派与契约模型.md) (8 shared connections)
- [Codex app-server 引擎](Codex_app-server_引擎.md) (5 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (4 shared connections)
- [JSONL 子进程传输](JSONL_子进程传输.md) (3 shared connections)
- [fake_codex_app_server.py: .notify()](fake_codex_app_server.py-_.notify.md) (2 shared connections)
- [会话编排器](会话编排器.md) (2 shared connections)
- [审批管理器](审批管理器.md) (2 shared connections)
- [test_codex_transport_robustness.py: test_codex_transpo…](test_codex_transport_robustness.py-_test_codex_transpo….md) (1 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (1 shared connections)

## Source Files

- `tests/fixtures/fake_codex_app_server.py`
- `tests/integration/test_codex_approval_flow.py`
- `tests/integration/test_event_sequence.py`

## Audit Trail

- EXTRACTED: 95 (68%)
- INFERRED: 45 (32%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*