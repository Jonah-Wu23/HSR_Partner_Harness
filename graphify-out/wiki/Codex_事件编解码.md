# Codex 事件编解码

> 22 nodes · cohesion 0.17

## Key Concepts

- **CodexCodec** (20 connections) — `src/pair_harness/adapters/codex/codec.py`
- **test_codex_event_mapping.py** (9 connections) — `tests/unit/test_codex_event_mapping.py`
- **binding()** (9 connections) — `tests/unit/test_codex_event_mapping.py`
- **EventBinding** (8 connections) — `src/pair_harness/adapters/codex/codec.py`
- **._event()** (6 connections) — `src/pair_harness/adapters/codex/codec.py`
- **.map_notification()** (6 connections) — `src/pair_harness/adapters/codex/codec.py`
- **._native_approval_id()** (4 connections) — `src/pair_harness/adapters/codex/codec.py`
- **test_maps_cancelled_turn_to_completed_cancelled_not_failed()** (4 connections) — `tests/unit/test_codex_event_mapping.py`
- **test_maps_file_change_request_approval_grant_root_to_paths()** (4 connections) — `tests/unit/test_codex_event_mapping.py`
- **test_maps_server_initiated_request_approval_payload()** (4 connections) — `tests/unit/test_codex_event_mapping.py`
- **test_rejects_non_numeric_native_approval_id()** (4 connections) — `tests/unit/test_codex_event_mapping.py`
- **Any** (3 connections)
- **test_maps_assistant_and_tool_notifications()** (3 connections) — `tests/unit/test_codex_event_mapping.py`
- **test_maps_failed_turn_and_ignores_other_turn()** (3 connections) — `tests/unit/test_codex_event_mapping.py`
- **test_maps_returned_reasoning_channels()** (3 connections) — `tests/unit/test_codex_event_mapping.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/codex/codec.py`
- **Map native app-server notifications to stable Pair Harness events.…** (1 connections) — `src/pair_harness/adapters/codex/codec.py`
- **校验原生审批请求的 approval_id 必须是数字。 M1.5：缺失或非数字 id 在 codec 阶段就变成可见协议失败，而不是等到…** (1 connections) — `src/pair_harness/adapters/codex/codec.py`
- **M6.1：原生 turn/completed status=cancelled 映射为取消回执，不能 failed。** (1 connections) — `tests/unit/test_codex_event_mapping.py`
- **M1.5：缺失/非数字 approval_id 在 codec 阶段即协议失败。** (1 connections) — `tests/unit/test_codex_event_mapping.py`
- **O3.1：app-server 服务端发起的 requestApproval（带 JSON-RPC id）。 approval_id 取请求…** (1 connections) — `tests/unit/test_codex_event_mapping.py`
- **O3.1：fileChange 审批把 grantRoot 归一进 paths 供沙箱检查。** (1 connections) — `tests/unit/test_codex_event_mapping.py`

## Relationships

- [ACP 编码引擎](ACP_编码引擎.md) (10 shared connections)
- [Codex app-server 引擎](Codex_app-server_引擎.md) (4 shared connections)
- [test_v038_t4_delegation_chain.py: _binding()](test_v038_t4_delegation_chain.py-__binding.md) (3 shared connections)

## Source Files

- `src/pair_harness/adapters/codex/codec.py`
- `tests/unit/test_codex_event_mapping.py`

## Audit Trail

- EXTRACTED: 44 (77%)
- INFERRED: 13 (23%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*