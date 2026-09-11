# Codex app-server 引擎

> 22 nodes · cohesion 0.12

## Key Concepts

- **CodexAppServerEngine** (42 connections) — `src/pair_harness/adapters/codex/engine.py`
- **.run_turn()** (9 connections) — `src/pair_harness/adapters/codex/engine.py`
- **._decode_ref()** (6 connections) — `src/pair_harness/adapters/codex/engine.py`
- **.open_session()** (6 connections) — `src/pair_harness/adapters/codex/engine.py`
- **.amend_turn()** (4 connections) — `src/pair_harness/adapters/codex/engine.py`
- **.cancel_turn()** (4 connections) — `src/pair_harness/adapters/codex/engine.py`
- **.resolve_approval()** (4 connections) — `src/pair_harness/adapters/codex/engine.py`
- **test_codex_reasoning_effort_accepts_gpt_56_sol_levels()** (4 connections) — `tests/integration/test_codex_transport.py`
- **test_codex_reasoning_effort_normalizes_auto_to_medium()** (4 connections) — `tests/integration/test_codex_transport.py`
- **test_codex_reasoning_effort_rejects_invalid_values()** (4 connections) — `tests/integration/test_codex_transport.py`
- **._emit_no_progress_warning()** (3 connections) — `src/pair_harness/adapters/codex/engine.py`
- **._encode_ref()** (3 connections) — `src/pair_harness/adapters/codex/engine.py`
- **.__init__()** (3 connections) — `src/pair_harness/adapters/codex/engine.py`
- **.configure_reasoning()** (2 connections) — `src/pair_harness/adapters/codex/engine.py`
- **Any** (1 connections)
- **V0.3.8 T4（契约 §14.6）：回合无进展结构化告警。 app-server 静默重试（模型供给误配、网络停摆）期间客户端此前零感知；…** (1 connections) — `src/pair_harness/adapters/codex/engine.py`
- **O3.1：回复 app-server 挂起的审批请求（requestApproval）。 ``approval_id`` 是服务端请求的 JSON-RPC…** (1 connections) — `src/pair_harness/adapters/codex/engine.py`
- **设置 GPT-5.6 Sol 的真实 reasoning effort。** (1 connections) — `src/pair_harness/adapters/codex/engine.py`
- **打开（或恢复）app-server 线程。…** (1 connections) — `src/pair_harness/adapters/codex/engine.py`
- **parametrize** (1 connections)
- **configure_reasoning 的真实归一化：auto → medium（F5 档位语义）。** (1 connections) — `tests/integration/test_codex_transport.py`
- **非法档位必须报错，而不是静默接受后带着错误档位发请求。** (1 connections) — `tests/integration/test_codex_transport.py`

## Relationships

- [ACP 编码引擎](ACP_编码引擎.md) (17 shared connections)
- [Codex 传输集成测试](Codex_传输集成测试.md) (8 shared connections)
- [JSONL 子进程传输](JSONL_子进程传输.md) (5 shared connections)
- [Codex 审批流集成测试](Codex_审批流集成测试.md) (5 shared connections)
- [Codex 事件编解码](Codex_事件编解码.md) (4 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (4 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (3 shared connections)
- [V0.3.8 委派执行链测试](V0.3.8_委派执行链测试.md) (2 shared connections)
- [审批管理器](审批管理器.md) (2 shared connections)

## Source Files

- `src/pair_harness/adapters/codex/engine.py`
- `tests/integration/test_codex_transport.py`

## Audit Trail

- EXTRACTED: 48 (62%)
- INFERRED: 30 (38%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*