# Pair Harness MVP 实现计划

- 日期：2026-08-10
- 设计依据：`docs/superpowers/specs/2026-08-10-roleplay-coding-harness-design.md`
- 当前阶段：实现计划待用户确认
- 实施原则：先完成白厄单组闭环，再接真实外部服务，最后扩展另外两组

## 1. 状态说明

| 标记 | 含义 |
|---|---|
| ✅ | 已完成并验证 |
| 🟦 | 当前条件已满足，可以立即实施 |
| ⏳ | 等待用户提供外部条件 |
| ⬜ | 前置完成后实施 |

## 2. 当前环境与前置条件

| 项目 | 状态 | 当前结果 |
|---|---|---|
| 设计文档 | ✅ | 已确认并提交 |
| Git 仓库 | ✅ | `main` 分支可用 |
| Python | ✅ | 3.11.4 |
| PyQt5 | ✅ | 5.15.11，Qt 5.15.2 |
| qasync | ✅ | 0.28.0，已安装并可导入 |
| sounddevice | ✅ | 0.5.5，已安装并检测到默认输入/输出设备 |
| pytest | ✅ | 当前环境可用 |
| Codex app-server | ⏳ | WindowsApps 中能发现 `codex.exe`，当前终端启动时报“拒绝访问” |
| 角色对话 API | ⏳ | 等待 base URL、API Key 和模型名 |
| DashScope API | ⏳ | 等待 `DASHSCOPE_API_KEY` 与服务地域配置 |
| 白厄参考语音 | ⏳ | 等待 10–20 秒干净语音或已创建的 `voice_id` |
| 神秘古代机械参考语音 | ⏳ | 等待 10–20 秒干净语音或已创建的 `voice_id` |
| 另外四套参考语音 | ⬜ | 只在扩展另外两组搭档前需要 |

## 3. 两个闭环的边界

### 3.1 当前可实现闭环

当前可以完成一个真实可运行的本地桌面应用：

```text
PyQt5 界面
→ 项目与新旧聊天
→ 白厄角色消息
→ 结构化 TaskRequest
→ 测试 CodingEngine 事件
→ 折叠工具卡片
→ ExecutionReceipt
→ 白厄结果回应
→ SQLite 恢复
```

这个闭环会真实运行界面、数据库和麦克风采集。角色回复、工具执行、ASR 与 TTS 使用可预测的测试适配器，因此不会调用真实模型，也不会修改项目文件。

当前状态：**🟦 未开始，可以立即实施。**

### 3.2 完整 MVP 闭环

完整 MVP 在当前闭环上替换真实适配器：

```text
真实角色对话 API
→ 角色结构化委派
→ Codex app-server 执行真实文件与命令工具
→ Qwen 流式 ASR/TTS
→ 六套角色与助手声音
→ 三组搭档独立切换
```

当前状态：**⏳ 未开始，等待 Codex app-server、API 配置和参考语音。**

## 4. 计划 A：当前可实现闭环

### A1. 仓库骨架与统一协议

状态：**🟦 未开始，可以立即实施**

新增文件：

- `pyproject.toml`
- `src/pair_harness/__init__.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/ports.py`
- `tests/unit/test_contracts.py`
- `tests/contract/test_ports.py`

实现内容：

- 定义不可变的 `Message`、`DialogueEvent` 和 `CharacterTurn`。
- 定义 `TaskRequestDraft`、`TaskAmendmentDraft` 和正式任务类型。
- 定义 `EngineEvent`、`ToolRun` 和 `EngineSessionRef`。
- 定义 `ExecutionReceipt` 与 `CharacterResultSummary`。
- 定义 `DialogueModel`、`CodingEngine`、`StateStore`、ASR、TTS 和 VAD 接口。
- `CodingEngine` 包含 `open_session`、`run_turn`、`cancel_turn`、`amend_turn` 和 `resolve_approval`。
- TTS 准入由 Orchestrator 根据消息身份与类型计算。

项目依赖与可选分组：

```toml
dependencies = ["pydantic", "PyYAML", "httpx"]

[project.optional-dependencies]
ui = ["PyQt5", "qasync"]
voice = ["numpy", "sounddevice", "onnxruntime", "dashscope"]
dev = ["pytest", "pytest-asyncio", "pytest-qt"]
```

当前全局 Python 环境已经验证 PyQt5、qasync 与 sounddevice 可用；A1 会创建项目自己的 `.venv`，后续安装都在该虚拟环境中进行。

验收命令：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_contracts.py tests\contract\test_ports.py
```

完成标准：协议字段、任务状态、不透明会话引用和可替换接口测试通过。

建议提交：`chore: scaffold pair harness core`

### A2. 白厄单组编排与测试适配器

状态：**🟦 未开始，可以立即实施**

新增文件：

- `config/pairs/phainon_ancient_machine.yaml`
- `config/prompts/characters/phainon.md`
- `config/prompts/assistants/ancient_machine.md`
- `src/pair_harness/config/pairs.py`
- `src/pair_harness/core/context.py`
- `src/pair_harness/core/engine_state.py`
- `src/pair_harness/core/orchestrator.py`
- `src/pair_harness/adapters/demo.py`
- `src/pair_harness/adapters/dialogue/openai_compatible.py`
- `src/pair_harness/cli.py`
- `tests/fakes.py`
- `tests/unit/test_pair_config.py`
- `tests/unit/test_dialogue_boundary.py`
- `tests/unit/test_task_lifecycle.py`
- `tests/unit/test_engine_state.py`
- `tests/unit/test_conversation_binding.py`

实现内容：

- 从旧项目只读迁移白厄角色卡所需的最小字段，新应用运行时不依赖旧仓库。
- `ScriptedDialogueModel` 输出 `speech.delta` 与结构化 `character.final`。
- `ScriptedCodingEngine` 输出固定的助手与工具事件。
- Orchestrator 给 Draft 补齐任务 ID、聊天 ID 与来源消息 ID。
- 普通角色正文无论包含命令、路径或 `@板砖`，只要没有 delegation，就不触发 CodingEngine。
- “直接交给助手”也归一化为正式 `TaskRequest`。
- 全局最多一个活动编程 turn，事件固定回到原聊天。
- 工具失败时，即使助手文本自称成功，最终回执仍为失败。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_pair_config.py tests\unit\test_dialogue_boundary.py tests\unit\test_task_lifecycle.py tests\unit\test_engine_state.py tests\unit\test_conversation_binding.py
.\.venv\Scripts\python.exe -m pair_harness.cli --demo --project . --message "请让古代机械创建 hello.txt"
```

CLI 演示必须依次输出：

```text
user → character → assistant/tool → assistant → character
```

演示需要明确标注“未执行真实文件工具”。

建议提交：`feat: add isolated roleplay orchestration`

### A3. Codex app-server 适配器的离线实现

状态：**🟦 未开始，可以立即实施；真实子进程联调等待计划 B**

新增文件：

- `src/pair_harness/settings.py`
- `src/pair_harness/adapters/codex/transport.py`
- `src/pair_harness/adapters/codex/codec.py`
- `src/pair_harness/adapters/codex/engine.py`
- `tests/fixtures/fake_codex_app_server.py`
- `tests/unit/test_codex_event_mapping.py`
- `tests/integration/test_codex_transport.py`

实现内容：

- `PAIR_HARNESS_CODEX_BIN` 保存 Codex 可执行文件路径或命令名；适配器固定追加 `app-server` 参数，不接收任意命令字符串。
- `JsonlProcessTransport` 负责子进程、请求关联和单一读取循环。
- `CodexCodec` 将原生通知转换为稳定 `EngineEvent`。
- `CodexAppServerEngine` 私有解析 `thread_id`，应用层只保存 `EngineSessionRef`。
- 实现取消、任务修改和审批响应通道。
- 进程退出转换为 `turn.failed`。
- 不实现任何 MCP 客户端、注册表、代理层或网关。

测试使用 `asyncio.Queue` 模拟 app-server，不启动真实 Codex。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_codex_event_mapping.py tests\integration\test_codex_transport.py
```

建议提交：`feat: add offline codex app-server adapter`

### A4. 最小 PyQt5 双模式界面

状态：**🟦 未开始，可以立即实施**

新增文件：

- `src/pair_harness/__main__.py`
- `src/pair_harness/ui/app.py`
- `src/pair_harness/ui/main_window.py`
- `src/pair_harness/ui/message_list.py`
- `src/pair_harness/ui/tool_card.py`
- `src/pair_harness/ui/input_bar.py`
- `src/pair_harness/ui/qt_bridge.py`
- `tests/ui/test_main_window.py`
- `tests/ui/test_tool_card.py`
- `tests/ui/test_input_bar.py`

实现内容：

- 使用 PyQt5 与 qasync。
- 首阶段只显示白厄与神秘的古代机械。
- 聊天模式使用全宽角色对话，目标固定为白厄。
- 协作模式恢复双栏和发送对象选择。
- 使用已经确认的蓝色与新铸青铜金配色。
- 用户、角色、助手、工具和系统消息具有不同视觉样式。
- 工具卡片以 `tool_call_id` 更新，默认折叠。
- 提供取消按钮和 app-server 原生审批卡片的占位交互。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ui,dev]"
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests\ui
.\.venv\Scripts\python.exe -m pair_harness --demo
```

建议提交：`feat: add pyqt5 roleplay workbench`

### A5. SQLite、项目与聊天恢复

状态：**🟦 未开始，可以立即实施**

新增文件：

- `src/pair_harness/core/repository.py`
- `src/pair_harness/storage/schema.sql`
- `src/pair_harness/storage/sqlite_store.py`
- `src/pair_harness/app_paths.py`
- `src/pair_harness/ui/project_library.py`
- `tests/unit/test_sqlite_store.py`
- `tests/integration/test_conversation_restore.py`

实现内容：

- 建立 `projects`、`conversations`、`messages`、`tool_runs` 和 `engine_sessions` 五张表。
- 项目绑定一个文件夹，每个项目保存多次聊天。
- 每条聊天固定一组搭档。
- 纯角色聊天延迟创建 `EngineSessionRef`。
- 只保存最终助手消息和最终工具卡片，不保存流式增量。
- 新聊天不继承旧聊天内容或编程会话。
- 项目路径失效时仍可查看历史。
- 项目与聊天库可以选择同一搭档的任意旧聊天。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_sqlite_store.py tests\integration\test_conversation_restore.py
.\.venv\Scripts\python.exe -m pair_harness --demo --data-dir .\.tmp\demo-data
```

关闭并重新运行第二条命令，消息和工具卡片必须恢复。

建议提交：`feat: persist projects and conversations`

### A6. 语音规则、麦克风层与测试语音闭环

状态：**🟦 未开始，可以立即实施**

新增文件：

- `src/pair_harness/core/audio.py`
- `src/pair_harness/core/voice_policy.py`
- `src/pair_harness/adapters/audio/sounddevice_io.py`
- `src/pair_harness/adapters/audio/demo.py`
- `src/pair_harness/ui/audio_controls.py`
- `tests/unit/test_input_matrix.py`
- `tests/unit/test_tts_filter.py`
- `tests/unit/test_speech_queue.py`
- `tests/ui/test_audio_controls.py`

实现内容：

- `sounddevice` 采集和播放层可以列出设备并采集 16 kHz 单声道 PCM。
- Demo ASR 接收注入文本，Demo TTS 产生测试音频或状态事件。
- VAD 使用测试事件验证监听、说话、结束和误触发状态。
- 聊天模式与“对角色说”显示 VAD、按键说话和文字。
- “直接交给助手”隐藏 VAD。
- 只有角色发言和助手自然语言进入 SpeechQueue。
- 命令、路径、代码、工具、审批和系统消息全部静音。
- 播放时暂停 VAD，按下说话键先停止播放。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ui,voice,dev]"
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_input_matrix.py tests\unit\test_tts_filter.py tests\unit\test_speech_queue.py tests\ui\test_audio_controls.py
.\.venv\Scripts\python.exe -m pair_harness --demo
```

计划 A 完成出口：

- 白厄单组桌面应用可以完整演示。
- 项目与聊天可以创建、切换和恢复。
- 角色无法越过助手产生工具事件。
- 工具卡片、任务结果和角色回应形成闭环。
- 麦克风层与全部语音交互状态可演示。
- 所有测试使用测试适配器，不依赖外部 API。

建议提交：`feat: add demo voice interaction loop`

## 5. 计划 B：完整 MVP 闭环

### B1. 真实角色对话 API 与 Codex app-server

状态：**⏳ 未开始，等待外部前置**

用户需要准备：

- 可以由 Python `subprocess` 启动的 Codex app-server 命令。
- Codex 的本地登录或认证状态。
- 角色对话 API 的 base URL、API Key 和模型名。

配置项：

```text
PAIR_HARNESS_CODEX_BIN
PAIR_HARNESS_DIALOGUE_BASE_URL
PAIR_HARNESS_DIALOGUE_API_KEY
PAIR_HARNESS_DIALOGUE_MODEL
```

新增测试：

- `tests/integration/test_text_loop_live.py`

实施内容：

- 对可执行命令运行 `app-server --help` 预检。
- 真实创建和恢复 app-server 会话。
- 在临时项目内执行一次真实文件修改任务。
- 验证工具事件、文件差异和真实回执。
- 让白厄只依据 `CharacterResultSummary` 作结果回应。

验收命令：

```powershell
$env:PAIR_HARNESS_CODEX_BIN = "C:\可执行路径\codex.exe"
$env:PAIR_HARNESS_DIALOGUE_BASE_URL = "..."
$env:PAIR_HARNESS_DIALOGUE_API_KEY = "..."
$env:PAIR_HARNESS_DIALOGUE_MODEL = "..."

New-Item -ItemType Directory -Path .\.tmp\codex-smoke -Force | Out-Null
.\.venv\Scripts\python.exe -m pair_harness.cli --real --pair phainon_ancient_machine --project .\.tmp\codex-smoke --message "请让古代机械创建 hello.txt，内容为 hello"
Get-Content -LiteralPath .\.tmp\codex-smoke\hello.txt
```

完成标准：真实文件存在，旧聊天可以恢复同一编程会话，新聊天不会继承旧会话。

建议提交：`feat: connect live dialogue and codex backends`

### B2. Silero VAD 与 Qwen 流式 ASR/TTS

状态：**⏳ 未开始，等待外部前置**

用户需要准备：

- `DASHSCOPE_API_KEY`。
- 服务地域和对应 WebSocket 地址。
- 白厄与神秘古代机械的参考语音，或已经创建的两个 `voice_id`。

新增文件：

- `src/pair_harness/adapters/audio/silero_vad.py`
- `src/pair_harness/adapters/audio/qwen_asr.py`
- `src/pair_harness/adapters/audio/qwen_tts.py`
- `scripts/create_qwen_voice.py`
- `tests/unit/test_asr_merge.py`
- `tests/unit/test_vad_state.py`
- `tests/unit/test_qwen_event_mapping.py`
- `tests/integration/test_qwen_audio_live.py`

实施内容：

- Python 端重新实现 Silero VAD，不复制浏览器 TypeScript/WASM。
- 初始阈值采用 `0.45`，保留开口前音频和最短语音判断。
- 接入 `qwen-audio-3.0-asr-flash-streaming`。
- 接入 `qwen-audio-3.0-tts-flash`。
- 参考旧项目的 ASR 增量合并、PCM 回调与结束事件。
- 一次性脚本根据本地参考语音创建 `voice_id`，应用运行时只消费 voice ID。
- 空转写不发送，TTS 播放时暂停 VAD。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_asr_merge.py tests\unit\test_vad_state.py tests\unit\test_qwen_event_mapping.py
$env:RUN_LIVE_QWEN = "1"
.\.venv\Scripts\python.exe -m pytest -q -m live_qwen tests\integration\test_qwen_audio_live.py
.\.venv\Scripts\python.exe -m pair_harness --real
```

人工验收：

- VAD 识别完成后自动发送给白厄。
- 按键说话可以打断 TTS。
- “直接交给助手”不出现 VAD。
- 角色和助手自然语言使用各自声音。
- 命令、路径、代码和工具卡片保持静音。

建议提交：`feat: connect qwen streaming voice`

### B3. 扩展流萤、萨姆、三月七与第四面镜

状态：**⬜ 等待 B1、B2 完成**

开始前还需要：

- 流萤、萨姆、三月七和第四面镜的主题颜色。
- 四套参考语音或已创建的 `voice_id`。

新增文件：

- `config/pairs/firefly_sam.yaml`
- `config/pairs/march7_fourth_mirror.yaml`
- `config/prompts/characters/firefly.md`
- `config/prompts/characters/march7.md`
- `config/prompts/assistants/sam.md`
- `config/prompts/assistants/fourth_mirror.md`
- `tests/unit/test_pair_isolation.py`
- `tests/ui/test_pair_switching.py`

实施内容：

- 只增加配置和参数化测试，不复制编排、界面或音频逻辑。
- 三组搭档可以分别创建新聊天。
- 每条聊天固定创建时选择的搭档。
- 切换时同步更新名字、主题和声音。
- 三组输入矩阵、工具权限和 TTS 规则一致。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m pair_harness --real
```

完整 MVP 完成出口：

- 三组搭档的聊天、声音和执行上下文互不串线。
- 项目、新旧聊天与 app-server 会话可以恢复。
- 真实角色委派可以驱动真实文件和命令工具。
- Qwen 流式 ASR/TTS 与本地 VAD 完成闭环。
- 所有已确认的身份、输入矩阵和静音规则通过验收。

建议提交：`feat: add all companion pairs`

## 6. 用户准备清单

### 启动 B1 前

- [ ] 提供可从终端启动的 Codex app-server 命令或可执行路径。
- [ ] 确认 Codex 已登录。
- [ ] 在本地 `.env` 中填写角色对话 API 配置。

### 启动 B2 前

- [ ] 在本地 `.env` 中填写 DashScope API 配置。
- [ ] 提供白厄参考语音文件。
- [ ] 提供神秘古代机械参考语音文件。
- [ ] 确认两份语音可以用于本项目的音色创建。

### 启动 B3 前

- [ ] 确认另外两组搭档的主题颜色。
- [ ] 提供另外四套参考语音或 voice ID。

## 7. 当前完成状态

| 阶段 | 状态 | 进度 |
|---|---|---:|
| 设计与初始化 | ✅ 完成 | 100% |
| 环境依赖检查 | ✅ 完成 | 100% |
| qasync 与 sounddevice 安装 | ✅ 完成 | 100% |
| 计划 A：当前可实现闭环 | 🟦 可开始 | 0% |
| B1：真实角色 API + Codex | ⏳ 等待外部前置 | 0% |
| B2：Qwen 语音 | ⏳ 等待外部前置 | 0% |
| B3：另外两组搭档 | ⬜ 后续 | 0% |

## 8. 明确不进入计划

- 自定义 MCP 网关、统一代理层或工具市场
- 复杂多 Agent 和动态拓扑
- 永久自治或自动生成目标
- RBAC、审计平台和遥测体系
- 容器集群和微服务
- Electron、React 和 3D/MMD 链路
- 自动长期记忆和大规模测试矩阵
