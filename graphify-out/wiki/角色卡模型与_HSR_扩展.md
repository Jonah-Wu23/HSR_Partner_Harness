# 角色卡模型与 HSR 扩展

> 104 nodes · cohesion 0.04

## Key Concepts

- **CharacterCard** (51 connections) — `src/pair_harness/character_cards/models.py`
- **character_prompt_assembler.py** (40 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **assemble_turn_prompt()** (40 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **test_character_prompt_assembler.py** (27 connections) — `tests/unit/test_character_prompt_assembler.py`
- **HsrExtension** (25 connections) — `src/pair_harness/character_cards/models.py`
- **CharacterBook** (21 connections) — `src/pair_harness/character_cards/models.py`
- **assemble_character_prompt()** (21 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_turn_card()** (13 connections) — `tests/unit/test_character_prompt_assembler.py`
- **AssemblyModule** (10 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_world_book_modules()** (10 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_collect_unexpanded()** (8 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_join_entry_contents()** (8 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_load_baiyu_card()** (8 connections) — `tests/unit/test_character_prompt_assembler.py`
- **test_turn_base_reuse_matches_fresh_computation()** (8 connections) — `tests/unit/test_character_prompt_assembler.py`
- **_apply_depth_prompt()** (7 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_block_lines()** (7 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_collect_trigger_texts()** (7 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_memory_module()** (7 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **test_turn_at_depth_group_and_depth_prompt_not_in_system_text()** (7 connections) — `tests/unit/test_character_prompt_assembler.py`
- **test_turn_system_text_order()** (7 connections) — `tests/unit/test_character_prompt_assembler.py`
- **AssembledPrompt** (6 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **DepthInjection** (6 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_render_block_text()** (6 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **_summary_module()** (6 connections) — `src/pair_harness/core/character_prompt_assembler.py`
- **test_turn_budget_overflow_excludes_low_priority_entry()** (6 connections) — `tests/unit/test_character_prompt_assembler.py`
- *... and 79 more nodes in this community*

## Relationships

- [世界书深度注入激活](世界书深度注入激活.md) (21 shared connections)
- [角色卡编解码与兼容报告](角色卡编解码与兼容报告.md) (18 shared connections)
- [test_v039_assembler_summary_memory.py: test_v039_assemble…](test_v039_assembler_summary_memory.py-_test_v039_assemble….md) (12 shared connections)
- [角色卡仓库](角色卡仓库.md) (10 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (6 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (6 shared connections)
- [长期记忆与身份](长期记忆与身份.md) (5 shared connections)
- [世界书激活与 token 估算](世界书激活与_token_估算.md) (4 shared connections)
- [桌面后端角色卡命令](桌面后端角色卡命令.md) (4 shared connections)
- [角色上下文窗口与摘要](角色上下文窗口与摘要.md) (4 shared connections)
- [提示词装配诊断](提示词装配诊断.md) (3 shared connections)
- [数据宏展开](数据宏展开.md) (3 shared connections)

## Source Files

- `src/pair_harness/character_cards/models.py`
- `src/pair_harness/core/character_prompt_assembler.py`
- `tests/unit/test_character_prompt_assembler.py`

## Audit Trail

- EXTRACTED: 258 (82%)
- INFERRED: 58 (18%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*