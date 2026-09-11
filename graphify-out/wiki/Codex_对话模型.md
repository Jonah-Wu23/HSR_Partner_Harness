# Codex 对话模型

> 93 nodes · cohesion 0.04

## Key Concepts

- **OpenAICompatibleDialogueModel** (76 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **DialogueRequest** (53 connections) — `src/pair_harness/core/contracts.py`
- **DialogueEvent** (37 connections) — `src/pair_harness/core/contracts.py`
- **DialogueModelReviewer** (30 connections) — `src/pair_harness/adapters/reviewer.py`
- **DialogueModel** (29 connections) — `src/pair_harness/core/ports.py`
- **reviewer.py** (20 connections) — `src/pair_harness/adapters/reviewer.py`
- **dialogue.py** (18 connections) — `src/pair_harness/adapters/codex/dialogue.py`
- **test_reviewer.py** (18 connections) — `tests/unit/test_reviewer.py`
- **CodexDialogueModel** (17 connections) — `src/pair_harness/adapters/codex/dialogue.py`
- **.stream_reply()** (14 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **DeltaAndFinalModel** (13 connections) — `tests/unit/test_reviewer.py`
- **asyncio** (13 connections)
- **test_dialogue_reviewer_uses_only_latest_three_user_messages()** (12 connections) — `tests/unit/test_reviewer.py`
- **test_dialogue_reviewer_parses_clean_speech_delta_stream()** (10 connections) — `tests/unit/test_reviewer.py`
- **test_dialogue_reviewer_parses_full_delta_stream()** (10 connections) — `tests/unit/test_reviewer.py`
- **test_dialogue_reviewer_prefers_raw_from_speech_completed()** (10 connections) — `tests/unit/test_reviewer.py`
- **.build_messages()** (9 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **.review()** (8 connections) — `src/pair_harness/adapters/reviewer.py`
- **test_dialogue_reviewer_parses_role_protocol_wrapper()** (8 connections) — `tests/unit/test_reviewer.py`
- **.generate_summary()** (6 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **._needs_delegation_retry()** (6 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **._request_extras()** (6 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **._system_prompt()** (6 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **test_deny_verdict_requires_reason_and_suggestion()** (6 connections) — `tests/unit/test_reviewer.py`
- **test_dialogue_reviewer_fails_closed_on_fallback_speech()** (6 connections) — `tests/unit/test_reviewer.py`
- *... and 68 more nodes in this community*

## Relationships

- [规划式评审测试夹具](规划式评审测试夹具.md) (35 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (31 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (24 shared connections)
- [审批管理器](审批管理器.md) (20 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (18 shared connections)
- [委派与契约模型](委派与契约模型.md) (17 shared connections)
- [模型输出解析](模型输出解析.md) (15 shared connections)
- [OpenAI 兼容层测试](OpenAI_兼容层测试.md) (12 shared connections)
- [test_deepseek_request_shape.py: AsyncClient](test_deepseek_request_shape.py-_AsyncClient.md) (9 shared connections)
- [会话编排器](会话编排器.md) (6 shared connections)
- [假聊天服务器测试](假聊天服务器测试.md) (5 shared connections)
- [增量 JSON 解析测试](增量_JSON_解析测试.md) (5 shared connections)

## Source Files

- `src/pair_harness/adapters/codex/dialogue.py`
- `src/pair_harness/adapters/demo.py`
- `src/pair_harness/adapters/dialogue/openai_compatible.py`
- `src/pair_harness/adapters/reviewer.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/ports.py`
- `tests/fakes.py`
- `tests/unit/test_application_service.py`
- `tests/unit/test_reviewer.py`

## Audit Trail

- EXTRACTED: 284 (68%)
- INFERRED: 134 (32%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*