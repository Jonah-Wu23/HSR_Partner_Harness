# HSR Partner Harness 架构文档

版本：0.2.0（V0.2 M4 基线）
适用范围：桌面应用（Tauri + React + Python Sidecar）整体架构
关键词：Sidecar JSONL 协议、编排器、引擎适配器、审批、语音、账号隔离

---

## 1. 概述

HSR Partner Harness 是一个「角色扮演 × 编程助手」的桌面应用。用户与一个
角色（character）对话，角色可以委派本地编程助手（assistant，产品内称
"古代机器"）执行真实项目任务；任务中的工具操作经过沙箱与审批闸门；
助手与角色的回复支持流式展示、思考链展示与语音朗读。

核心设计决策：

| 决策 | 内容 |
| --- | --- |
| 三进程结构 | Tauri 桌面壳（Rust）+ React 前端 + Python Sidecar（业务权威） |
| Python 业务权威 | 模型调用、状态机、审批、存储全部由 Sidecar 决定；前端是纯视图层 |
| JSONL over stdio | Sidecar 协议为换行分隔 JSON，请求/响应/事件三通道 |
| 事件序号契约 | 所有事件单调递增序号，前端按序号对账，断线重连后重新水合 |
| 引擎可插拔 | 编程引擎通过 `CodingEngine` 端口抽象：Codex app-server / DeepSeek-Reasonix ACP / 脚本演示 |
| 快速接受 | 用户消息同步落库立即返回真实 id，回合在后台任务推进 |
| 本地优先 | 所有数据存本机 SQLite，账号/密钥/引擎数据目录按账号隔离 |

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        桌面进程（单个可执行文件）                      │
│                                                                     │
│  ┌───────────────────────┐        ┌──────────────────────────────┐  │
│  │   React 前端           │        │   Rust 壳（Tauri v2）          │  │
│  │                        │        │                              │  │
│  │  AppController         │        │  main.rs                     │  │
│  │   └─ Zustand store     │        │   ├─ 启动/重启 Sidecar        │  │
│  │   └─ presenters        │        │   ├─ 请求转发（stdin）         │  │
│  │   └─ UI 组件           │        │   ├─ 事件转发（stdout→event）  │  │
│  │                        │        │   ├─ 崩溃检测 + 退避重连       │  │
│  │   tauriDesktopBackend  │        │   └─ 资源发现（sidecar/codex/ │  │
│  │   (invoke 桥)          │        │       reasonix 二进制）        │  │
│  └──────────┬────────────┘        └──────────────┬───────────────┘  │
│             │  Tauri invoke                          │  stdin/stdout │
│             ▼                                       ▼               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              Python Sidecar（PyInstaller 单目录打包）           │   │
│  │                                                              │   │
│  │  desktop_backend ── 协议层：commands / events / service       │   │
│  │        │                                                     │   │
│  │        ▼                                                     │   │
│  │  core ── 业务权威：orchestrator / approval / sandbox /        │   │
│  │           risk_rules / engine_state / voice_runtime           │   │
│  │        │                                                     │   │
│  │        ├──► adapters/dialogue ── 角色对话模型（流式）           │   │
│  │        ├──► adapters/codex ── Codex app-server 引擎           │   │
│  │        ├──► adapters/acp ── DeepSeek-Reasonix ACP 引擎        │   │
│  │        ├──► adapters/audio ── Qwen ASR/TTS 语音               │   │
│  │        └──► storage ── SQLite（账号/项目/会话/消息/队列）        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────── 外部服务（进程外）────────────────────────────┐    │
│  │  Codex app-server（codex.exe 子进程）                          │    │
│  │  reasonix acp（DeepSeek-Reasonix 子进程）                      │    │
│  │  DeepSeek / OpenAI 兼容 HTTP API（角色对话）                   │    │
│  │  DashScope（阿里云百炼 Qwen ASR/TTS WebSocket）                │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

三层职责划分：

- **Rust 壳**：只管进程生命周期。拉启 Sidecar、转发 JSONL、崩溃退避重连、
  发现打包的内置二进制（`packaged_sidecar/codex/reasonix`）并注入环境变量。
  不接触业务逻辑。
- **React 前端**：渲染与交互。Store 按序号水合事件，Presenter 把状态投影为
  视图模型，UI 组件纯展示。不持有业务权威。
- **Python Sidecar**：全部业务逻辑。协议命令路由、编排状态机、模型适配、
  审批裁决、语音运行时、SQLite 持久化。

---

## 3. 进程模型与 Sidecar 协议

### 3.1 进程生命周期

```
        启动                    崩溃                    正常退出
  ┌─────────────┐        ┌─────────────────┐        ┌──────────────┐
  │ Tauri 启动   │        │ Sidecar 异常退出  │        │ app.shutdown │
  │ spawn sidecar│        │ reader EOF       │        │ 命令         │
  │ (--real/    │        │ 分类：Crash       │        │ → stdin 写入 │
  │  --demo)    │        │ → 广播 disconnected│        │ → kill       │
  │             │        │ → 退避重连循环      │        │ → 不再重连   │
  └──────┬──────┘        │   1s 2s 4s … 15s  │        └──────────────┘
         │               └─────────────────┘
         ▼
  frontend: booting → bootstrap 水合 → ready
```

- 启动参数：`--real`（加载 `.env` 的真实模式）或 `--demo`（脚本演示）；
  `--project <root>` 指定项目目录。
- `.env` 发现顺序：`PAIR_HARNESS_ENV_FILE` → 仓库根/当前目录/可执行文件
  同目录 → `%LOCALAPPDATA%\PairHarness\.env` → 应用配置/数据目录。
- 找到 `.env` 即真实模式；找不到回退 demo 模式。

### 3.2 JSONL 协议

每行一个 JSON 对象，三种 kind：

```
请求（前端 → Sidecar，stdin）
  {"kind":"request","id":"r1","method":"chat.submit","params":{...}}

响应（Sidecar → 前端，stdout，按 id 对账）
  {"kind":"response","id":"r1","ok":true,"result":{...}}
  {"kind":"response","id":"r1","ok":false,"error":{"code":"...","message":"..."}}

事件（Sidecar → 前端，stdout，广播）
  {"kind":"event","event":"message.created","sequence":42,"payload":{...}}
```

- **序号契约**：`EventEmitter` 为每个事件分配单调递增 `sequence`；
  `bootstrap()` 快照携带 `sequence = next_sequence - 1`，前端以该值为
  `lastSequence`，下一条事件必须严格 `+1`，否则丢弃并置
  `needsBootstrap` 请求重新水合。Rust 侧合成分发的事件（重连状态等）
  也参与同一序号空间，断线-重连不断层。
- 命令全集见 `desktop_backend/commands.py`（约 40 个方法），分为
  项目/会话/聊天/队列/任务/审批/语音/账号/配置/认证十组。
- 长任务不阻塞通道：`chat.submit` 同步落库后立即返回，回合在 Sidecar
  后台任务推进，结果以事件流出。

---

## 4. 前端架构（desktop/src）

```
src/
├── main.tsx                入口；ErrorBoundary 兜底（渲染崩溃不再白屏）
├── app/
│   └── AppController.tsx   根组件：订阅 store → presenter → 渲染树
├── contracts/
│   ├── protocol.ts         协议类型：命令/事件/快照/领域模型
│   ├── view-models.ts      视图模型类型
│   └── actions.ts          前端 action 类型
├── services/
│   ├── backend.ts          DesktopBackend 端口
│   ├── tauriDesktopBackend invoke 桥（真实）
│   ├── mockDesktopBackend  脚本后端（预览/测试）
│   ├── eventBatcher.ts     事件批量应用
│   └── actions.ts          动作控制器：命令 → store 状态
├── stores/
│   └── desktopStore.ts     Zustand store：事件投影 + 快照水合
├── presenters/
│   └── presenters.ts       状态 → 视图模型投影（消息分栏、会话列表等）
└── ui/                     组件：导航/工作台/审批栏/设置/引导/状态
```

数据流单向：

```
UI 动作 ──► actions.request(command) ──► invoke ──► Sidecar
                                                    │
UI 渲染 ◄── presenters(store) ◄── applyEvents ◄── sidecar://event
```

- **事件投影**（`desktopStore.applyEvents`）：`message.delta` 创建/更新
  流式消息（`streaming: true`），`message.finalized`/`message.created`
  终结；`turn.started`/`turn.status_changed` 推进回合生命周期；失败/
  取消回合会清掉该会话所有 streaming 占位，避免"三个点"卡死。
- **消息空间归属**：不按 source 切栏，而是按归属——
  `user+target=character`、`character`、`system` 归角色区；
  `user+target=assistant`、`assistant`、`tool` 归工作台。
- **对账式更新**：后端设置类命令返回定向响应（裁剪 payload），store
  与现有记录合并（如 `project.changed` 保留 `conversations`），不整份
  覆盖，避免渲染层字段丢失。

---

## 5. Python Sidecar 分层

```
src/pair_harness/
├── cli.py                    命令行入口（--demo/--real/--project）
├── settings.py               环境变量设置（对话/Codex/语音）
├── app_paths.py              数据目录（%LOCALAPPDATA%\PairHarness）
├── desktop_backend/          桌面协议层
│   ├── __main__.py           sidecar 主循环（stdin→命令→stdout）
│   ├── commands.py           命令白名单与校验
│   ├── events.py             事件发射器（序号分配）
│   ├── application_service.py 命令路由 + 状态快照 + 事件转发
│   ├── engine_factory.py     引擎工厂（codex/deepseek 选择与配置）
│   └── voice_factory.py      语音运行时工厂
├── core/                     业务权威
│   ├── orchestrator.py       会话编排器（角色回合/执行回合/队列）
│   ├── contracts.py          领域模型（pydantic）
│   ├── ports.py              端口抽象（DialogueModel/CodingEngine/...）
│   ├── approval.py           审批管理器（模式/审查/会话缓存）
│   ├── sandbox.py            项目沙箱（写路径越界校验）
│   ├── risk_rules.py         高风险操作规则表
│   ├── engine_state.py       全局引擎状态（活动任务/生命周期）
│   ├── repository.py         项目仓库模型
│   ├── context.py            近期对话上下文
│   ├── voice_policy.py       可朗读文本判定
│   └── voice_runtime.py      语音运行时（VAD→ASR→TTS 流水线）
├── adapters/                 外部依赖适配
│   ├── dialogue/             角色对话模型（OpenAI 兼容流式）
│   ├── codex/                Codex app-server 引擎 + 认证 + 传输
│   ├── acp/                  DeepSeek-Reasonix ACP 引擎
│   ├── audio/                Qwen ASR/TTS 客户端
│   ├── demo.py               脚本演示引擎/对话模型
│   └── reviewer.py           审查智能体（对话模型包装）
├── config/                   静态配置加载
│   ├── pairs.py              pair YAML（角色/助手/主题）
│   └── providers.py          供应商识别与推理档位预设
└── storage/
    ├── schema.sql            建表脚本
    └── sqlite_store.py       SQLite 存储（迁移/查询/快照）
```

### 5.1 桌面协议层（desktop_backend）

`DesktopApplicationService` 是 Sidecar 的"门面"：把 JSONL 命令映射到
编排器调用，把编排器的消息/事件回调映射为协议事件。关键职责：

- 命令路由（`handle_command` → 40+ 处理器）；
- `bootstrap()` 完整快照（项目/会话/消息/回合/队列/审批/语音/pair）；
- 后台回合管理：`chat.submit` 快速接受 → `_run_submit_chain` 后台任务 →
  Turn 生命周期事件（accepted → running → completed/failed/cancelled）；
- 队列自动派发链：回合完成后自动派发 `conversation_inbox` 下一条；
- 对话流转发：角色思考/正文增量 → `message.delta`（reasoning/speech
  通道共用 `speech:{conversation}:{message_id}` 占位 id）；
- 引擎事件转发：助手文本/思考增量、工具卡片、审批请求；
- 失败收尾：回合失败时补发 `message.finalized`，前端气泡不卡"三点"。

### 5.2 编排器（core/orchestrator.py）

编排器是业务核心状态机，两个主入口：

```
                       ┌──────────────────────────────┐
  chat.submit ────────►│ process_character_turn       │
  (target=character)   │  1. 会话锁内：对话模型流式回复 │
                       │     → 思考/正文增量事件        │
                       │  2. character.final 落库台词   │
                       │  3. 有委派 → _execute 执行     │
                       │  4. 执行结果 → 角色结果回应     │
                       └──────────────┬───────────────┘
                                      ▼
                       ┌──────────────────────────────┐
  chat.submit ────────►│ process_direct_input         │
  (target=assistant)   │  无活动任务 → 新建 TaskRequest │
                       │  活动任务中   → 归一 TaskAmendment│
                       │    （steer 运行中回合）         │
                       └──────────────┬───────────────┘
                                      ▼
                       ┌──────────────────────────────┐
                       │ _execute(task)               │
                       │  state.start → busy          │
                       │  open_session（恢复或新建）    │
                       │  事件循环：                   │
                       │   工具 → 沙箱 → 审批门控       │
                       │   原生审批 → 裁决 → 回复引擎    │
                       │   文本/思考增量 → 转发          │
                       │  结束 → 回执 + 角色结果回应      │
                       └──────────────────────────────┘
```

回合内事件序号由编排器统一分配（不信任适配器自带序号），审批合成事件
与引擎事件在同一计数器下连续。

### 5.3 审批链

```
引擎工具事件（tool.started / requestApproval）
        │
        ▼
  沙箱检查（写路径越界 → 直接否决）
        │
        ▼
  ApprovalManager（按项目审批模式）
   ├─ request_approval  每次操作挂起 → ApprovalBroker → 前端审批栏 → 用户裁决
   ├─ review            低风险 → 审查智能体自动放行；高风险 → 用户审批
   │                    （reviewer = 对话模型包装，只在高风险时调用）
   └─ full_auto         never/yolo，不发起审批请求
        │
        ▼
  裁决经 resolve_approval 回复引擎（codex: decision 字段；
  reasonix: outcome.selected + optionId）→ 引擎继续/拒绝
```

- `risk_rules.yaml`：高风险操作规则表（文件删除、git 破坏性命令、网络、
  依赖安装、系统级命令、批量 patch、敏感路径），只在"帮我审核"模式下
  生效；"请求批准"模式所有操作都走人工审批。
- 审批通过/否决以 `system.approval` 卡片留在消息时间线。

### 5.4 队列（conversation_inbox）

忙碌时提交的消息先入队持久化（`queued`），回合完成后自动派发
（`processing` → 新回合 → 完成删除；失败退回 `queued` 可重试，停止
继续派发）。`intent`：`followup` 追加 / `steer` 置队首（立即插入）。

---

## 6. 引擎适配器

编程引擎统一实现 `CodingEngine` 端口：

```
CodingEngine
├── open_session(project, stored_ref, approval_policy, sandbox, ...)
├── run_turn(session, request) → AsyncIterator[EngineEvent]
├── cancel_turn(session, turn_id)
├── amend_turn(session, engine_turn_id, amendment)
├── resolve_approval(session, approval_id, decision)
└── native_preexecution_approval: bool   # 是否原生执行前审批
```

### 6.1 Codex app-server（默认引擎）

```
Tauri ──注入 PAIR_HARNESS_BUNDLED_CODEX_BIN──► codex.exe app-server
        （resources/codex/bin/codex.exe，npm 包原生发行目录）

JsonlProcessTransport（一行 JSON-RPC 一条消息）
  ├─ 请求/响应按 id 关联（pending map）
  ├─ 服务端请求（requestApproval 带 id）→ 通知队列 → 调用方 respond()
  └─ 坏行容错：单行坏 JSON 只跳过计数，不断开

认证：CodexAuthService（账号隔离的 CODEX_HOME/auth.json）
  ├─ OpenAI 浏览器 OAuth（start_login 等待官方流程）
  └─ API Key 直写（api_login）
```

事件映射（codec）：`item/started` → tool.started；`item/completed`
→ tool.finished / file.patch；`requestApproval` 三态
（commandExecution/fileChange/permissions）→ approval.requested；
`turn/completed` → turn.completed/failed。

### 6.2 DeepSeek-Reasonix ACP（deepseek 引擎）

```
Tauri ──注入 PAIR_HARNESS_BUNDLED_REASONIX_BIN──► reasonix.exe acp
        （resources/reasonix/bin/reasonix.exe，npm 官方安装）
        env: REASONIX_HOME = base_dir/accounts/{account}/reasonix/
            （config.toml：provider 端点与模型；
              .env：DEEPSEEK_API_KEY）
```

- reasonix 不从进程环境变量读 provider 配置：`config.toml` 定义
  base_url/model，`.env` 存放 `api_key_env` 指向的密钥；
- ACP v1 事件统一封装为 `session/update` 通知，类型在
  `params.update.sessionUpdate`：`agent_message_chunk` /
  `agent_thought_chunk` / `tool_call` / `tool_call_update` / `plan`；
- `session/request_permission` 是服务端请求（带 id），回复必须是
  `{"outcome": {"outcome": "selected", "optionId": "allow_once"|"allow_always"|"reject_once"}}`；
- `session/cancel` 是 notification（无 id），经 `transport.notify` 发送；
- 审批映射：编排器 `never`（完全允许）→ `yolo`，其余 → `ask`；
- `native_preexecution_approval = True`：原生执行前审批，避免双重门控。

### 6.3 演示引擎（demo 模式）

`ScriptedCodingEngine` / `ScriptedDialogueModel`：无需外部凭据的脚本
流程，用于离线验收三种审批模式与界面。

---

## 7. 角色对话模型与输出协议

`OpenAICompatibleDialogueModel`（DeepSeek / 任何 OpenAI 兼容端点）流式
调用 `/chat/completions`：

```
角色回合请求装配：
  system = 角色卡 + 搭档表达配置 + 运行时输出协议（JSON 单对象约定）
  messages = 近期对话（user/character 互转）
  可选注入：任务进度摘要 / 执行结果摘要 / 项目运行上下文
  user = 用户消息
  extras（DeepSeek 专属）：
    thinking = {enabled|disabled}，reasoning_effort = 档位
    response_format = json_object（避免流式分块解析失败）
```

输出解析双通道：

```
reasoning_content ──► reasoning.started/delta/completed（思考链）
content ──► IncrementalJsonSpeechParser ──► speech.started/delta/completed
         └► 完整原文 → _parse_output：
              {"speech": "...", "delegation": {"type":"task"|"amendment", ...}}
              解析失败 → 降级纯台词（原始 JSON 不进气泡/不朗读）
```

能力边界（确定性兜底）：模型漏掉委派时按用户指令形成结构化委派；
"我来执行"类自述被改写为交托助手；结果回应以回执状态为准，禁止
成功/失败倒置。

标题生成：`generate_title` 用助手身份非流式短请求（2–16 字）；对推理
模型显式关闭思考（`thinking: disabled`）+ 充足 token 预算，空内容时
放大预算重试，避免思考耗尽 token 导致标题静默失败。

---

## 8. 语音流水线

```
┌────────────────────────────────────────────────────────────┐
│ VoiceRuntime（core/voice_runtime.py）                        │
│                                                            │
│  麦克风 ─► VAD（静音段检测） ─► Qwen ASR（流式转写）            │
│                                   │ partial/final           │
│                                   ▼                         │
│                             文本 → 提交为消息（target 角色/助手）│
│                                                            │
│  消息落库 ─► TTS 资格判定（voice_policy：仅自然语言朗读）       │
│                ├─► Qwen TTS（流式合成）→ 播放队列 → 扬声器      │
│                └─► 命令输出/工具记录保持静音                    │
└────────────────────────────────────────────────────────────┘
```

- 模型：`qwen-audio-3.0-asr-flash-streaming`（ASR）、
  `qwen-audio-3.0-tts-flash`（TTS），DashScope 专属端点；
- 交互模式：自动 VAD 聆听 + 按住说话（PTT）两种；
- 音色：pair 内置角色/助手两个 `voice_id`，试听只允许这两个；
- 语音不可用（缺 Key/网络）不阻塞文本主线，错误以 toast 呈现。

---

## 9. 存储与数据模型

数据库：`%LOCALAPPDATA%\PairHarness\pair_harness.db`（SQLite）。
核心表：

```
accounts ──┬── account_preferences（主题/VAD/模式）
           ├── provider_configs（账号级非密钥配置：引擎/端点/模型）
           ├── secret_refs（账号级密钥，单机明文 + 掩码回显）
           └── projects（归属账号）
                 └── conversations（pair_id、last_mode）
                       ├── messages（message_json 全文）
                       ├── tool_runs（工具卡片记录）
                       ├── engine_sessions（会话恢复引用）
                       └── conversation_inbox（忙碌队列）
app_state（应用级单值：当前账号等）
```

- 迁移：`sqlite_store.SCHEMA_VERSION` 逐级执行（user_version 驱动）；
  新库由 `schema.sql` 建全表；
- 消息/工具以 `*_json` 列存整对象（pydantic model_dump），查询按
  conversation 顺序索引；
- 引擎会话恢复：`engine_sessions` 保存 `EngineSessionRef`
  （codex thread_id / acp session_id 的 base64 编码），重开会话走
  resume/thread 恢复而非重放。

---

## 10. 账号、配置与隔离

```
每个本地账号（accounts）拥有独立的：
  ├─ 项目/会话/消息数据（projects.account_id）
  ├─ 配置（provider_configs：engine / dialogue.* / voice.enabled / vad_enabled）
  ├─ 密钥（secret_refs：dialogue.api_key / voice.api_key）
  ├─ Codex 数据目录（CODEX_HOME = base/accounts/{id}/codex）
  └─ Reasonix 配置目录（REASONIX_HOME = base/accounts/{id}/reasonix）
```

- 认证：本地账号密码 PBKDF2 派生存储；登录/切换账号重建模型与引擎
  运行时（`_rebuild_runtime_for_account`），账号级配置覆盖环境默认；
- 引擎选择：`engine` = `codex`（默认）或 `deepseek`；
  对话服务商 = `openai_oauth`（Codex 认证）或 OpenAI 兼容 API
  （DeepSeek 等，provider 自动识别）；
- 环境变量 → 账号配置的覆盖顺序：显式传入 > 账号配置 > 环境变量 >
  内置默认；
- 推理档位：项目级 `reasoning_effort`（low/medium/high/xhigh/max），
  按供应商预设归一化（DeepSeek Flash 的 medium/xhigh → high 等），
  非法档位不写入请求体。

---

## 11. 关键流程时序

### 11.1 启动与引导

```
前端             Rust 壳            Sidecar
 │  invoke app.bootstrap             │
 ├───────────────► 写入 stdin ───────► 构建服务（读取账号配置）
 │                  │                │  bootstrap()：完整快照 + 序号
 │  state.snapshot ◄── stdout 事件 ◄─┤  emit(state.snapshot)
 │  (sequence 对齐, 水合 store)       │
 │  引导未完成 → 引导页 → account.onboarding_complete
```

### 11.2 角色聊天回合（含委派执行）

```
前端            Service           Orchestrator       DialogueModel     CodingEngine
 │ chat.submit │                   │                     │                 │
 ├────────────►│ 同步落库用户消息    │                     │                 │
 │ ◄──立即返回  │ 注册 Turn(accepted)│                     │                 │
 │  (message_id)│ 后台任务启动        │                     │                 │
 │             ├──► process_character_turn ─► stream_reply                     │
 │             │        │             │ ◄── reasoning/speech 增量 ──│
 │ message.delta ◄───────┤             │       (思考链流式上屏)       │
 │  (reasoning/ │        │ character.final → 台词落库 + 委派          │
 │   speech)    │        │                │                          │
 │             │        │ 有委派 → _execute ──► open_session ─────────┤
 │             │        │         │               ◄────── session ───┤
 │ tool_run.upserted ◄───┼─────────┤ 事件循环（沙箱/审批/增量转发）      │
 │ 审批请求/裁决 ◄───────┼─────────┤ ◄── tool_call / text / permission ──┤
 │             │        │ 回执 → 角色结果回应（stream_reply）            │
 │ message.created ◄─────┤         │                                    │
 │ turn.status_changed ◄─┤ turn completed/failed                        │
 │ 队列非空 → 自动派发下一条                                             │
```

### 11.3 直发助手（协作模式）

```
前端 chat.submit(target=assistant)
   │
   ├─ 无活动任务 ─► 新建 TaskRequest ─► _execute（同 11.2 的执行段）
   ├─ 活动任务（本会话）─► TaskAmendment ─► engine.amend_turn（steer）
   └─ 活动任务（他会话）─► 系统提示"另一聊天任务仍在运行"
```

### 11.4 工具审批（请求批准模式）

```
CodingEngine          Orchestrator        ApprovalBroker      前端
  requestApproval ──► approval.requested
  （挂起等待）           │ 沙箱检查（越界→直接否决）
                       ├─► 裁决（reviewer/人工）
                       │       │ approval.requested（审批栏卡片）
                       │       │ ◄── 用户 allow/deny
                       │ ◄─────┘
                       ├── resolve_approval（回复引擎）
  ◄── 继续/拒绝执行 ────┤
                       └─ system.approval 卡片入时间线
```

### 11.5 取消

```
前端 task.cancel ──► orchestrator.cancel_active_task
                       ├─ 生命周期 → CANCELLED（终态先行）
                       └─ engine.cancel_turn
                            codex：turn/interrupt（request）
                            reasonix：session/cancel（notification）
                       → 回执 status=cancelled，角色结果回应如实表述
```

### 11.6 聊天标题自动生成

```
chat.submit（首条用户消息）
   │
   ├─► 后台任务：_schedule_title_generation
   │      ├─ 已生成过/标题已改 → 跳过
   │      └─ dialogue_model.generate_title（关思考 + token 预算）
   │            └─ 成功 → rename_conversation → conversation.changed
   └─► 前端 conversation.changed 处理器同步 projectsById[].conversations
          → 侧栏标题即时更新
```

---

## 12. 构建与打包

```
desktop/scripts/build-sidecar.ps1    打包 Python Sidecar + 内置二进制
  ├─ PyInstaller（--onedir → resources/sidecar/pair-harness-sidecar/）
  ├─ Codex 原生发行目录 → resources/codex/
  └─ reasonix.exe（npm 全局）→ resources/reasonix/bin/

desktop/src-tauri/tauri.conf.json
  ├─ bundle.resources = sidecar/** + codex/** + reasonix/**
  ├─ bundle.targets = nsis / msi（安装包）
  └─ 仅出 exe：tauri build --no-bundle（resources 需复制到 exe 同目录）

Rust 侧资源发现（main.rs）：
  packaged_sidecar → 直接作为程序启动（不注入环境变量）
  packaged_codex / packaged_reasonix → 命中后注入
    PAIR_HARNESS_BUNDLED_CODEX_BIN / PAIR_HARNESS_BUNDLED_REASONIX_BIN
  Python 侧 engine_factory.resolve_{codex,reasonix}_executable：
    打包内置 > 环境变量（PAIR_HARNESS_*_BIN）> PATH 默认
```

---

## 13. 目录结构总览

```
HSR Partner Harness/
├── src/pair_harness/           Python Sidecar 包
├── desktop/
│   ├── src/                    React 前端
│   ├── src-tauri/              Rust 壳 + 资源（sidecar/codex/reasonix）
│   ├── scripts/                构建脚本（build-sidecar / tauri 构建）
│   └── dist/                   前端构建产物
├── config/
│   ├── pairs/                  pair YAML（角色+助手+主题）
│   ├── prompts/                角色卡/助手提示词/审查提示词
│   └── risk_rules.yaml         高风险操作规则
├── assets/                     Sidecar 静态资源
├── docs/                       架构与设计文档
├── scripts/                    复现/验证脚本
└── tests/                      pytest 测试（unit/contract/integration）
```

---

## 14. 扩展点

| 扩展点 | 位置 | 说明 |
| --- | --- | --- |
| 新编程引擎 | `core/ports.py` CodingEngine + `desktop_backend/engine_factory.py` | 实现端口，工厂按 `engine` 选择 |
| 新对话服务商 | `config/providers.py` + `adapters/dialogue/` | 供应商识别、请求形态预设、输出解析 |
| 新角色/助手 | `config/pairs/` + `config/prompts/` | YAML + Markdown 提示词 |
| 新审批规则 | `config/risk_rules.yaml` | 模式匹配规则表 |
| 新语音引擎 | `core/ports.py`（ASR/TTS/VAD）+ `adapters/audio/` | 实现端口，工厂替换 |
| 前端新界面 | `desktop/src/ui/` | Presenter 投影 + 组件 |
| 存储迁移 | `storage/sqlite_store.py` SCHEMA_VERSION | 逐级迁移 |
