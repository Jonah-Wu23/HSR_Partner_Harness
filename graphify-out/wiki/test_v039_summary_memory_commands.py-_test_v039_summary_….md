# test_v039_summary_memory_commands.py: test_v039_summary_…

> 16 nodes · cohesion 0.20

## Key Concepts

- **test_v039_summary_memory_commands.py** (10 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **test_memory_update_and_delete_persist_and_broadcast()** (8 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **command()** (7 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **test_summary_regenerate_broadcasts_completed()** (7 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **test_memory_scope_mismatch_reports_real_error()** (6 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **test_summary_regenerate_unknown_id_fails_truthfully()** (6 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **Path** (5 connections)
- **test_reuse_active_does_not_reuse_across_pairs()** (4 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **_wait_until()** (2 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **DesktopCommand** (1 connections)
- **V0.3.9 遗留闭环：P02 复用作用域与 summary/memory 四命令。 契约出处：归档正文 ``.archive/v0.3.9-dual-…** (1 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **summary.regenerate 对不存在的摘要 ID 以真实错误失败（不伪造成功）。** (1 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **memory.update/delete 真实持久化并广播（契约 §2：修改与删除必须生效）。** (1 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **构造不存在记忆的 update/delete 报 memory_not_found（越作用域真实报错）。** (1 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **reuse_active 只复用在同项目+同卡+同搭档的活跃会话；跨搭档不复用。 直接验证 find_active_conversation 的…** (1 connections) — `tests/unit/test_v039_summary_memory_commands.py`
- **summary.regenerate 对真实失败记录重新生成：broadcast completed，落库更新。** (1 connections) — `tests/unit/test_v039_summary_memory_commands.py`

## Relationships

- [Demo 服务与队列测试](Demo_服务与队列测试.md) (5 shared connections)
- [桌面后端角色卡命令](桌面后端角色卡命令.md) (2 shared connections)
- [配对级长期记忆存储](配对级长期记忆存储.md) (2 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [委派与契约模型](委派与契约模型.md) (1 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (1 shared connections)
- [长期记忆与身份](长期记忆与身份.md) (1 shared connections)
- [摘要与投影存储校验](摘要与投影存储校验.md) (1 shared connections)

## Source Files

- `tests/unit/test_v039_summary_memory_commands.py`

## Audit Trail

- EXTRACTED: 31 (82%)
- INFERRED: 7 (18%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*