# test_v039_prompt_assembly_seams.py: test_v039_prompt_a…

> 19 nodes · cohesion 0.16

## Key Concepts

- **test_v039_prompt_assembly_seams.py** (20 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **_bind_card_conversation()** (6 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **_call()** (5 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **_insert_completed_summary()** (5 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **_store_active_memory()** (5 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **test_bound_card_with_completed_summary_assembles_summary_module()** (5 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **_publish_card()** (4 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **test_active_memory_reaches_bound_card_assembly()** (4 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **test_active_memory_reaches_unbound_conversation_prompt()** (4 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **test_conversation_without_project_skips_memories_without_failing()** (4 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **Any** (1 connections)
- **V0.3.9 提示词装配接缝：摘要与 active 记忆必须真正进入角色 system 提示词。 三个经审查确认的缺陷都落在…** (1 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **直接落库一条 completed 摘要（覆盖区间取会话内真实消息）。** (1 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **按会话权威作用域直接落库一条 active 记忆（content 为 JSON 文本）。** (1 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **绑定卡 + completed 摘要：接缝返回 core 摘要对象，装配含 chat_summary。** (1 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **绑定卡会话：active 记忆进入装配诊断与 system_text。** (1 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **未绑定卡的会话按 builtin:<角色 id> 作用域读到同一条记忆。** (1 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **无项目会话没有记忆作用域：按无记忆继续，装配不发模型请求就失败。** (1 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`
- **发布一张卡、选为 active 并新建绑定会话，返回 conversation_id。** (1 connections) — `tests/unit/test_v039_prompt_assembly_seams.py`

## Relationships

- [对话上下文与消息模型](对话上下文与消息模型.md) (5 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (2 shared connections)
- [委派与契约模型](委派与契约模型.md) (2 shared connections)
- [角色上下文窗口与摘要](角色上下文窗口与摘要.md) (2 shared connections)
- [storage: records.py](storage-_records.py.md) (1 shared connections)
- [Demo 服务与队列测试](Demo_服务与队列测试.md) (1 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (1 shared connections)
- [摘要与投影存储校验](摘要与投影存储校验.md) (1 shared connections)
- [配对级长期记忆存储](配对级长期记忆存储.md) (1 shared connections)
- [桌面后端角色卡命令](桌面后端角色卡命令.md) (1 shared connections)

## Source Files

- `tests/unit/test_v039_prompt_assembly_seams.py`

## Audit Trail

- EXTRACTED: 39 (89%)
- INFERRED: 5 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*