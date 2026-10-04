# CLI 入口与应用路径

> 50 nodes · cohesion 0.07

## Key Concepts

- **MessageSource** (64 connections) — `src/pair_harness/core/contracts.py`
- **ApprovalMode** (60 connections) — `src/pair_harness/core/contracts.py`
- **cli.py** (37 connections) — `src/pair_harness/cli.py`
- **ExecutionContext** (23 connections) — `src/pair_harness/core/context.py`
- **run_real()** (21 connections) — `src/pair_harness/cli.py`
- **Settings** (18 connections) — `src/pair_harness/settings.py`
- **build_coding_engine()** (15 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **Enum** (12 connections)
- **run_demo()** (11 connections) — `src/pair_harness/cli.py`
- **str** (11 connections)
- **AppPaths** (10 connections) — `src/pair_harness/app_paths.py`
- **main()** (9 connections) — `src/pair_harness/cli.py`
- **context.py** (9 connections) — `src/pair_harness/core/context.py`
- **_console_approval()** (8 connections) — `src/pair_harness/cli.py`
- **TurnStatus** (6 connections) — `src/pair_harness/core/contracts.py`
- **_summary_context_text()** (5 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **settings.py** (5 connections) — `src/pair_harness/settings.py`
- **.default()** (4 connections) — `src/pair_harness/app_paths.py`
- **Path** (4 connections)
- **QueueIntent** (4 connections) — `src/pair_harness/core/contracts.py`
- **app_paths.py** (3 connections) — `src/pair_harness/app_paths.py`
- **.character_assets()** (3 connections) — `src/pair_harness/app_paths.py`
- **build_parser()** (3 connections) — `src/pair_harness/cli.py`
- **_configure_stdio_utf8()** (3 connections) — `src/pair_harness/cli.py`
- **Path** (3 connections)
- *... and 25 more nodes in this community*

## Relationships

- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (32 shared connections)
- [测试替身与集成夹具](测试替身与集成夹具.md) (28 shared connections)
- [审批裁决与审查智能体](审批裁决与审查智能体.md) (26 shared connections)
- [消息契约与会话编排](消息契约与会话编排.md) (26 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (17 shared connections)
- [语音运行时装配与中继](语音运行时装配与中继.md) (8 shared connections)
- [对话供应商与搭档配置](对话供应商与搭档配置.md) (7 shared connections)
- [账号语音服务测试](账号语音服务测试.md) (7 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (6 shared connections)
- [遗留登录与引擎装配](遗留登录与引擎装配.md) (5 shared connections)
- [SQLite 存储与队列恢复](SQLite_存储与队列恢复.md) (5 shared connections)
- [OpenAI 兼容对话解析](OpenAI_兼容对话解析.md) (5 shared connections)

## Source Files

- `src/pair_harness/__main__.py`
- `src/pair_harness/app_paths.py`
- `src/pair_harness/cli.py`
- `src/pair_harness/core/context.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/orchestrator.py`
- `src/pair_harness/desktop_backend/application_service.py`
- `src/pair_harness/desktop_backend/engine_factory.py`
- `src/pair_harness/settings.py`

## Audit Trail

- EXTRACTED: 189 (63%)
- INFERRED: 113 (37%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*