# DeepSeek-Reasonix 实现剖析

> 本文整理自对仓库源码的阅读，覆盖底层技术栈与上下文管理两条主线。
> 行号对应 2026-08-13 的 main-v2 分支（v1.23.0 前后）快照，代码演进后可能漂移。

## 1 项目概况

DeepSeek-Reasonix 是开源的编码 agent，MIT 协议，Go 编写，单二进制发布，仓库位于 `github.com/esengine/DeepSeek-Reasonix`。定位是「可以放着跑的编码 agent」：plan 模式、权限系统、工作区沙箱、逐轮 checkpoint，让长时自主运行保持可读、可回滚。

同一个本地引擎，四种入口：

- CLI / TUI（终端）
- 桌面应用（Wails）
- HTTP/SSE（serve）
- 编辑器集成（ACP，VS Code 扩展调用本地 `reasonix acp`）

模型侧：DeepSeek 是预设，任意 OpenAI 兼容端点都是配置项。支持执行器 + 规划器双模型组合，两路会话各自保持缓存稳定。

## 2 底层技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 语言与构建 | Go 1.25+（toolchain 1.26.5） | `CGO_ENABLED=0` 静态编译，单二进制，一条命令交叉编译 darwin/linux/windows × amd64/arm64 六个目标 |
| 内核 | `internal/control.Controller` | 传输无关的 agent 循环，所有前端共用 |
| 终端 UI | Charm 生态：`bubbletea/v2`、`bubbles/v2`、`lipgloss/v2` | Elm 式 TUI 框架 |
| 桌面 | Wails | Go 后端 + Node 24 / pnpm 的 webview 前端（`desktop/`） |
| 编辑器接入 | ACP 协议 | VS Code 扩展不打包 CLI，启动本地 `reasonix acp` 后端 |
| 模型接入 | DeepSeek 预设 + OpenAI 兼容端点 | 全部配置驱动（`reasonix.toml`），无硬编码模型 |
| 插件 | MCP + 自研 Extension Protocol v1 | MCP 提供工具/提示/资源；EP v1 sidecar 可拦截运行时事件、提供 Provider 与结构化 UI |
| 发布 | npm 包拉预编译二进制 + GitHub Releases + Homebrew | Windows 安装包经 SignPath.io 签名 |

其他关键依赖（`go.mod`）：

- **tree-sitter**：JS/Python/Rust/TS 四份语法，代码解析不走正则
- **goldmark**：Markdown 渲染；**chroma**：语法高亮
- **santhosh-tekuri/jsonschema/v6**：工具调用 schema 校验
- **mvdan.cc/sh**：shell 解析与执行，沙箱内命令由它跑
- **larksuite SDK**：飞书 bot（`internal/bot`、`botruntime`）
- **go-keyring / wincred / godbus / go-toast**：跨平台凭据存储与系统通知
- **spf13/pflag、BurntSushi/toml、yaml.v3**：CLI 与配置

自研基础包：`sandbox`（工作区沙箱）、`worktree`（git worktree 隔离）、`checkpoint`（逐轮检查点回滚）、`permission`、`planmode`、`memory`、`skill`、`plugin` 等。

## 3 架构分层

`internal/` 下约 90 个包，每个包只负责一件事，长解释进 `doc.go`。关键约定：

- 一个 transport 无关的 `control.Controller` 坐在所有前端后面（chat TUI、HTTP/SSE serve、Wails 桌面、bot）。新行为加在 controller 里，三个前端自动继承。
- 分层由 `tools/repolint` 强制：utility 包不得 import `reasonix/` 下任何东西；只有 `cli`、`serve`、`acp`、`bot`、`botruntime`、`boot` 以及 `cmd/`、`desktop/` 能 import `control`；frontend 以下的包不得 import 上层。
- 子代理委派把五个概念分开：profile 定义 worker 怎么思考，`TaskSpec` 定义这次调用要什么，`CapabilityGrant` 定义能碰什么，`ContextRequest` 定义从什么上下文开始，`SchedulerPolicy` 定义何时跑。字段放在决定它的那个成员里，profile 只带天花板，不带单次调用值。`internal/agent/profile_boundary_test.go` 强制这条边界。
- 性能特性落地时必须在最终边界带 effect test（`internal/boot/effect_test.go` 模式）：断言真正到达 provider 请求、前端 sink 或经过真实 `boot.Build` 装配的轨迹。组件正确不等于系统有效。

质量门禁：gofmt、go vet、make lint（golangci-lint 按 `.golangci-version` 固定版本 + repolint）。repolint 对着 ratchet baseline 跑，新债务直接失败 CI，`-update` 只允许携带改名/抽取产生的债务且要在 PR 里说明。

## 4 上下文管理

这一节是缓存命中的核心。整个设计围绕 DeepSeek 的自动前缀缓存：只要请求前缀字节相同，缓存就命中。工程上把「前缀永不改变」当作一等约束，所有会变化的东西都赶到请求尾部。

### 4.1 铁律：system prompt + 工具 schema 前缀字节级稳定

`REASONIX.md` 写死了这条规则，代码里到处是它的注释：

- 所有会变的东西不进 system prompt 和工具 schema。`SetGoal` 的注释（`internal/control/controller.go:2648`）写明：goal 注入到 user 回合，不进 system prompt 或 tool schema，这样不扰动 cache-stable prefix。`SetPlanMode` 同样（controller.go:2583），只在 user 回合开头加 plan-mode 标记。
- `control.Compose`（`internal/control/input.go:137`）是组装入口：`<memory-update>`、`<background-jobs>`、`<hook-context>`、plan-mode 标记、goal 块、记忆召回结果，全部 prepend 到用户回合文本上，不碰前缀。input.go:174 的注释：会话中途写入的记忆骑在回合上（never the cached system prefix），立刻生效且不失效 prompt cache，下个会话才折进系统前缀。

### 4.2 序列化净化，保证字节稳定

`provider.Message` 里混着大量本地元数据：`RawContent`、`ToolExecution`、`CreatedAt`、`DecisionReceipts`、`LocalOnly` 标记等。发送前 `ModelMessages` 全部剥离（`internal/provider/provider.go:103` 注释：tool schemas and prompt-cache prefixes stay stable）。工具结果第一次可见时就截断定界，之后不可变。历史追加式增长，前面的字节永远不变。

### 4.3 上下文维护：单一 compact_ratio，一次性 checkpoint

最近的提交（#8244）把多阈值 prune/snip/native 自动维护换成一条内容驱动路径：

- 上下文追加式增长直到窗口的 85%（`compact_ratio` 默认 0.85，`internal/agent/compact.go:24`）。到阈值前完全不动，缓存一直热。
- 到阈值后做一次 summary 事务，安装 checkpoint：**稳定前缀 + 一个结构化摘要 + 最近逐字尾**（compact.go:20 注释；`checkpointProjectionMessages` 在 compact_projection.go:487）。
- 摘要用固定标题：Standing facts & constraints / Goal / Decisions & rationale / Files & code / Commands & outcomes / Errors & fixes / Pending & next step，用 `<compaction-summary>` 标签包裹。规则：短句、保留标识符路径数字原样、不虚构。
- canonical transcript 永不重写。投影是独立视图，`ProjectionVersion` 持久化，重启后恢复同一投影，会话重启不白费缓存。
- 摘要后直到下一次 85% 阈值，又是追加期。压缩这个唯一的缓存重置点被压到最低频率，且压缩结果形状稳定（前缀 + 单摘要 + 尾），后续回合照样命中。
- 校验严格：candidate 必须比源小，自动路径须降到窗口 50% 上限内（`checkpointCeilingRatio`），fixed prefix 超限要走例外路径（`exceptionalMinSavingsRatio`）。摘要期间会话若变化（`errCompressStaleContext`），丢弃候选并封锁本代自动重试，避免白付一次摘要费。

### 4.4 缓存可见性：诊断与测试

- `internal/agent/cache_shape.go`：`PrefixShape` 对 system + tools 做哈希，跨轮比对，解释 miss 是 system 变了、tools 变了还是内容重写。`CompareShape` 区分「本地元数据变更」和「真正的 provider 可见重写」，后者才算缓存变化。
- `cachehit_e2e_test.go`：真实多步工具循环的端到端测试，验证每轮 Usage 都拿到 `CacheHitTokens`。
- controller.go:3547 的 `cacheColdAfter`：按 provider 的前缀缓存保留时长算冷启动窗口。
- 计费归一化（provider.go:721-737）：DeepSeek 的 `prompt_cache_{hit,miss}_tokens` 与 OpenAI 的 `cached_tokens` 归一成 `CacheHitTokens` / `CacheMissTokens` / `CacheWriteTokens`，缓存写入按单独价目计费（`CacheHit` 每 1M 计价）。
- PR 门禁：cache 敏感路径（`internal/tool/`、`internal/provider/`、`internal/boot/` 等）要求 PR body 写 `Cache-impact` 与 `Cache-guard` 字段，`scripts/check-cache-impact.sh` 校验；`none` 只在 provider 可见前缀逐字节不变时成立。

### 4.5 命中率为什么高

四层原因叠起来：

1. **前缀不变**。每轮请求头部（system + tools + 历史）与前一轮逐字节相同，DeepSeek 自动前缀缓存直接命中。
2. **动态信息只在请求尾部**。记忆更新、plan 标记、goal、后台任务完成通知全在用户回合开头追加，不影响缓存键。
3. **压缩低频且形状稳定**。缓存重置点最少，重置后的投影本身持久化，跨重启恢复。
4. **元数据全剥离**。UI 卡片、编辑标记、审批记录这些本地状态的变更不会弄脏线上字节。

prompt cache 命中在设计阶段就是一等约束。所有会变化的东西都被赶到 user turn 尾部骑尾巴，前缀从装配那一刻起冻结。

## 5 相关代码索引

| 主题 | 位置 |
|---|---|
| 用户回合组装（Compose） | `internal/control/input.go` |
| 控制器（goal、plan mode、cacheColdAfter） | `internal/control/controller.go` |
| 上下文维护（ContextManager） | `internal/agent/context_manager.go` |
| 压缩与 checkpoint | `internal/agent/compact.go`、`compact_projection.go` |
| 缓存形状诊断 | `internal/agent/cache_shape.go` |
| 缓存命中端到端测试 | `internal/agent/cachehit_e2e_test.go` |
| provider 消息与计费 | `internal/provider/provider.go` |
| 系统装配（boot） | `internal/boot/boot.go` |
| 分层强制 | `tools/repolint/layers.go` |
| 缓存影响检查脚本 | `scripts/check-cache-impact.sh` |
