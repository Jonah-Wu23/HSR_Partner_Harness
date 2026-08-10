# MVP 后续优化计划（DeepSeek 特别优化 + 角色扮演特别优化）

- 日期：2026-08-11
- 前置条件：
  - MVP 计划完成：`docs/plans/2026-08-10-mvp-implementation-plan.md`（B1 外部模型 API 接入（DeepSeek 优先）、B2 语音、B3 三组搭档）。
  - 优化计划完成：`docs/plans/2026-08-11-harness-optimization-plan.md`（O1–O4，尤其 O3.2 提示词装配与委派解析、O3.3 角色进度摘要——本计划的提示词机制都建立在这条装配管线上）。
- 当前阶段：计划已编写，等待用户确认；MVP 完成前不启动实施。
- 与设计文档 `docs/specs/2026-08-10-roleplay-coding-harness-design.md` §12 的关系：§12.1 的必要增强（第二个 `DialogueModel` 适配器、会话压缩、Token 使用显示、长期记忆等）仍然有效；本计划的 P1 覆盖其中"第二个适配器 + Token 显示"的 DeepSeek 部分，P2 的"小总结/大总结"并入"会话压缩"统一设计。

## 0. 实施者须知

1. 本计划的实施严格遵守 AGENTS.md 与 MVP 计划 §0 的约定（顺序执行、单独提交、PowerShell 语法、`.\.venv\Scripts\python.exe`、简体中文注释、测试先行）。
2. 两条主线 P1、P2 可并行推进；P2 的"预填充与厂商尾部模板"依赖 P1 的供应商识别能力，该子项排在 P1 之后。
3. 每个机制落地前先有设计稿并经用户确认；设计稿未确认不编码。

---

## 1. P1：DeepSeek 特别优化（参考甚至复用 DeepSeek-Reasonix）

目标：让 DeepSeek 成为本项目角色对话的一等后端——不是"能连上"，而是请求形态、思考控制、缓存与稳定性都按 DeepSeek 的官方语义调优。

参考来源：仓库内 `DeepSeek-Reasonix/`（**MIT License**，`DeepSeek-Reasonix/LICENSE`，Copyright (c) 2026 Reasonix Contributors）。

### 1.1 参考与复用清单

| 主题 | Reasonix 位置 | 借鉴内容 |
|---|---|---|
| 后端识别 | `internal/provider/openai/host.go` | 按 Base URL 识别 `api.deepseek.com` / `*.deepseek.com`，自动切换请求形态 |
| 推理协议对照 | `docs/REASONING_PROVIDERS.zh-CN.md` | 各后端思维链控制方式的权威对照表 |
| effort 档位 | `internal/provider/openai/effort.go` | `reasoning_effort` 档位归一化（遗留 `medium`→`high`，`xhigh` 按 Flash/Pro 分别归一） |
| 思考流分离 | `internal/provider/openai/think.go` | 流内 `<think>` 块与正文的增量分离，思考内容不进台词与 TTS |
| 输出预算 | `internal/provider/openai/output_budget.go` | `max_output_tokens` 分档策略（日常/长思考/工具循环） |
| 重试与流稳定 | `internal/provider/retry.go`、`stream_error.go` | 有界重试、尊重 `Retry-After`、响应体读取超时、401/403 区分瞬时拒绝与配置错误 |
| Anthropic 兼容端点 | `internal/provider/anthropic/`、预设 `https://api.deepseek.com/anthropic` | Messages API 形态、思考块在工具调用历史中的回放、provider 侧 web_search |
| 供应商预设 | `internal/config/provider_presets.go`、`reasonix.example.toml` | `[[providers]]` 预设结构；密钥只走 `api_key_env` 环境变量，预设不持有秘密 |

### 1.2 复用规则（许可证合规）

- 允许复制或改造 Reasonix 代码为 Python 实现；**凡复制或实质性改造的文件，必须在文件头保留其 MIT 版权与许可声明**，并在 `NOTICE` 或文档中登记出处。
- 不整体引入 Go 代码、模块或其二进制；按需小范围移植，移植前先评审对应源文件。
- 处理方式参照设计文档 §10 对 Herta 的既有先例。

### 1.3 优化内容

1. **思考控制**：思考开关与 effort 档位进入项目级配置与界面；闲聊轮低档位省成本，委派轮与审查智能体高档位保质量；思考内容按 voice_policy 规则天然静音，永不进入 TTS 与气泡正文。
2. **前缀缓存友好**：提示词装配管线把稳定内容（角色卡、规则、模块开关）置前、变动内容（近期消息、进度摘要）置后，利用 DeepSeek 自动前缀缓存降低成本；在日志中记录缓存命中指标。
3. **Token 使用显示**：对接设计 §12.1，按轮展示输入/输出/缓存命中 token 与估算成本。
4. **Anthropic 兼容端点可选**：为需要 Messages API 形态（思考块回放、web_search）的场景保留第二接入路径，与 OpenAI 兼容路径共用同一 `DialogueModel` 接口。
5. **稳定性基线**：停滞检测与可中断重试，错误信息用户可读（区分网络、配额、鉴权、配置错误）。

### 1.4 验收

- 离线单测覆盖请求形态（思考开关、effort 归一化、预算字段、历史回放），不发起真实请求。
- DeepSeek 真实端点冒烟：角色闲聊、结构化委派、结果回应三类轮次全部通过；思考内容不上屏、不进 TTS。
- 同一配置切换到 Anthropic 兼容端点后对话行为一致。

---

## 2. P2：角色扮演特别优化（参考 8.9【可待-从头越】Agent 版预设）

参考材料：`docs/referances/8.9【可待-从头越】 Agent版.json`——一份重度工程化的 SillyTavern 角色扮演预设（195 个提示词条目、57 个启用、`prompt_order` 排序与启用集、深度注入 `injection_position/depth/order`、采样参数档案 `temperature=1 / top_p=1 / min_p=0 / reasoning_effort=max`、流式开启）。

**只提取机制与自用改写，不做 SillyTavern 格式兼容层或预设导入器；NSFW 相关模块不迁入本项目。**

### 2.1 借鉴的机制

1. **模块化提示词开关**：预设把语言、单轮字数档位、叙事人称、转述程度、对话密度、剧情主导权、剧情推进速度、文风（散文/轻小说/冷凝等及其补充包）、描写密度、分段长度、思考长度做成可开关模块。本项目落为：pair 配置增加"角色扮演模块"段，UI 提供开关，选择按聊天持久化。
2. **去 AI 味与质量控制库**：禁用库、抗缺陷、抗重复、抗短句、抗平淡、抗网文化、抗全知、逻辑加强等模块，与本仓库 `docs/提示词去AI味重构总结.md` 的既有思路合并，形成一套可维护的反 AI 腔模块集，与 `phainon.md` 的语言禁区对齐、不冲突。
3. **叙事工程**：当前伏笔、大纲规划、描写发展链 → 角色侧的叙事状态跟踪；"小总结（省 token）/大总结" → 并入设计 §12.1 的会话压缩统一设计。
4. **预填充与厂商尾部模板**：预设为 DS 官方/哈/豆、KIMI、GLM、Minimax 等分别准备了预填充与尾部/输出模板——与 P1 的后端识别联动，按当前供应商自动选择模板。**共存规则**：纯聊天轮可套用文学预填充；含结构化委派的轮次不套用，保证 `speech + delegation` JSON 解析率不受影响。
5. **Agent 版分区思路**：预设的 `agentSystemPrompt` / `agentTask` / `agentResults` 占位符与本 Harness 的双通道天然对应——角色闲聊轮、任务委派轮、结果回应轮使用分区的提示词段落，结果回应轮的输入只有 `CharacterResultSummary`（维持设计 §6.2 边界）。
6. **采样参数档案**：按搭档/场景保存采样预设，预设档案值（如 `temperature=1`）仅作参考起点，实际取值在白厄组试点时标定。

### 2.2 落地顺序

1. 设计稿：模块 schema（名称、内容、默认开关、注入位置与顺序）、与 O3.2 装配管线的接法、与委派协议的共存规则、持久化字段。
2. 白厄组试点：模块化开关 + 反 AI 腔模块 + 采样档案。
3. 叙事工程与会话压缩（小总结/大总结）。
4. 预填充与厂商尾部模板（依赖 P1 的后端识别）。
5. 参数化扩展到流萤、三月七两组（只加配置，不复制逻辑）。

### 2.3 验收

- 同一对话在模块开关切换前后行为可区分、可复现（测试适配器断言装配结果）。
- 开启全部文学模块后，结构化委派解析成功率不下降（以 O3.2 的解析测试基线为准）。
- 反 AI 腔模块不破坏角色卡既有禁区与身份边界；TTS 静音规则不受影响。
- 会话压缩开启后，角色回应仍只依据 `CharacterResultSummary`，不接触原始工具输出。

---

## 3. 排序与里程碑

```text
MVP 完成（B1–B3）+ 优化计划完成（O1–O4）
        │
        ├─ P1 DeepSeek 特别优化（1.1–1.4）
        │     └─ 后端识别能力就绪
        │
        └─ P2 角色扮演特别优化
              ├─ 2.2.1 设计稿（先行，可与 P1 并行）
              ├─ 2.2.2–2.2.3 白厄试点与叙事工程
              └─ 2.2.4 预填充与厂商模板（排在 P1 后端识别之后）→ 2.2.5 扩展三组
```

完成出口：DeepSeek 端点上三组搭档的角色扮演质量（文风、反 AI 腔、伏笔跟踪）与委派稳定性同时达标；Token 成本可见；全部既有测试与新测试全绿。
