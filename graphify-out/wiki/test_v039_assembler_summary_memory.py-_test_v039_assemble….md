# test_v039_assembler_summary_memory.py: test_v039_assemble…

> 17 nodes · cohesion 0.24

## Key Concepts

- **test_v039_assembler_summary_memory.py** (17 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **_memory()** (9 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **_card()** (7 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **_summary()** (7 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **test_event_trigger_stays_after_summary_and_memory()** (6 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **test_summary_and_memory_do_not_leak_into_assistant_brief()** (6 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **test_empty_summary_or_memory_content_produces_no_module()** (5 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **test_summary_and_memory_modules_follow_hsr_and_precede_triggers()** (5 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **_scope()** (4 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **test_deleted_memory_is_not_injected_but_active_is()** (4 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **test_failed_summary_is_not_injected()** (4 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **_hsr_with_trigger()** (3 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **test_no_summary_no_memory_keeps_previous_module_set()** (3 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **MemoryScope** (1 connections)
- **PairMemory** (1 connections)
- **V0.3.9 契约 §2：角色装配顺序中的聊天摘要与配对记忆模块。 契约出处：``.archive/v0.3.9-dual-track-…** (1 connections) — `tests/unit/test_v039_assembler_summary_memory.py`
- **摘要与记忆只进角色 system 段；本模块不产出助手文本。** (1 connections) — `tests/unit/test_v039_assembler_summary_memory.py`

## Relationships

- [角色卡模型与 HSR 扩展](角色卡模型与_HSR_扩展.md) (12 shared connections)
- [角色上下文窗口与摘要](角色上下文窗口与摘要.md) (4 shared connections)
- [长期记忆与身份](长期记忆与身份.md) (3 shared connections)
- [世界书深度注入激活](世界书深度注入激活.md) (1 shared connections)

## Source Files

- `tests/unit/test_v039_assembler_summary_memory.py`

## Audit Trail

- EXTRACTED: 49 (94%)
- INFERRED: 3 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*