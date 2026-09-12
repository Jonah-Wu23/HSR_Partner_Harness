# Repository Guidelines

## 协作方式

默认使用简体中文。修改以当前需求为准，先完成主路径，再处理必要的测试和文档。

仓库中可能存在用户自己的本地文件。提交时写明文件路径，避免使用 `git add -A`。原始资料和旧版文件保存在 `.archive/`，该目录受 Git 忽略。

## 最高准则：Let It Fail, Let It Go

### Let It Fail

真实失败必须暴露，不能用兜底代码把失败改写成成功、空结果或伪造的失败回执。

- 诊断和真实联调时，不吞异常、不合成成功事件、不用默认文本掩盖未执行的任务。
- 需要验证真实链路时，使用真实配置、真实服务和真实 app-server；假模型、假 HTTP、Scripted/Fake engine 或 mock server 只能验证离线协议逻辑，不能作为真实链路通过的证据。
- 测试必须让错误直接失败。发现测试夹具与真实协议不一致时，更新夹具以匹配真实协议，不能为了让测试通过而放宽生产代码或增加未经证实的兼容分支。
- 修复只针对已观察到的根因；不得用关键词猜测、历史消息恢复或合成事件掩盖委派未触发、工具未执行或 app-server 已退出。
- 界面可以把底层异常转换为可读提示，但不得改变底层失败状态，也不得阻断原始错误继续进入日志和调用链。

### Let It Go

赋予大语言模型足够的权限，充分相信目前大语言模型的实力。

- 严禁在代码与脚本层面使用各种探针、正则与关键词检测限制大语言模型：意图判定（要不要委派、任务内容）、台词措辞、成败表述一律由模型自己负责，代码不得改写、补全或替换模型输出。
- 代码只做协议一致性检查（例如模型自报 delegate=true 却未返回 delegation 即协议违规，如实暴露）与安全边界（沙箱、审批），不做语义猜测。
- 用户的措辞千变万化，任何关键词词典、正则、句式模板都不可能覆盖；检测模型或用户文字意图的兜底一律视为缺陷，发现即删除。
- 角色卡与提示词只描述职责边界与输出协议，不维护关键词枚举式的意图判定清单。

## 智能体行为约定

本节参考 OpenAI GPT-6 Astra 提示词最佳实践整理，约束在本仓库中工作的智能体。

### 主动推进

从指令和上下文中推断用户的意图与任务范围，以行动为先，把任务做到底。

- 用户表达要做新工作或修问题的意图后，持续推进直到目标完成。除非操作明显具有破坏性、不可逆，否则自主推进：建隔离 worktree 或 checkout、解决合并冲突、只读检查、建草稿 PR 等都视为已授权。
- "能不能……""我想……""帮我……"这类措辞一律视为执行指令。不要停在"可以"的口头回应、方案罗列或"要不要继续"的询问上；不为省时间、力气或 token 交付"差不多能用"的半成品；任务需要持续投入，就把必要工作全部做完。
- 先做出具体、可审阅的结果，再请求批准。部署变更、写入外部应用、合并 PR、发布站点之前，先把所有能做的做完，让批准成为最后一步。可逆操作、只读操作、评审、修复，以及此前已授权或任务指令已强烈暗示的事情，不需要额外请示。
- 不因假想的风险主动添加警告、免责声明、批准流程或安全检查清单。

### 指令优先级与 skill 透明

- 用户指令优先于 skill 提供的指引；两者冲突时以用户指令为准。
- 如果某个 skill 导致你请求许可、暂停、搁置已请求的工作或偏离用户意图，指出确切的 SKILL.md 文件，引用相关条款，简要说明它如何适用；区分 skill 的明示要求和你对指引的解读。

### 表达与写作风格

本节是项目写作要求的维护入口，适用于营销方案、官网、视频脚本、界面文案、下表中的五份文件，以及智能体回复、代码注释、提交信息和 PR。中英文遵循相同原则。

先说主要观点或实际结果，再给读者理解、判断或操作所需的解释。每段围绕一个要点，让句子自然承接。长短句随内容变化，避免把完整意思切成连续碎句。列表用于真正并列、有序或便于比较的信息；表格用于比较，层级确有必要时才用嵌套列表。不要把每段都写成加粗小标题加一句结论。

使用常见词、具体例子和准确动词，优先主动语态。技术细节只写到足以说明行为、判断风险或复现结果。英文使用自然句法，不堆叠连字符复合修饰语，不编造 `exact-head checks`、`editorial-row layouts` 之类标签；代码标识、正式名称和标准术语按原文书写。

直接写实际做什么、如何工作、交付了什么。严禁先自行添加用户未要求的内容，再把删除该内容写成产品卖点、交付范围或设计理由。用户否决的擅自扩展应从最终标题、正文、注释、提交信息和 PR 中一并消失。只在用户明确追问，或已有用户确实需要迁移说明时，简要说明相关变化。成稿围绕最终需求与实现组织。

禁止用“不是 X，而是 Y”“X，而非 Y”“X（无 Y）”或 `X, not Y`、`X—not Y` 引入无关对立项。不要主动罗列不做的事、保持不变的事或已放弃的方案，不用自证清白、表忠心和反复道歉代替结果。真实使用条件、当前限制和必要许可条款写在读者需要的位置，表述具体，避免扩写成防御性说明。

不用 `Bottom Line:`、`delve`、`foster`、`leverage`、`genuinely`、“值得注意的是”“重要的是”等套话，不用“问？答。”式自问自答，不以“简而言之”“最简单的心智模型是”或同类句子重复收尾。删除空洞排比、口号式升华、模糊限定词和机械过渡语。不用破折号补充解释。

营销文案围绕明确受众、具体场景和一个传播主张展开，使用产品中的角色、操作与成果支撑表达。语气可以有个性，事实必须有依据；效果、用户数、效率提升和评价均需来源。计划中的目标和测算标明假设。润色时保留作者原意、有效细节和自然语气，不凭空补写事实或引语。

#### 各文件的写作职责

| 文件 | 写作要求 |
| --- | --- |
| `README.md` | 面向初次了解产品的中文读者，先说明用途和实际使用场景，再给下载、配置与操作路径。功能描述对应发布版本，示例足够具体。 |
| `README.en.md` | 用自然英文传达与中文版一致的产品事实、版本与使用条件。按英语习惯组织句子，避免逐字翻译中文口号。 |
| `PHILOSOPHY.md` | 说明设计选择、理由和用户能观察到的行为。区分设计目标与已实现能力，避免拟人化比喻替代架构解释，避免绝对化效果承诺。 |
| `THIRD_PARTY_NOTICES.md` | 准确列出来源、实际使用范围、版权与许可。项目自写说明使用中性、简明的语言；第三方许可原文和版权声明逐字保留。 |
| `AGENTS.md` | 规则明确动作、适用条件和必要例外。同一要求集中维护，其他文档引用本节。规则应能指导下一次工作，避免记录对话情绪和修改经过。 |

#### 成稿检查

使用 `humanizer` 技能校订本项目文案，遵循用户当前指令，在内部完成起草、审阅和修订。交付最终文本，按任务需要简述修改结果。逐句检查信息是否服务当前需求，事实是否有依据，标题与正文是否残留擅自扩展或已删除内容，语言是否自然。第三方原文、代码、命令和链接目标按其各自契约保留。审阅由模型完成，不在产品运行时添加关键词或正则来改写用户与角色的表达。

### 子代理委派

- 任何时候，只要能通过委派给其他代理来并行工作，且能节省时间或提升质量，就用协作工具委派，无论你是根代理还是子代理。
- 发给其他代理的消息和最终答复可能被人阅读，保持清晰易读，单词与数字之间保留正常空格。

### 测试与验证的尺度

- 可逆、低影响、与实现互为镜像的改动不写测试。如果选择用测试验证，测试必须对验证实现确实有意义、有必要。
- 运行与改动相称的测试，完成必需的检查。通过之后，只有出现新改动、新失败或未解决的疑虑时才扩大或重复测试，否则继续推进任务。

## 当前架构

桌面端位于 `desktop/`，界面使用 Tauri 2 和 React。Rust 负责启动 Python Sidecar，也负责桌面文件夹选择。

Python 包位于 `src/pair_harness/`。Sidecar 入口是 `pair_harness.desktop_backend`，业务状态以 Python 层为准。桌面端通过 JSONL 请求和事件与 Sidecar 通信。

桌面界面统一放在 `desktop/`。Python 包保留 Sidecar 所需的业务代码。

## 文档索引

`docs/` 按渐进式披露组织：本节只记录顶层，各子目录的 `README.md` 再披露其下文档，需要细节时逐层进入。

- `docs/README.md` — docs 总索引（完整入口）。
- `docs/index.html` 与 `docs/assets/website/` — 项目官网，GitHub Pages 从 `docs/` 根目录发布，两者位置不可移动。
- `docs/plans/` — 开发计划，现行路线图 `V0.3.3-V0.4.0-Plan.md`。
- `docs/release-notes/` — 版本发布说明（v0.4.0 / v0.3.2 / v0.3.2-patch1 / v0.2.0），另有 v0.3.x 阶段验收文档。
- `docs/character-card/` — 角色卡数据契约、字段映射、状态枚举与接入清单。
- `docs/design/` — `research/` 外部调研（mufy、SillyTavern、DeepSeek-Reasonix）、`dashscope/` 千问语音 API 参考、`web-prototype/` V0.4.0 视觉原型、`旧版/` v0.2.0 时代文档。
- `docs/website/` — 官网文案规则。
- `docs/promo/` — 宣发工作目录，Git 忽略，仅存本地。

维护规则：新增文档放进对应子目录并更新该目录 `README.md`；移动或重命名 `docs/character-card/`、`docs/design/dashscope/` 下的文档时，同步更新 `src/` 代码注释中的路径引用。

## 知识图谱

`graphify-out/` 存有一份预构建的仓库知识图谱：7620 节点、18326 条边、311 个社区，覆盖 `src/`、`tests/`、`desktop/`、`docs/`、`config/`、`scripts/`。回答架构问题、判断符号归属、评估改动波及范围时先查它，比通读源码快得多。

### 入口

首选 `graphify-out/wiki/index.md`。它是纯 Markdown 加相对链接，322 篇文章共 1.4 MB。任何能读文件的客户端都能用，不需要 shell、Python 或安装 graphify。社区文章按领域列出关键概念、连接数和源文件路径，并列出相邻社区；节点文章按关系分类列出全部连接。

能执行 shell 且本机装有 graphify 时，命令行查询更省上下文：

```powershell
graphify query "委派执行链怎么走的" --budget 2000   # BFS 遍历，输出受 token 上限约束
graphify query "..." --dfs                          # 追单条路径
graphify explain "ApprovalManager"                  # 符号讲解与邻接边
graphify affected "SQLiteStore" --depth 2           # 反向：改动会波及谁
graphify path "A" "B" --undirected                  # 两符号间最短路径
graphify god-nodes --top 10                         # 连接度最高的核心抽象
```

`path` 默认走有向边，通常搜不到结果，加 `--undirected`。`query` 触及预算上限时会明确报出被截断的节点数，需要更全的结果就抬高 `--budget` 或收窄问题。

### 前提、范围与新鲜度

graphify 是机器级安装（当前在全局 Python 3.11），不在本仓库的 `.venv` 里。没有它就走 wiki 路径，结论一样可用，只是查询粒度粗一些。

图谱只覆盖 534 个文件。`evidence/`、`output/`、`.playwright-cli/`、`desktop/src-tauri/gen/`、`assets/reference_voices/` 和全部图片未纳入：前四类是逐次运行的原始记录与生成物，图谱价值低；语音采样是 TTS 参考音频，不是文本。查询结果不代表整个仓库。

代码改动后图谱会过期，重建要走 `/graphify .` 的完整范围裁剪流程，不要直接跑 `graphify update`。该命令按仓库根重新扫描，会把上面排除的目录重新纳入：实测节点数从 7620 涨到 8475、社区从 311 变成 366，55 个已命名社区标签随之丢失。

`graphify-out/graph.json` 有 11.9 MB，是给工具消费的原始数据，不要整份读入上下文。

## 产品边界

角色负责对话，也可以形成结构化委派。文件操作和命令执行由助手完成。

消息必须保留来源字段。角色、助手使用各自身份，工具事件继续保持结构化展示。

语音功能使用 DashScope。自然语言回复可以朗读，工具记录保持静音。

项目绑定本地文件夹。新项目默认采用文件夹名称，用户可以随时改名。聊天初始名称为“新聊天”，首次完整回复结束后由助手生成标题；用户手动改名后，自动标题不得覆盖它。

## 常用命令

Python 测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

前端测试和构建：

```powershell
Set-Location desktop
npm test -- --run
npm run typecheck
npm run build
```

Rust 测试：

```powershell
Set-Location desktop\src-tauri
cargo test
```

首次运行状态重置是项目的刻意设计，不是误操作。每次打包 EXE 时都必须进行首次运行数据清理，由 `desktop/scripts/tauri-with-first-run-reset.ps1` 清空 `PairHarness` 本地数据目录以及 WebView 的 Local/Session Storage，使每次打包后的验证都回到新人第一次进入的状态；该清理是打包流程的必需步骤，不得省略。

NSIS 安装包：

```powershell
Set-Location desktop
npm run build:sidecar
npm run tauri -- build --bundles nsis
```

发布节奏：开发迭代只更新 `desktop/src-tauri/target/release/hsr-partner-harness.exe`，不重新生成或上传安装包。v0.4.0 已重新生成并上传 NSIS 安装包，下一次安装包更新随之后的版本发布安排。

Android arm64 Debug APK：配置 `JAVA_HOME`、`ANDROID_HOME`、`NDK_HOME` 后，在 `desktop/` 运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-android.ps1`，依赖已缓存时可加 `-Offline`。脚本先构建移动前端及包含前端资源的 Rust 动态库，再打包 APK，不执行安装。调用 gradle 前，脚本读取 `src-tauri/tauri.conf.json` 的 `version`，按 tauri CLI 同一派生式 `major*1000000+minor*1000+patch` 算出 versionCode（0.3.9 → 3009），并写出 `gen/android/app/tauri.properties`（`tauri.android.versionName` / `tauri.android.versionCode`）；该文件只在 `tauri android build` 路径生成，脚本直连 gradle 必须自行补写，否则包内版本恒为 1 / 1.0，`adb install -r` 会因降级被拒。版本缺失、非 semver 或派生值超出 1..2100000000 时脚本报错并非零退出，不进打包。不得仅复制 `assets/` 或因旧 `.so` 存在就宣称新代码已打入 APK。

## 外部代码

`src/pair_harness/config/providers.py` 含有根据 DeepSeek-Reasonix 改写的供应商识别逻辑。修改这部分时保留文件内出处，并同步检查 `THIRD_PARTY_NOTICES.md`。

编程助手统一经打包的 DeepSeek-Reasonix（ACP）接入，自己配置的 OpenAI 兼容端点按 Chat Completions 工作；仓库不包含 Codex 源码，产品不再要求 Codex app-server、Responses API 或 OAuth 登录（B-03）。

`src/pair_harness/adapters/codex/` 下仍有 `transport` 与 `auth` 两个遗留共享模块：`transport` 只提供子进程 JSONL 传输（由 ACP 连接复用），`auth` 只承载账号目录定位与本地遗留登录状态的只读/清理。两者都不构成 Codex 产品依赖，改动时不要据此恢复 Codex 运行路径。
