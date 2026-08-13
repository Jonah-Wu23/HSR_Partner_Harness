# PenguinHarness 实现架构解析

版本：0.2.0
适用范围：对桌面安装产物 `D:\PenguinHarness` 的逆向解析（Electron + Node + Hono 实现）
关键词：Electron、utilityProcess、同源 HTTP/SSE、Hono、模型目录、agenthub

---

## 1. 概述

PenguinHarness 是一个「AI Agent 执行环境」的桌面应用：Electron 壳内嵌一个
Node 服务端进程，浏览器窗口指向本地 HTTP 服务，通过同源 HTTP + SSE 与前端通信，
**刻意不使用 Electron 私有 IPC**。服务端负责多用户认证授权、Session 执行（SSE 流式）、
用量统计，核心层提供上下文引擎、统一消息协议与多厂商模型接入。

| 项 | 内容 |
| --- | --- |
| 产品名 | PenguinHarness（桌面包名 penguin-harness-desktop） |
| 版本 | 0.2.0，Apache-2.0 |
| 仓库 | github.com/Prism-Shadow/penguin-harness |
| 运行时 | Electron（Chromium + V8），Node ≥ 24 |
| 语言 | TypeScript（服务端与核心层），React（前端 SPA） |
| 包结构 | pnpm workspace monorepo：`packages/core`、`packages/server`（含 web-dist） |

---

## 2. 技术栈总览

| 层 | 技术 |
| --- | --- |
| 桌面壳 | Electron（`BrowserWindow` + `utilityProcess`） |
| 服务端框架 | Hono ^4.12.34 + @hono/node-server（不依赖 Express） |
| 前端 | React SPA，预构建静态产物（web-dist），由服务端同源托管 |
| 核心库 | @prismshadow/penguin-core（context_engine / OmniMessage / model-catalog） |
| Agent 框架 | @prismshadow/agenthub ^0.4.1，@prismshadow/penguin-skills（workspace 包） |
| 模型 SDK | @anthropic-ai/sdk 0.91.1、@anthropic-ai/bedrock-sdk、@aws-sdk 全家桶、@google、ws 8.21.0 |
| 数据格式 | smol-toml、yaml、fflate（压缩）、tar、dotenv |
| 构建/测试 | TypeScript + tsup（打包）、vitest（测试）、tsx |

---

## 3. 进程模型与通信

```
┌───────────────────────────────────────────────────────────────────┐
│                    PenguinHarness.exe（单个可执行文件）              │
│                                                                   │
│  ┌─────────────────────┐           ┌────────────────────────────┐ │
│  │  BrowserWindow      │  HTTP/SSE │  utilityProcess（Node）     │ │
│  │  React SPA          │  ───────► │  @prismshadow/penguin-     │ │
│  │  http://localhost:P │  ◄─────── │  server（Hono）             │ │
│  │                     │  （同源）  │  - 多用户认证授权            │ │
│  └──────────┬──────────┘           │  - Session 执行（SSE 流）    │ │
│             │                       │  - 用量统计                  │ │
│  ┌──────────┴──────────┐           │  - 静态托管 web-dist 前端    │ │
│  │  主进程 main.js      │           └────────────────────────────┘ │
│  │  ├─ 启动/重启 server │              ▲                          │ │
│  │  ├─ 端口记忆与选择    │              │ spawn（Node 子进程）      │ │
│  │  ├─ 崩溃检测 + 退避   │              │                          │ │
│  │  └─ desktop-login 跳转│──────────────┘                          │ │
│  └─────────────────────┘                                           │
└───────────────────────────────────────────────────────────────────┘
```

三个关键设计：

**无私有 IPC。** 主进程与服务端之间不定义任何 IPC 通道，前端对服务端的全部访问
走 `http://localhost:P` 的同源 HTTP。包描述原文：*"same-origin HTTP/SSE, no
private IPC"*。好处是前端与服务端共享同一套安全模型（同源策略、Cookie/Session），
不需要为 Electron 维护一套额外的桥接协议。

**utilityProcess 隔离。** 服务端跑在独立 Node 子进程里，崩溃不影响主进程与窗口；
主进程只负责进程生命周期（启动、健康检查、重启）。

**窗口只认回环地址。** `isAppUrl` / `isLocalSurfaceUrl` 校验目标 URL 的协议、
端口与 hostname，仅放行 `localhost` / `127.0.0.1` / `[::1]`，防止窗口被导航到
外网页面后通过同源拿到本地服务权限。

---

## 4. 桌面壳层（main.js）

| 模块 | 职责 |
| --- | --- |
| server-process | 用 `utilityProcess.fork` 启动 server 的 `dist/index.js`；等待端口文件（30s 超时）与 HTTP 就绪（10s）；退出时优雅关闭（6s 宽限） |
| port-memory | 上次使用的端口写入文件，下次优先复用；`choosePort` 对 IPv4/IPv6 双栈探测端口空闲，被占用则回退到 0（系统随机分配） |
| 崩溃重启 | 最多 3 次，指数退避 `min(1000×2ⁿ, 8000)` ms，超过次数弹错误框 |
| 登录流 | 生成一次性 token，窗口跳转 `/api/auth/desktop-login?token=...`，由服务端签发桌面会话 |
| util | 端口文件解析（1–65535 整数校验）、App URL / 回环地址判定、重启退避 |

随包资源：

- `resources/git`：内置 Git for Windows（minimal 版），供 harness 的 Git 操作免依赖使用
- `resources/elevate.exe`：UAC 提权辅助程序
- `LICENSE.electron.txt` / `LICENSES.chromium.html`：Electron 与 Chromium 的许可证文件
- 打包风格为 electron-builder：`PenguinHarness.exe`（主程序，约 225MB）+ `Uninstall PenguinHarness.exe`（NSIS 卸载器）+ `locales/` 与 `.pak` 资源文件

---

## 5. 服务端（@prismshadow/penguin-server）

Hono 应用，路由清单（逆向自 dist）：

| 路由 | 职责 |
| --- | --- |
| `/api/auth` | 认证（含 desktop-login token 签发桌面会话） |
| `/api/me` | 当前用户信息 |
| `/api/sessions` | Session 执行，SSE 流式输出 |
| `/api/projects` | 项目管理 |
| `/api/skills` | 技能管理（penguin-skills 的 HTTP 暴露） |
| `/api/events` | 事件流 |
| `/api/admin/users` | 用户管理 |
| `/api/version` | 版本查询 |
| `/api/desktop` | 桌面集成（供 Electron 壳调用） |

依赖：hono、@hono/node-server、fflate、tar、smol-toml、yaml、dotenv，
以及 workspace 内的 penguin-core 与 penguin-skills。

---

## 6. 核心层（@prismshadow/penguin-core）

核心 SDK 只依赖 agenthub 与 penguin-skills，与 HTTP 层解耦，是可独立发布的基础库
（publishConfig 均为 public）：

| 子模块 | 职责 |
| --- | --- |
| context_engine | 上下文组装与管理 |
| omnimessage | 统一消息协议（OmniMessage），含 markers 子协议 |
| interfaces | LLM / Environment 抽象接口 |
| state/model-catalog | 模型目录：provider 元数据、模型解析、环境变量解析 |

**model-catalog 内置的模型（逆向自 chunk）：**

| 厂商 | 模型 |
| --- | --- |
| anthropic | claude-fable-5、claude-opus-4.7 / 4.8 / 5、claude-sonnet-5 |
| deepseek | deepseek-v4-flash（含 -0731 快照）、deepseek-v4-pro |
| gemini | gemini-3、gemini-3-flash-preview |
| fireworks | accounts/fireworks/models/deepseek-v4-flash / pro（代理托管） |
| bedrock | 经 @anthropic-ai/bedrock-sdk 接入 AWS |

模型解析支持别名（如 `anthropic/claude-sonnet-5`、`deepseek/deepseek-v4-flash`），
provider 信息通过 `providerInfo` / `resolveModelEnv` 按环境变量配置密钥。

---

## 7. 前端

- React SPA，由 tsup/Vite 风格构建产物组成：`web-dist/index.html` +
  `assets/index-*.js` + 代码高亮语言包（按语言拆分的异步 chunk，如
  abap、python、typescript 等）
- 不单独起静态服务器：由 Hono 同源托管，天然与 API 同源，无跨域问题
- 桌面窗口直接加载 `http://localhost:P`，登录走 desktop-login 跳转

---

## 8. 构建与发布

- monorepo：pnpm workspace，core / server / skills 三包独立发布
- tsup 打包出 ESM（`"type": "module"`），server 包 `files` 只含 dist、web-dist、LICENSE
- server 要求 Node ≥ 24
- 桌面层 electron-builder 产出 Windows NSIS 安装/卸载器
- 版本同步：桌面包、core、server 均为 0.2.0

---

## 9. 关键设计决策

| 决策 | 选择 | 理由/效果 |
| --- | --- | --- |
| 通信方式 | 同源 HTTP + SSE，无私有 IPC | 前端与服务端共享同一安全模型，省掉一套桥接协议 |
| 服务端进程 | utilityProcess 独立 Node 进程 | 服务端崩溃不影响主进程与窗口 |
| 端口 | 记忆上次端口 + 双栈探测，冲突回退随机 | 桌面重启后尽量保持同一 URL；随机端口避免固定端口冲突 |
| 崩溃恢复 | 最多 3 次，指数退避 | 短暂故障自愈，持续失败才弹窗 |
| 服务端框架 | Hono（而非 Express/Fastify） | 体积小、TS 优先、SSE 友好，适合内嵌服务 |
| 前端托管 | 服务端同源托管静态产物 | 免 CORS 配置，窗口加载即用 |
| 模型接入 | 自研 model-catalog 多厂商目录 | 单一入口解析模型别名、provider、密钥来源 |
| 基础库 | core 与 HTTP/server 解耦，独立发布 | 核心协议可复用于非桌面场景 |

---

## 10. 与 HSR Partner Harness 的对照

| 维度 | PenguinHarness | HSR Partner Harness |
| --- | --- | --- |
| 桌面壳 | Electron（Node） | Tauri（Rust） |
| 服务端 | Node + Hono（utilityProcess） | Python Sidecar（JSONL over stdio） |
| 前端 | React SPA，同源 HTTP 托管 | React，Tauri invoke 桥 |
| 通信 | 本地 HTTP + SSE（同源） | JSONL over stdio（事件序号对账） |
| 进程隔离 | utilityProcess 崩溃重启 + 退避 | Sidecar 崩溃检测 + 退避重连 |
| 模型层 | agenthub + model-catalog（多厂商） | CodingEngine 端口抽象（Codex / ACP） |
| 存储 | 服务端管理（待确认） | SQLite 本地优先，账号隔离 |

两者的壳层思路一致：主进程/壳只做进程生命周期管理，业务权威下沉到独立进程，
通过流式协议与前端通信。区别在于通信载体——PenguinHarness 选本地 HTTP（面向
浏览器安全模型），HSR Partner Harness 选 stdio JSONL（面向桌面原生桥）。
