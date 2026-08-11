# Tauri 桌面迁移基线

- 日期：2026-08-11
- 基线提交：`d7e365f`
- 基线分支：`main`
- 逻辑迁移分支：`codex/tauri-logic`
- 逻辑 worktree：`.worktrees/tauri-logic`
- 当前工作树：创建 worktree 前干净，无用户未提交或未跟踪改动
- React/Tauri 目录：基线尚不存在 `desktop/`

## Python 基线

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：`327 passed, 3 failed, 3 skipped`（约 27 秒）。

失败项是基线环境事实：

- `tests/integration/test_text_loop_live.py::test_live_cli_creates_file_and_resumes_thread`
  与 `test_live_deepseek_roleplay_boundaries_are_stable`：需要外部 DeepSeek 连接，当前连接失败。
- `tests/ui/test_theme.py::test_theme_preference_roundtrip`：当前运行环境中的主题偏好读回 `dark` 而非测试写入的 `light`。

3 个跳过项属于原有环境条件测试。迁移新增测试使用测试适配器，不以外部凭据为前置条件。

## 当前入口与权威状态

| 能力 | 当前入口/权威实现 | 基线状态 |
|---|---|---|
| 深浅主题切换 | `src/pair_harness/ui/theme.py`、`tests/ui/test_theme*.py` | 已有 PyQt 入口；默认深色与品牌色有测试覆盖 |
| 项目创建与切换 | `src/pair_harness/ui/app.py`、`ui/project_library.py`、`storage/sqlite_store.py` | 已实现 |
| 多聊天创建、选择、恢复 | `ui/app.py`、`storage/sqlite_store.py`、`core/orchestrator.py` | 已实现 |
| 固定搭档 | `config/pairs/`、`config/pairs.py`、SQLite `pair_id` | 白厄 + 古代机械当前可用 |
| 日常聊天 | SQLite `project_id IS NULL` 能力存在；PyQt 入口当前只创建项目聊天 | 数据层可表达，入口未提前扩展 |
| 聊天模式 | `ConversationOrchestrator.handle_character_input` | 已实现，角色聊天不创建任务 |
| 协作模式 | `MainWindow`、`InputBar`、`ConversationOrchestrator` | 已实现 |
| 默认发送给角色 / 直接交给助手 | `VoiceRuntime`、`InputBar`、`ui/app.py` | 已实现 |
| 角色委派 | `DialogueModel` 返回 `TaskRequestDraft`，编排器执行 | 已实现 |
| 工具记录 | `ToolRun`、`SQLiteStore.save_tool_run`、`ToolCard` | 已实现，按 `tool_call_id` 更新 |
| 单一活动 turn | `GlobalEngineState` | 已实现 |
| 任务取消与 amendment | `ConversationOrchestrator`、`CodingEngine` | 已实现 |
| 三种审批模式 | `ApprovalManager`、风险规则和审查适配器 | 已实现 |
| 推理档位 | `projects.reasoning_effort`、对话适配器 | 已实现 |
| ASR / TTS / VAD | `VoiceRuntime` 与 `adapters/audio/` | 测试适配器和真实适配器均已存在 |
| TTS 静音边界 | `core/voice_policy.py` | 已实现并有测试覆盖 |
| SQLite 历史数据 | `storage/schema.sql`、`sqlite_store.py` | 版本迁移为 3，语义保留 |
| 路径失效提示 | `repository.Project.path_available`、PyQt 项目导航 | 核心字段已存在，React 需提供等价入口 |
| 流式消息与工具更新 | `on_message`、`on_engine_event`、Qt bridge | 已实现；React 侧需按稳定 ID 归并 |
| 思考内容 | `Message.payload`、`EngineEventType.ASSISTANT_REASONING_DELTA` | 已实现，React 默认折叠 |

## 迁移边界

- PyQt 入口在候选版验收前保留；本阶段不删除 `src/pair_harness/ui/**`。
- Python 核心、适配器、SQLite 和语音配置继续作为业务权威，不复制数据库、不重写 schema。
- `E:\AI\二次元情感陪伴助手` 只读。
- 本阶段不加入 3D、MMD、WebGL、换装、相册、新搭档内容或完整 IDE 文件浏览器。
