# ACP 编程引擎适配器

> 94 nodes · cohesion 0.06

## Key Concepts

- **application_service.py** (191 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **EngineEvent** (64 connections) — `src/pair_harness/core/contracts.py`
- **EngineSessionRef** (61 connections) — `src/pair_harness/core/contracts.py`
- **ScriptedCodingEngine** (53 connections) — `src/pair_harness/adapters/demo.py`
- **AcpCodingEngine** (44 connections) — `src/pair_harness/adapters/acp/engine.py`
- **TaskRequest** (41 connections) — `src/pair_harness/core/contracts.py`
- **ports.py** (41 connections) — `src/pair_harness/core/ports.py`
- **EngineEventType** (37 connections) — `src/pair_harness/core/contracts.py`
- **demo.py** (36 connections) — `src/pair_harness/adapters/demo.py`
- **ProjectRef** (33 connections) — `src/pair_harness/core/contracts.py`
- **CodingEngine** (26 connections) — `src/pair_harness/core/ports.py`
- **ToolRun** (21 connections) — `src/pair_harness/core/contracts.py`
- **ConversationSnapshot** (19 connections) — `src/pair_harness/core/repository.py`
- **engine.py** (17 connections) — `src/pair_harness/adapters/acp/engine.py`
- **TaskAmendment** (17 connections) — `src/pair_harness/core/contracts.py`
- **StateStore** (15 connections) — `src/pair_harness/core/ports.py`
- **core/repository.py** (14 connections) — `src/pair_harness/core/repository.py`
- **PausingEngine** (12 connections) — `tests/unit/test_conversation_concurrency.py`
- **CancelableEngine** (11 connections) — `tests/unit/test_cancel_flow.py`
- **.open_session()** (9 connections) — `src/pair_harness/adapters/acp/engine.py`
- **.run_turn()** (9 connections) — `src/pair_harness/adapters/acp/engine.py`
- **_DupPatchEngine** (9 connections) — `tests/integration/test_changed_files_dedup.py`
- **GatedCodingEngine** (9 connections) — `tests/integration/test_progress_summary_injection.py`
- **test_permission_request_is_answered_with_decision_option()** (9 connections) — `tests/unit/test_acp_engine.py`
- **UnboundEngine** (9 connections) — `tests/unit/test_amendment_routing.py`
- *... and 69 more nodes in this community*

## Relationships

- [测试替身与集成夹具](测试替身与集成夹具.md) (55 shared connections)
- [审批裁决与审查智能体](审批裁决与审查智能体.md) (48 shared connections)
- [消息契约与会话编排](消息契约与会话编排.md) (38 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (34 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (32 shared connections)
- [ACP 回合生命周期测试](ACP_回合生命周期测试.md) (25 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (16 shared connections)
- [对话摘要与上下文投影](对话摘要与上下文投影.md) (16 shared connections)
- [演示模型与对话契约](演示模型与对话契约.md) (15 shared connections)
- [ACP 事件映射编解码](ACP_事件映射编解码.md) (14 shared connections)
- [长期记忆与指标记录](长期记忆与指标记录.md) (12 shared connections)
- [流式事件顺序测试](流式事件顺序测试.md) (11 shared connections)

## Source Files

- `src/pair_harness/adapters/acp/engine.py`
- `src/pair_harness/adapters/demo.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/ports.py`
- `src/pair_harness/core/repository.py`
- `src/pair_harness/desktop_backend/application_service.py`
- `tests/integration/test_changed_files_dedup.py`
- `tests/integration/test_progress_summary_injection.py`
- `tests/unit/test_acp_engine.py`
- `tests/unit/test_amendment_routing.py`
- `tests/unit/test_application_service.py`
- `tests/unit/test_cancel_flow.py`
- `tests/unit/test_concurrent_entries.py`
- `tests/unit/test_conversation_concurrency.py`
- `tests/unit/test_delegation_retry.py`
- `tests/unit/test_sqlite_store.py`
- `tests/unit/test_stream_events.py`
- `tests/unit/test_task_lifecycle.py`

## Audit Trail

- EXTRACTED: 596 (78%)
- INFERRED: 171 (22%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*