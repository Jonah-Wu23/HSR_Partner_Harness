# OpenAI 兼容对话解析

> 38 nodes · cohesion 0.08

## Key Concepts

- **openai_compatible.py** (48 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **test_text_loop_live.py** (14 connections) — `tests/integration/test_text_loop_live.py`
- **MemoryDraft** (11 connections) — `src/pair_harness/core/contracts.py`
- **test_live_deepseek_roleplay_boundaries_are_stable()** (9 connections) — `tests/integration/test_text_loop_live.py`
- **make_reviewer()** (9 connections) — `tests/unit/test_reviewer.py`
- **TaskAmendmentDraft** (7 connections) — `src/pair_harness/core/contracts.py`
- **test_reviewer.py** (7 connections) — `tests/unit/test_reviewer.py`
- **test_dialogue_reviewer_uses_only_latest_three_user_messages()** (7 connections) — `tests/unit/test_reviewer.py`
- **_parse_character_turn()** (6 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **_parse_delegation()** (6 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **_live_context()** (6 connections) — `tests/integration/test_text_loop_live.py`
- **_live_orchestrator()** (6 connections) — `tests/integration/test_text_loop_live.py`
- **Path** (6 connections)
- **_parse_memory()** (5 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **test_dialogue_reviewer_fails_closed_on_invalid_json()** (5 connections) — `tests/unit/test_reviewer.py`
- **_progress_summary_text()** (4 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **_runtime_context_text()** (4 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **run_cli()** (4 connections) — `tests/integration/test_text_loop_live.py`
- **test_live_cli_creates_file_and_resumes_session()** (4 connections) — `tests/integration/test_text_loop_live.py`
- **_result_summary_text()** (3 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **_title_source_label()** (3 connections) — `src/pair_harness/adapters/dialogue/openai_compatible.py`
- **live_env()** (3 connections) — `tests/integration/test_text_loop_live.py`
- **smoke_project()** (3 connections) — `tests/integration/test_text_loop_live.py`
- **asyncio** (3 connections)
- **test_dialogue_reviewer_rejects_non_boolean_allow()** (3 connections) — `tests/unit/test_reviewer.py`
- *... and 13 more nodes in this community*

## Relationships

- [OpenAI 兼容对话模型](OpenAI_兼容对话模型.md) (15 shared connections)
- [消息契约与会话编排](消息契约与会话编排.md) (11 shared connections)
- [测试替身与集成夹具](测试替身与集成夹具.md) (11 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (9 shared connections)
- [审批裁决与审查智能体](审批裁决与审查智能体.md) (7 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (7 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (5 shared connections)
- [对话供应商与搭档配置](对话供应商与搭档配置.md) (4 shared connections)
- [增量 JSON speech 解析](增量_JSON_speech_解析.md) (2 shared connections)
- [供应商识别与推理档位](供应商识别与推理档位.md) (2 shared connections)
- [角色卡模型与提示装配](角色卡模型与提示装配.md) (2 shared connections)
- [演示模型与对话契约](演示模型与对话契约.md) (2 shared connections)

## Source Files

- `src/pair_harness/adapters/dialogue/openai_compatible.py`
- `src/pair_harness/core/contracts.py`
- `tests/integration/test_text_loop_live.py`
- `tests/unit/test_reviewer.py`

## Audit Trail

- EXTRACTED: 122 (84%)
- INFERRED: 23 (16%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*