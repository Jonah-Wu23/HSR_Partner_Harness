# test_text_loop_live.py: test_text_loop_liv…

> 14 nodes · cohesion 0.23

## Key Concepts

- **test_text_loop_live.py** (12 connections) — `tests/integration/test_text_loop_live.py`
- **_live_orchestrator()** (8 connections) — `tests/integration/test_text_loop_live.py`
- **test_live_deepseek_roleplay_boundaries_are_stable()** (8 connections) — `tests/integration/test_text_loop_live.py`
- **Path** (6 connections)
- **live_env()** (4 connections) — `tests/integration/test_text_loop_live.py`
- **run_cli()** (4 connections) — `tests/integration/test_text_loop_live.py`
- **test_live_cli_creates_file_and_resumes_thread()** (4 connections) — `tests/integration/test_text_loop_live.py`
- **smoke_project()** (3 connections) — `tests/integration/test_text_loop_live.py`
- **fixture** (2 connections)
- **asyncio** (1 connections)
- **CompletedProcess** (1 connections)
- **B1 真实联调：DeepSeek 对话 + codex app-server 全链路（live marker）。…** (1 connections) — `tests/integration/test_text_loop_live.py`
- **固定三场景重复两轮：闲聊、委派、失败结果均遵守职责边界。** (1 connections) — `tests/integration/test_text_loop_live.py`
- **第一次运行创建 hello.txt；同一会话二次运行恢复旧聊天；新会话另开线程。** (1 connections) — `tests/integration/test_text_loop_live.py`

## Relationships

- [委派与契约模型](委派与契约模型.md) (3 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (3 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (2 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (2 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (2 shared connections)
- [会话编排器](会话编排器.md) (1 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (1 shared connections)

## Source Files

- `tests/integration/test_text_loop_live.py`

## Audit Trail

- EXTRACTED: 30 (86%)
- INFERRED: 5 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*