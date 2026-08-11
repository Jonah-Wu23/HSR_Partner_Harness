# MVP 后续优化计划（DeepSeek 特别优化 + 角色扮演特别优化 + 可选多模态扩展）

- 日期：2026-08-11
- 前置条件：
  - MVP 计划完成：`docs/plans/2026-08-10-mvp-implementation-plan.md`（B1 外部模型 API 接入（DeepSeek 优先）、B2 语音、B3 三组搭档）。
  - 优化计划完成：`docs/plans/2026-08-11-harness-optimization-plan.md`（O1–O4，尤其 O3.2 提示词装配与委派解析、O3.3 角色进度摘要——本计划的提示词机制都建立在这条装配管线上）。
- 当前阶段：计划已编写，等待用户确认；MVP 完成前不启动实施。
- 与设计文档 `docs/specs/2026-08-10-roleplay-coding-harness-design.md` §12 的关系：§12.1 的必要增强（第二个 `DialogueModel` 适配器、会话压缩、Token 使用显示、长期记忆等）仍然有效；本计划的 P1 覆盖其中"第二个适配器 + Token 显示"的 DeepSeek 部分，P2 的"小总结/大总结"并入"会话压缩"统一设计。

## 0. 实施者须知

1. 本计划的实施严格遵守 AGENTS.md 与 MVP 计划 §0 的约定（顺序执行、单独提交、PowerShell 语法、`.\.venv\Scripts\python.exe`、简体中文注释、测试先行）。
2. 两条主线 P1、P2 可并行推进；P2 的"预填充与厂商尾部模板"依赖 P1 的供应商识别能力，该子项排在 P1 之后。P3 是**可选、非必需**扩展，独立于 P1/P2，是否启动与何时启动由用户决定，未启动或未完成不影响 P1/P2 的出口判定。
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

## 3. P3（可选）：多模态扩展（Qwen-MM-Plugins）

定位：**可选、非必需**的能力扩展——为本 Harness 接入图像/视频/文档理解与专业工具调用能力，让助手层从"纯文本编程"升级为"多模态原生"。不做不影响主线的任何验收。

参考来源：`https://github.com/QwenLM/Qwen-MM-Plugins`（**Apache-2.0**，见仓库 `LICENSE`；blender/freecad 能力 vendor 了第三方 MIT 代码，署名见其 NOTICE.md）。官方定位：面向 Qwen 模型的原生多模态理解插件，让任何 Agent Harness 具备原生多模态能力。

### 3.1 能力清单与接入形态

每个能力 = 一个 **skill**（让模型知道有这套工具）+ 一个可选 **MCP server**（工具本体，`uvx` 按需拉起，依赖 `uv`），可单独安装：

| 能力 | 内容 | 形态 |
|---|---|---|
| core | 动态分辨率读图片/视频/文档/3D 模型，OCR、grounding、分割、ASR、视觉对话、联网搜索 | skill + MCP |
| video-memory | 长视频层次化图记忆，支撑超长视频问答 | skill + MCP |
| omni-av | Omni 音视频理解：带时间戳/说话人标签的 ASR、时序定位、事件计数、音乐标签 | skill + MCP |
| video-edit | 视频剪辑工作流 + 图片/视频/音频生成 | skill + MCP |
| blender | 驱动正在运行的 Blender 建模/材质/灯光/渲染（瘦客户端，22 工具） | skill + MCP |
| freecad | 驱动正在运行的 FreeCAD 参数化 CAD（14 工具，STEP/STL、FEM） | skill + MCP |
| edu-agent | 把数学/理科题变成分步讲解的中文视频 | 纯 skill，无 MCP server |

系统依赖：`ffmpeg`（视音频必需），`libreoffice`/`blender`/`texlive`/`chromium` 按能力可选。API key：`DASHSCOPE_API_KEY`（读图/OCR/grounding/转写/Omni/生成类——与 B2 语音同一家，配置可复用）、`SERPER_API_KEY`（联网搜索类）。

### 3.2 接入前提与边界

1. **MCP 客户端（消费侧）**：本 Harness 需引入连接外部 MCP server 的客户端能力。设计边界禁止的是自建 MCP 网关、统一代理层、注册表与工具市场；**消费外部 MCP 服务器不在禁止之列**，本项目协议未禁止。B1 的"不实现任何 MCP 客户端"仅为 MVP 范围裁剪，P3 设计稿中正式解除。
2. **skill 承载**：skill 内容（工具说明提示词）并入 P2 的模块化提示词装配管线，作为可开关模块注入助手侧，不另建装配通道。
3. **工具执行权不变**：全部多模态工具只属于助手层，照常受项目级沙箱与三种审批模式约束；角色侧只讨论与回应结果。TTS 静音规则不变（工具输出、路径、日志不朗读）。
4. **不恢复 3D 展示链路**：blender/freecad 仅作为助手任务执行（产出文件/渲染图回传展示），不引入任何 3D 视口、模型加载或 WebGL——与"不迁移旧项目 3D 链路"的边界一致。
5. **模型路线**：多模态理解走 DashScope（qwen-vl/Omni 系列），与 P1 的 DeepSeek 文本主线并存；可作为设计 §12.1"第二个 `DialogueModel` 适配器"的多模态候选。
6. **平台约束**：官方仅验证 Linux/macOS 与 Windows WSL2，**原生 Windows 未验证**；本项目是 Windows 原生 PyQt5 应用，落地前先在设计稿阶段验证 WSL2 路线或原生可行性。
7. **合规**：Apache-2.0——复制或实质性改造其 skill/代码时保留版权与许可声明，登记出处（同 §1.2 规则）；不使用其安装器与插件市场机制，按需手动注册。

### 3.3 落地顺序（如启动）

1. 设计稿：MCP 客户端在编排器中的位置（连接、工具发现、超时与取消）、与审批/沙箱的接法、skill 模块 schema、平台路线验证结论。
2. 最小试点：`edu-agent`（纯 skill，无 MCP，成本最低）或 `core` 读图（价值最高，只需 `DASHSCOPE_API_KEY` + ffmpeg）。
3. 按需扩展其余能力；不承诺全量接入，每个能力单独评审。

### 3.4 验收（仅在启动时适用）

- 试点能力在真实端点跑通：工具调用事件照常持久化、可折叠展示、全程静音。
- 多模态工具与普通工具走同一审批与沙箱链路；越界操作被 Orchestrator 拦截。
- 不启动 P3 时，P1/P2 的全部验收不受影响。

---

## 4. 排序与里程碑

```text
MVP 完成（B1–B3）+ 优化计划完成（O1–O4）
        │
        ├─ P1 DeepSeek 特别优化（1.1–1.4）
        │     └─ 后端识别能力就绪
        │
        ├─ P2 角色扮演特别优化
        │     ├─ 2.2.1 设计稿（先行，可与 P1 并行）
        │     ├─ 2.2.2–2.2.3 白厄试点与叙事工程
        │     └─ 2.2.4 预填充与厂商模板（排在 P1 后端识别之后）→ 2.2.5 扩展三组
        │
        └─ P3 可选：多模态扩展 Qwen-MM-Plugins（3.1–3.4）
              非必需，独立于 P1/P2，启动与否由用户决定
```

完成出口：DeepSeek 端点上三组搭档的角色扮演质量（文风、反 AI 腔、伏笔跟踪）与委派稳定性同时达标；Token 成本可见；全部既有测试与新测试全绿。P3 不在完成出口内。
