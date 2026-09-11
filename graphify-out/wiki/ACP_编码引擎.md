# ACP 编码引擎

> 111 nodes · cohesion 0.04

## Key Concepts

- **EngineEvent** (77 connections) — `src/pair_harness/core/contracts.py`
- **EngineSessionRef** (71 connections) — `src/pair_harness/core/contracts.py`
- **TaskRequest** (62 connections) — `src/pair_harness/core/contracts.py`
- **ScriptedCodingEngine** (58 connections) — `src/pair_harness/adapters/demo.py`
- **EngineEventType** (56 connections) — `src/pair_harness/core/contracts.py`
- **ports.py** (41 connections) — `src/pair_harness/core/ports.py`
- **AcpCodingEngine** (32 connections) — `src/pair_harness/adapters/acp/engine.py`
- **CodingEngine** (24 connections) — `src/pair_harness/core/ports.py`
- **codex/engine.py** (21 connections) — `src/pair_harness/adapters/codex/engine.py`
- **TaskAmendment** (20 connections) — `src/pair_harness/core/contracts.py`
- **StateStore** (20 connections) — `src/pair_harness/core/ports.py`
- **acp/engine.py** (14 connections) — `src/pair_harness/adapters/acp/engine.py`
- **PausingEngine** (12 connections) — `tests/unit/test_amendment_routing.py`
- **.__init__()** (11 connections) — `src/pair_harness/core/orchestrator.py`
- **CancelableEngine** (11 connections) — `tests/unit/test_cancel_flow.py`
- **_FlakyEngine** (11 connections) — `tests/unit/test_delegation_retry.py`
- **Reviewer** (10 connections) — `src/pair_harness/core/ports.py`
- **GatedCodingEngine** (10 connections) — `tests/integration/test_progress_summary_injection.py`
- **SequenceEngine** (10 connections) — `tests/unit/test_v032_baselines.py`
- **main()** (9 connections) — `scripts/repro_acp_engine.py`
- **_DupPatchEngine** (9 connections) — `tests/integration/test_changed_files_dedup.py`
- **test_restore_drops_session_from_a_different_engine()** (9 connections) — `tests/integration/test_conversation_restore.py`
- **_GateDenyEngine** (9 connections) — `tests/integration/test_event_sequence.py`
- **UnboundEngine** (9 connections) — `tests/unit/test_amendment_routing.py`
- **BlockedEngine** (9 connections) — `tests/unit/test_cancel_flow.py`
- *... and 86 more nodes in this community*

## Relationships

- [委派与契约模型](委派与契约模型.md) (56 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (50 shared connections)
- [审批管理器](审批管理器.md) (28 shared connections)
- [会话编排器](会话编排器.md) (27 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (18 shared connections)
- [Codex app-server 引擎](Codex_app-server_引擎.md) (17 shared connections)
- [ACP 引擎测试](ACP_引擎测试.md) (17 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (11 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (10 shared connections)
- [Codex 事件编解码](Codex_事件编解码.md) (10 shared connections)
- [并发入口测试](并发入口测试.md) (9 shared connections)
- [V0.3.8 委派执行链测试](V0.3.8_委派执行链测试.md) (8 shared connections)

## Source Files

- `scripts/repro_acp_engine.py`
- `src/pair_harness/adapters/acp/engine.py`
- `src/pair_harness/adapters/codex/codec.py`
- `src/pair_harness/adapters/codex/engine.py`
- `src/pair_harness/adapters/demo.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/orchestrator.py`
- `src/pair_harness/core/ports.py`
- `src/pair_harness/desktop_backend/application_service.py`
- `tests/contract/test_ports.py`
- `tests/integration/test_changed_files_dedup.py`
- `tests/integration/test_conversation_restore.py`
- `tests/integration/test_event_sequence.py`
- `tests/integration/test_progress_summary_injection.py`
- `tests/unit/test_amendment_routing.py`
- `tests/unit/test_cancel_flow.py`
- `tests/unit/test_concurrent_entries.py`
- `tests/unit/test_contracts.py`
- `tests/unit/test_delegation_retry.py`
- `tests/unit/test_task_lifecycle.py`

## Audit Trail

- EXTRACTED: 435 (69%)
- INFERRED: 191 (31%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*