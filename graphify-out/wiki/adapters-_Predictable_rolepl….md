# adapters: Predictable rolepl…

> 14 nodes · cohesion 0.18

## Key Concepts

- **ScriptedDialogueModel** (21 connections) — `src/pair_harness/adapters/demo.py`
- **test_restored_orchestrator_backfills_history_and_session_ref()** (15 connections) — `tests/integration/test_conversation_restore.py`
- **test_completed_demo_conversation_restores_after_reopen()** (9 connections) — `tests/integration/test_conversation_restore.py`
- **test_desktop_service_restores_each_conversation_pair_without_crossing()** (5 connections) — `tests/integration/test_conversation_restore.py`
- **_desktop_command()** (4 connections) — `tests/integration/test_conversation_restore.py`
- **Path** (4 connections)
- **asyncio** (3 connections)
- **.generate_summary()** (2 connections) — `src/pair_harness/adapters/demo.py`
- **.generate_title()** (2 connections) — `src/pair_harness/adapters/demo.py`
- **Predictable roleplay adapter used by Plan A demos and tests.** (1 connections) — `src/pair_harness/adapters/demo.py`
- **确定性摘要：demo/测试用，不做语义判断、不改写消息原文。** (1 connections) — `src/pair_harness/adapters/demo.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/demo.py`
- **DesktopCommand** (1 connections)
- **O2.2：restore_conversation 回填消息历史与 EngineSessionRef。 恢复后再发消息：角色模型收到的近期上下文包含历史消息；…** (1 connections) — `tests/integration/test_conversation_restore.py`

## Relationships

- [规划式评审测试夹具](规划式评审测试夹具.md) (9 shared connections)
- [委派与契约模型](委派与契约模型.md) (5 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (4 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (4 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (4 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (4 shared connections)
- [存储增量缓冲与刷盘](存储增量缓冲与刷盘.md) (2 shared connections)
- [会话编排器](会话编排器.md) (2 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (1 shared connections)
- [服务模式集成测试](服务模式集成测试.md) (1 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (1 shared connections)
- [Demo 服务与队列测试](Demo_服务与队列测试.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/demo.py`
- `tests/integration/test_conversation_restore.py`

## Audit Trail

- EXTRACTED: 28 (52%)
- INFERRED: 26 (48%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*