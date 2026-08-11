# Harness 设计优化实施计划

- 日期：2026-08-11
- 来源：2026-08-11 对计划 A 完成态的全仓设计评审（基线：78 个测试通过、1 个跳过，最新提交 `3a48c7f`）
- 设计依据：`docs/specs/2026-08-10-roleplay-coding-harness-design.md`、`AGENTS.md` 当前项目状态
- 当前阶段：O1–O4 全部完成（最终测试基线：157 passed, 1 skipped）；O3.1 设计修订稿待用户确认；B1 真实联调等待外部条件
- 定位：本计划夹在计划 A（已完成）与计划 B（等待外部条件）之间，修复评审发现的断链、bug 与设计打磨项，降低 B1 联调风险

## 0. 实施者须知

1. 按 O1 → O4 的顺序执行；O3 的设计稿可以先写，但涉及真实 app-server 的联调步骤仍等待计划 B 的外部条件（可启动的 Codex app-server、角色对话 API 配置）。
2. 每个工作项完成后单独 commit，不混入其他改动；提交信息使用简体中文。
3. 终端命令一律使用 PowerShell 语法；Python 解释器一律使用 `.\.venv\Scripts\python.exe`。
4. 不引入计划之外的依赖、文件或功能；不修改只读参考仓库 `E:\AI\二次元情感陪伴助手`。
5. 任何改动前先运行 `.\.venv\Scripts\python.exe -m pytest -q` 确认基线全绿；每个工作项必须附带对应的新测试，不允许为通过测试而删除或放松既有断言。
6. 全部改动继续使用可预测的测试适配器，不调用真实模型，不执行真实文件修改。

## 1. 背景与问题清单

计划 A 的分层骨架（contracts/ports、沙箱、审批、风险规则、状态机）经评审确认健康，但存在三类问题：

- **断链类**：设计已承诺的验收项在接线上是断的（旧聊天恢复不回填编排器、取消链路无消费者、运行中修改无路由、事件流无流式通道、真实角色适配器无委派解析、双审批体系未统一）。
- **正确性 bug**：评审中已实测或代码路径明确的错误（审查智能体拼接必然失败、str 枚举入库与上屏、子进程 stderr 死锁风险等）。
- **设计打磨项**：不阻塞但应在计划 B 前收紧的细节（审批缓存粒度、Windows 路径匹配、事件序号双源头、并发防护、存储迁移机制等）。

已知计划内遗留（审查否决后的改方案重试、Codex workspace-write 映射联调、B2 语音、B3 搭档扩展）不在本计划内重复建设。

## 2. 阶段总览

| 阶段 | 内容 | 依赖外部条件 | 状态 |
|---|---|---|---|
| O1 | 正确性修复（7 项） | 无 | ✅ 全部提交 |
| O2 | 编排器链路补全（5 项） | 无 | ✅ 全部提交 |
| O3 | B1 前置设计落地（3 项） | 联调步骤等待计划 B 条件 | ✅ 适配器实现完成，联调并入 B1 |
| O4 | 设计打磨（6 项） | 无 | ✅ 全部提交 |

O1、O2、O4 全部使用测试适配器完成并验证；O3 产出设计修订与适配器实现，真实联调并入计划 B1。

---

## 3. O1 正确性修复

### O1.1 审查智能体的回复拼接必然失败 ✅ `e36c937`

- 问题：`src/pair_harness/adapters/reviewer.py` 的 `DialogueModelReviewer.review` 同时拼接 `speech.delta` 片段与 `character.final` 的全量台词。两个现有适配器（Scripted、OpenAI 兼容）都是“增量 delta + 全量 final”，拼接结果必然重复，JSON 解析必失败，审查模式永远返回“格式错误”否决。当前 `tests/unit/test_reviewer.py` 只覆盖 `ScriptedReviewer`，该 bug 无测试兜底。
- 动作：只取 `character.final` 的台词作为解析输入（忽略 delta）；解析失败保持 fail-closed 否决。
- 验证：新增测试——使用同时发送 delta 与 final 的对话模型，断言审查裁决解析正确；再补一条非法 JSON 输出断言否決与理由文案。

### O1.2 str 枚举入库与上屏 ✅ `b895497`

- 问题：Python 3.11 下 `str(MessageSource.USER)` 结果为 `"MessageSource.USER"`（已实测）。`sqlite_store.py` 的 `save_message` 把该值写入 source/kind 列（目前查询不读这两列，属脏数据隐患）；`message_list.py` 的气泡来源标签直接显示 `MessageSource.CHARACTER`，且 `setObjectName(f"message-{message.source}")` 使 QSS ID 选择器含 `.`，气泡样式可能不生效。
- 动作：入库与展示统一改用 `.value`；气泡来源标签映射为中文名（用户/角色/助手/工具/系统）；objectName 只使用安全字符。
- 验证：存储测试断言 messages 表 source/kind 列为枚举值；UI 测试断言来源标签文本与气泡样式表应用。

### O1.3 Codex 传输层健壮性 ✅ `9f8be73`

- 问题：`transport.py` 中子进程 `stderr=PIPE` 但无人消费，app-server 打满缓冲后整体阻塞；`request()` 无超时；`_read_loop` 内单行坏 JSON 会抛出并杀掉整个读循环。
- 动作：stderr 改为 `DEVNULL`（或启动独立任务消费并接入日志）；`request()` 增加可配置超时；`_read_loop` 对单行解析失败做容错（记录并跳过），只对连接关闭终止循环。
- 验证：新增传输层测试——坏行注入后继续读后续消息；请求超时抛出可识别异常；fake app-server 测试保持通过。

### O1.4 UI busy 判断去掉演示关键字 ✅ `d1a17f1`

- 问题：`ui/app.py` 的 `submit` 用 `"请让古代机械" in text` 判断 busy，UI 层感知了 demo 适配器的触发词。
- 动作：busy 状态由 orchestrator 的执行生命周期驱动（任务开始/结束回调或 O2.1 的事件通道），不再做文本猜测。
- 验证：UI 测试——纯聊天不进入 busy；产生委派的输入进入 busy 并在任务结束后复位。

### O1.5 “本对话内允许”缓存收紧 ✅ `3fe7219`

- 问题：`approval.py` 的 `_signature` 对 shell 只取首个词（允许过 `git status` 后，`git push --force` 在同对话内直接放行）；`file_write` 按扩展名缓存（写过 `a.txt` 后写 `.env` 也放行），敏感路径与高风险规则在缓存命中路径上完全不参与。
- 动作：命中 `sensitive_paths` 或高风险规则的操作永不写入会话缓存；shell 签名至少包含命令与子命令两个词元；file 类签名纳入具体路径的父目录维度。签名规则改动需在代码注释中写明依据。
- 验证：新增审批测试——同对话内先允许低风险命令、再触发同首词高风险命令仍要求审批；敏感路径写入不被缓存命中放行。

### O1.6 敏感路径匹配兼容 Windows 分隔符 ✅ `254df3f`

- 问题：`risk_rules.py` 用 `fnmatch` 以 `'**/.env'` 等正斜杠模式匹配路径，Windows 反斜杠路径全部漏判。
- 动作：匹配前把待检路径统一规范为 POSIX 风格（`PurePath(...).as_posix()` 或等价处理），规则表保持正斜杠写法不变。
- 验证：参数化测试覆盖 `C:\proj\.env`、`src/../.env`、正斜杠变体。

### O1.7 审批区展示参数修正 ✅ `0d76a92`

- 问题：`ui/app.py` 的 `approval_callback` 调 `window.show_approval_request(op.summary, op.command or "")`，把命令文本当成审批理由显示；`enqueue_request` 的 approval_id 传空串，UI 队列与 futures 队列仅靠顺序对应。
- 动作：传递真实理由（风险标签或“需要用户审批”）；approval_id 贯通到 ApprovalBar 队列项，裁决按 id 对应 future，不再依赖 FIFO 巧合。
- 验证：UI 测试断言审批区摘要与理由文本；两个连续审批请求按 id 正确裁决。

---

## 4. O2 编排器链路补全

### O2.1 流式事件通道（OrchestratorBridge 启用） ✅ `0b79834`

- 问题：`handle_character_input` 内部 `await self._execute(task)` 一竿子到底，角色“交给你了”台词要等整个任务执行完才到达 UI；`apply_engine_event` 是事后回放，设计 §4.4 的流式工具卡片无法实现。`ui/qt_bridge.py` 的 `OrchestratorBridge` 已预留信号但从未使用。
- 动作：orchestrator 增加事件回调（或异步队列）出口，消息、工具事件、审批事件产生时即推送；UI 经 OrchestratorBridge 增量渲染；`ConversationOutcome` 保留为最终汇总。推送顺序须满足设计 §3.2：角色接受委派的台词先于执行事件到达界面。
- 验证：编排器测试断言回调事件顺序（委派台词 → 工具事件 → 助手总结 → 角色结果回应）；UI 测试断言执行中途界面已出现角色台词与运行中的工具卡片。

### O2.2 旧聊天恢复回填编排器 ✅ `b9011f2`

- 问题：`ui/app.py` 只把 `load_conversation` 的结果用于展示，orchestrator 的 `_history` 与 `_sessions` 不回填。后果：恢复后角色失忆（`recent_messages` 为空）；`_execute` 取不到 `stored_ref`，Codex 只能 `thread/start` 而非 `thread/resume`——“旧聊天恢复编程会话”这一验收项当前是断的。
- 动作：orchestrator 增加 `restore_conversation(snapshot)` 入口（或由 store 惰性回填），打开聊天时同时回填消息历史与 `EngineSessionRef`。
- 验证：集成测试——写入历史后重建 orchestrator，恢复再发消息，断言 `DialogueRequest.recent_messages` 含历史消息；断言 `open_session` 收到已保存的 `stored_ref`。

### O2.3 取消链路接通 ✅ `0baefe3`

- 问题：`cancel_requested` 信号只有发射端；orchestrator 无取消入口；`CodexAppServerEngine.cancel_turn` 无人调用。
- 动作：orchestrator 增加 `cancel_active_task()`：经 `GlobalEngineState` 找到活动 turn，调用引擎 `cancel_turn`，把任务生命周期落到 `cancelled`，回执状态为 `cancelled`，角色结果回应如实说明已停止；UI 连接取消按钮。无活动任务时取消按钮保持禁用。
- 验证：编排器测试断言取消后状态机、回执与角色回应；Codex 适配器测试断言 `turn/interrupt` 请求参数。

### O2.4 运行中用户修改优先路由 ✅ `555bf89`

- 问题：任务运行中用户“直接交给助手”会撞 `BusyTurnError` 静默失败（设计 §3.2 要求用户直接修改拥有最高优先级）。
- 动作：运行中的 direct input 归一为 `TaskAmendment` 走 `amend_turn`（用户来源优先于角色建议）；其余冲突场景把 `BusyTurnError` 转化为用户可见的系统提示，不再静默。
- 验证：编排器测试——运行中 direct input 产生 amendment 且 `origin` 可区分用户来源；UI 测试断言冲突提示可见。

### O2.5 编排器并发防护 ✅ `16e8606`

- 问题：qasync 单循环下多个 submit 协程可并发进入 orchestrator，纯角色聊天与执行中任务交错写 `_history`，顺序不定；`_active_lifecycle` 单字段假设被并发打破。
- 动作：orchestrator 入口按会话串行化（`asyncio.Lock` 或每会话队列）；明确执行期间角色聊天的消息落库顺序约定并写注释。
- 验证：并发测试——执行中并发发起角色聊天，断言历史顺序确定、`BusyTurnError`/amendment 行为符合预期。

---

## 5. O3 B1 前置设计落地

### O3.1 审批体系统一（设计修订 + 适配器预备） ✅ 适配器 `3e02034`，设计修订稿见 §14 待确认

- 问题：orchestrator 在 `tool.started` 事件之后做沙箱与审批门控，对真实引擎而言操作已在执行，门控名不副实；`CodingEngine.resolve_approval` 全仓无人调用；codec 同时透传 app-server 原生 `approval.requested`，两套审批并存。
- 动作：
  1. 产出设计修订稿（更新 `docs/specs/` 对应章节）：app-server 负责真正暂停执行（approval policy + workspace-write 沙箱策略映射），orchestrator 的 `ApprovalManager` 裁决后统一经 `resolve_approval` 转发；orchestrator 侧沙箱保留为兜底校验；原生审批事件不再单独透传为交互卡片。
  2. 适配器预备实现：`open_session`/`thread/start` 参数中预留策略映射位置；orchestrator 门控结果接 `resolve_approval`。真实参数联调并入计划 B1。
- 验证：设计修订稿经用户确认；测试适配器层断言裁决会调用 `resolve_approval` 且参数正确。

### O3.2 角色适配器提示词装配与委派解析 ✅ `5602cc9`

- 问题：`OpenAICompatibleDialogueModel` 只发送 `user_message.text`：不注入角色卡（`load_pair_config`/`load_prompt` 无人调用）、忽略近期消息与结果摘要、不解析 `config/prompts/characters/phainon.md` 约定的 `{"speech", "delegation"}` JSON，`CharacterTurn.delegation` 在真实链路永远为 None；未注入 client 时每次调用新建 `httpx.AsyncClient` 且不关闭。
- 动作：
  1. 装配提示词：system 为角色卡 + 助手表达配置（按 `pair_id` 从 `config/pairs` 加载），messages 为近期角色对话，`result_summary`/`progress_summary` 以约定格式注入。
  2. 解析输出为 `CharacterTurn`：`delegation.type == "task"` → `TaskRequestDraft`，`"amendment"` → `TaskAmendmentDraft`；解析失败时把原始输出降级为纯台词（不产出委派），并保证原始 JSON 不会作为台词进入 TTS。
  3. 修复 client 生命周期（复用、超时、关闭）。
- 验证：适配器单测用本地假 HTTP 服务覆盖：提示词装配内容、三种输出形态（纯聊天/委派/修改）、解析失败降级、client 复用。

### O3.3 角色进度摘要落地 ✅ `dc13297`

- 问题：`DialogueRequest.progress_summary` 字段从未被填充，`CharacterProgressSummary` 类型未定义，设计 §3.2/§9 的“角色只接收压缩进度摘要”停在协议字段层面。
- 动作：定义 `CharacterProgressSummary`（当前步骤简述、已完成步骤数、状态，不含原始命令与输出）；orchestrator 在执行期间按节流策略生成并注入角色请求。
- 验证：编排器测试断言执行期间角色收到的进度摘要不含路径、命令与输出原文。

---

## 6. O4 设计打磨

| 编号 | 位置 | 问题与动作 | 验证 |
|---|---|---|---|
| O4.1 | `orchestrator.py`、`codec.py`、`engine.py` | 事件序号双源头（codec 内部编号 + orchestrator 合成事件本地编号 + `sequence=10**9` 魔法值）。统一为 orchestrator 出口处重排，适配器不再自定序号 ✅ `c145829` | 事件流测试断言序号连续无碰撞 |
| O4.2 | `approval.py`、`orchestrator.py` | `clear_session_cache` 无人调用，“聊天结束后失效”无生命周期；`_approval_managers` 常驻不清理。接聊天结束/切换钩子并清理 ✅ `b5822bc` | 测试断言切换聊天后缓存失效 |
| O4.3 | `sqlite_store.py`、`schema.sql` | 迁移靠手写 ALTER TABLE，引入 `PRAGMA user_version`；`last_turn_id` 从未写入、`resume_status` 恒为 'ready'——或接线或移除；`changed_files` 去重；回执与 ToolRun 状态消除 `type: ignore` 字符串 ✅ `3b3c53c` | 迁移测试（旧库打开升级）；存储测试断言去重 |
| O4.4 | `contracts.py` | `payload: dict`、`PendingOperation.paths: list` 名义 frozen 实则内容可变，改 tuple/Mapping 或注释说明；`Message.turn_id` 混入 engine_turn_id 语义，改独立字段或改名并同步存储 ✅ `19de97b` | 协议测试同步更新 |
| O4.5 | `message_list.py`、`tool_card.py`、`main_window.py` | `QLabel` 自动识别富文本，助手输出含 `<...>` 会渲染错乱，统一转义；`setToolButtonStyle(2)`/`setArrowType(1)` 换 Qt 枚举；`MessageSource.TOOL` 死分支清理；角色/助手气泡颜色改读 `PairConfig.theme`（B3 前置） ✅ `2c70750` | UI 测试覆盖富文本转义与主题读取 |
| O4.6 | 全局 | 评审确认的设计偏差注释化：沙箱对 shell 命令仅能锁定 cwd（真实边界在引擎策略），在 `sandbox.py` 注释写明，避免后来者误判防护强度 ✅ `2b8fb76` | 代码审查 |

## 7. 明确不做的范围

- 不接真实 Codex app-server、真实角色对话 API、DashScope（属计划 B1/B2，外部条件未到）。
- 不扩展流萤/萨姆、三月七/第四面镜配置（属计划 B3）。
- 不新建日常聊天区、聊天标题自动生成功能（已确认方案内未实施项，随计划 B 主线推进）。
- 不引入生产级权限、审计、遥测、容器隔离等超出本地单用户 MVP 的机制。
- 不重复计划 A 已完成内容，不放松既有 78 个测试的断言。

## 8. 总验收标准

1. `.\.venv\Scripts\python.exe -m pytest -q` 全绿，且每个 O 项附带的新测试真实覆盖对应问题（评审抽查能复现“修复前失败、修复后通过”）。
2. 恢复旧聊天后：角色能引用历史上下文，编程会话引用回传 `stored_ref`。
3. 执行期间：界面先看到角色接受委派的台词，工具卡片流式更新，取消按钮可用且取消后状态、回执、角色回应一致。
4. 运行中用户直接修改形成 amendment；其余冲突有用户可见提示。
5. 审批：高风险与敏感路径操作不被“本对话内允许”缓存放行；审查智能体在测试适配器下给出正确裁决；裁决调用 `resolve_approval`。
6. 数据库 source/kind 列为枚举值；界面无枚举名上屏；审批区理由文本正确。
7. 设计修订稿（O3.1）经用户确认，并入 `docs/specs/`。
