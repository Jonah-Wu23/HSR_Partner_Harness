# Pair Harness MVP 实现计划（详细版）

- 日期：2026-08-10
- 设计依据：`docs/specs/2026-08-10-roleplay-coding-harness-design.md`
- 当前阶段：详细实施计划已确认，等待用户安排实施者执行
- 实施原则：先完成白厄单组闭环，再接真实外部服务，最后扩展另外两组

## 0. 实施者须知

本计划面向独立实施者编写，实施时严格遵守：

1. 按 A1 → A7 的顺序执行，每个阶段跑通验收命令后再进入下一阶段。
2. 每个阶段完成后按“建议提交”单独 commit，不要把多个阶段的改动混在一个提交里。
3. 不引入计划之外的依赖、文件或功能。拿不准的行为以设计文档原文为准。
4. 终端命令一律使用 PowerShell 语法；Python 解释器一律使用项目虚拟环境中的 `.\.venv\Scripts\python.exe`。
5. 不修改只读参考仓库 `E:\AI\二次元情感陪伴助手` 的任何文件。
6. 测试失败时先修复再推进，不跳过、不删除失败测试。
7. 所有代码注释和提交信息使用简体中文。

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
→ 沙箱校验与三种审批模式
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

实现步骤：

**第 1 步：创建 `pyproject.toml`**

```toml
[project]
name = "pair-harness"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic", "PyYAML", "httpx"]

[project.optional-dependencies]
ui = ["PyQt5", "qasync"]
voice = ["numpy", "sounddevice", "onnxruntime", "dashscope"]
dev = ["pytest", "pytest-asyncio", "pytest-qt"]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

创建 `.venv` 并安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

**第 2 步：编写 `src/pair_harness/core/contracts.py`**

所有数据模型用 `pydantic.BaseModel` 并设置 `frozen=True`，保证不可变。完整模型清单如下（字段与设计文档 §6 一一对应，实施时照抄字段名，不要改名）：

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Source(str, Enum):
    USER = "user"
    CHARACTER = "character"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class Message(BaseModel, frozen=True):
    message_id: str
    conversation_id: str
    pair_id: str
    turn_id: str | None = None
    source: Source
    kind: str          # user.text / character.speech / assistant.natural_language / tool.run / system.notice
    text: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    tts_eligible: bool = False   # 只允许 Orchestrator 计算写入，模型与适配器不得设置
    created_at: datetime


class DialogueEvent(BaseModel, frozen=True):
    type: Literal["speech.delta", "character.final"]
    text_delta: str = ""
    final: "CharacterTurn | None" = None


class CharacterTurn(BaseModel, frozen=True):
    speech: str
    delegation: "TaskRequestDraft | TaskAmendmentDraft | None" = None


class TaskRequestDraft(BaseModel, frozen=True):
    instructions: str
    constraints: list[str] = Field(default_factory=list)


class TaskAmendmentDraft(BaseModel, frozen=True):
    target_task_id: str
    instructions: str


class TaskRequest(BaseModel, frozen=True):
    task_id: str
    conversation_id: str
    origin_message_id: str
    instructions: str
    constraints: list[str] = Field(default_factory=list)
    revision: int = 0


class TaskAmendment(BaseModel, frozen=True):
    amendment_id: str
    target_task_id: str
    origin_message_id: str
    revision: int
    instructions: str


class EngineSessionRef(BaseModel, frozen=True):
    engine_type: str
    opaque: str        # 适配器内部编码的不透明引用，应用层不解析


ENGINE_EVENT_TYPES = (
    "turn.started", "assistant.delta", "assistant.final",
    "tool.started", "tool.progress", "tool.finished",
    "file.patch", "approval.requested", "approval.resolved",
    "turn.completed", "turn.failed",
)


class EngineEvent(BaseModel, frozen=True):
    event_id: str
    conversation_id: str
    task_id: str
    engine_turn_id: str
    sequence: int
    type: str                      # 取值必须属于 ENGINE_EVENT_TYPES
    tool_call_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolRun(BaseModel, frozen=True):
    conversation_id: str
    task_id: str
    engine_turn_id: str
    tool_call_id: str
    sequence: int
    status: Literal["running", "succeeded", "failed", "denied"]
    summary: str
    detail: str = ""               # 默认折叠的完整内容


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AMENDMENT_PENDING = "amendment_pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED, TaskStatus.FAILED,
        TaskStatus.CANCELLED, TaskStatus.AMENDMENT_PENDING,
    },
    TaskStatus.AMENDMENT_PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
}


class ExecutionReceipt(BaseModel, frozen=True):
    task_id: str
    engine_turn_id: str
    status: TaskStatus
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)


class CharacterResultSummary(BaseModel, frozen=True):
    task_id: str
    status: TaskStatus
    summary: str
    user_visible_changes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)


class ApprovalMode(str, Enum):
    REQUEST_APPROVAL = "request_approval"   # 请求批准
    REVIEW = "review"                       # 帮我审核
    FULL_AUTO = "full_auto"                 # 完全允许运行


class ApprovalDecision(str, Enum):
    ALLOW = "allow"                          # 允许
    ALLOW_FOR_CONVERSATION = "allow_for_conversation"  # 本对话内允许
    DENY = "deny"                            # 否决


class ReviewerVerdict(BaseModel, frozen=True):
    allow: bool
    reason: str = ""        # 否决时必填：简短理由
    suggestion: str = ""    # 否决时必填：调整建议


class PendingOperation(BaseModel, frozen=True):
    """一次等待沙箱与审批检查的工具操作。"""
    tool_kind: Literal["file_write", "file_delete", "shell", "patch"]
    command: str | None = None          # shell 命令原文
    paths: list[str] = Field(default_factory=list)   # 涉及的文件路径
    patch_file_count: int | None = None              # patch 涉及的文件数
    summary: str = ""                   # 给审批区显示的一句话摘要
```

**第 3 步：编写 `src/pair_harness/core/ports.py`**

用 `typing.Protocol` 加 `@runtime_checkable` 定义全部接口，方法签名照抄设计文档 §5.1：

- `DialogueModel.stream_reply(request) -> AsyncIterator[DialogueEvent]`
- `CodingEngine.open_session / run_turn / cancel_turn / amend_turn / resolve_approval`
- `StateStore`：`save_message`、`list_conversations(project_id)`、`save_tool_run`、`get_engine_session(conversation_id)`、`save_engine_session`，均为 async
- `SpeechRecognizer.stream_transcribe`、`SpeechSynthesizer.synthesize`、`VoiceActivityDetector.detect`

**第 4 步：编写测试**

- `tests/unit/test_contracts.py`：模型 frozen 不可改（赋值抛错）；`ALLOWED_TRANSITIONS` 与设计文档 §6 的状态图一致；`ApprovalMode` 与 `ApprovalDecision` 各三个值；`ReviewerVerdict` 默认值。
- `tests/contract/test_ports.py`：为每个 Protocol 写一个最小 fake 类，断言 `isinstance(fake, Protocol)` 通过。

完成标准：两个测试文件全部通过。

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

实现步骤：

**第 1 步：搭档配置**

`config/pairs/phainon_ancient_machine.yaml` 的结构（B3 扩展另外两组时复用同一结构）：

```yaml
pair_id: phainon_ancient_machine
character:
  name: 白厄
  prompt_file: prompts/characters/phainon.md
  voice:
    voice_id: null        # 计划 B2 填入
assistant:
  name: 神秘的古代机械
  prompt_file: prompts/assistants/ancient_machine.md
  voice:
    voice_id: null
theme:
  character_colors: ["#C7D4E3", "#8AA4D4", "#3A548C", "#296CE1"]
  assistant_colors: ["#B08D57", "#C5A059", "#8C6B3F"]
```

`src/pair_harness/config/pairs.py`：用 PyYAML 加载为 `PairConfig` dataclass，校验 `prompt_file` 存在，缺失时抛 `PairConfigError`。角色卡正文从旧项目只读参考后手写最小版本，新应用运行时不读旧仓库。

**第 2 步：上下文组装 `core/context.py`**

- 角色模型请求 = 角色卡 + 当前聊天最近 20 条 user/character 消息 + 当前任务的进度摘要或结果摘要（不含原始工具输出）。
- 助手任务上下文 = 通用 Harness 规则 + 助手表达配置 + 项目路径 + `TaskRequest` + 少量与任务直接相关的近期对话。

**第 3 步：全局单活动 turn `core/engine_state.py`**

```python
class EngineState:
    def begin_turn(self, project_id: str, conversation_id: str, task_id: str) -> None:
        # 已有活动 turn 时抛 ActiveTurnExists
    def end_turn(self, task_id: str) -> None: ...
    def active(self) -> ActiveTurn | None: ...
```

**第 4 步：编排器 `core/orchestrator.py`**

`ConversationOrchestrator` 是唯一消息路由入口，按以下流程实现：

1. `handle_user_text(conversation_id, text, target)`：`target="character"` 时调 `DialogueModel.stream_reply`，逐 delta 更新角色消息；`target="assistant"` 时直接把文本归一化为 `TaskRequest`。
2. 收到 `character.final` 后：用 Orchestrator 写入身份字段并计算 `tts_eligible`（只有 `character.speech` 与 `assistant.natural_language` 为 True）；消息立即持久化。
3. `delegation` 为 `TaskRequestDraft` 时：校验字段，补齐 `task_id`、`conversation_id`、`origin_message_id`，经 `EngineState.begin_turn` 后交给 `CodingEngine.run_turn`。角色正文里出现命令、路径或 `@板砖` 字样但没有 `delegation`，一律不触发执行。
4. 消费 `EngineEvent` 流：按 `tool_call_id` 更新工具卡片；`approval.requested` 转给审批层（A3）；`turn.completed/failed` 后从 `tool.finished`、`file.patch` 和审批事件推导 `ExecutionReceipt`。助手文本自称成功但工具失败时，回执必须是失败。
5. 从回执派生 `CharacterResultSummary`（剔除路径、命令输出、堆栈、代码），再调一次角色模型生成人物化结果回应。
6. 修改与取消：`TaskAmendmentDraft` → `amend_turn`，修订号递增；用户直接发给助手的新指令优先级最高。

**第 5 步：测试适配器 `adapters/demo.py`**

- `ScriptedDialogueModel`：按脚本依次输出 `speech.delta` 和一个 `character.final`，脚本可指定是否携带 `TaskRequestDraft`。
- `ScriptedCodingEngine`：按固定脚本输出 `turn.started → assistant.delta → tool.started → tool.finished → file.patch → assistant.final → turn.completed`，可配置插入 `approval.requested` 和失败分支。不执行任何真实文件操作。

**第 6 步：`adapters/dialogue/openai_compatible.py`**

实现 `DialogueModel` 的 OpenAI 兼容流式客户端骨架：从环境变量读 `PAIR_HARNESS_DIALOGUE_BASE_URL / API_KEY / MODEL`，用 httpx 发流式请求，把增量文本包装成 `DialogueEvent`。计划 A 只做单元测试（mock httpx），不真实联网。

**第 7 步：`cli.py`**

`python -m pair_harness.cli --demo --project . --message "..."` 跑通 `user → character → assistant/tool → assistant → character` 的完整顺序，每行输出来源前缀，结尾明确打印“未执行真实文件工具”。

**第 8 步：测试**

- `test_pair_config.py`：YAML 正常加载；prompt 文件缺失时报错。
- `test_dialogue_boundary.py`：角色正文包含命令、路径、`@板砖` 但无 delegation 时，`CodingEngine` 一次都不被调用；`DialogueEvent.type` 只能是两个合法值。
- `test_task_lifecycle.py`：非法状态转换抛错；Draft 补齐三个关联字段；“直接交给助手”产出相同的 `TaskRequest` 结构。
- `test_engine_state.py`：活动 turn 存在时第二个任务被拒绝；事件固定回到发起聊天。
- `test_conversation_binding.py`：聊天的 `pair_id` 创建后不可改。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_pair_config.py tests\unit\test_dialogue_boundary.py tests\unit\test_task_lifecycle.py tests\unit\test_engine_state.py tests\unit\test_conversation_binding.py
.\.venv\Scripts\python.exe -m pair_harness.cli --demo --project . --message "请让古代机械创建 hello.txt"
```

建议提交：`feat: add isolated roleplay orchestration`

### A3. 项目级沙箱与三种审批模式

状态：**🟦 未开始，可以立即实施**

新增文件：

- `src/pair_harness/core/sandbox.py`
- `src/pair_harness/core/risk_rules.py`
- `src/pair_harness/core/approval.py`
- `src/pair_harness/adapters/reviewer.py`
- `config/risk_rules.yaml`
- `tests/unit/test_sandbox.py`
- `tests/unit/test_risk_rules.py`
- `tests/unit/test_approval_modes.py`
- `tests/unit/test_reviewer.py`

实现步骤：

**第 1 步：目录级沙箱 `core/sandbox.py`**

```python
class SandboxViolation(Exception):
    """操作试图越过项目根目录。"""


class ProjectSandbox:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve_write_path(self, path: str | Path) -> Path:
        # 1. 相对路径拼到 self.root 上；绝对路径原样保留
        # 2. 调 .resolve() 展开 .. 和符号链接
        # 3. 结果必须满足 is_relative_to(self.root)，否则抛 SandboxViolation
        # 4. Windows 下盘符不同一律视为越界

    def enforce_cwd(self, cwd: str | Path | None) -> Path:
        # None 返回 self.root；其余走 resolve_write_path 的校验
```

要点：所有文件写入、删除和命令执行的工作目录都必须先过 `ProjectSandbox`。校验失败的操作直接产生 `tool.finished`（状态 `denied`）和一条 `system` 消息，不进入审批流程。

**第 2 步：高风险规则表 `config/risk_rules.yaml` 与 `core/risk_rules.py`**

规则表是“帮我审核”模式的唯一判定依据。命中任一启用规则的操作算高风险，转审查智能体；未命中直接放行。完整文件内容如下，实施时原样创建：

```yaml
# 高风险操作判定规则表
# 只在“帮我审核”模式下使用；“请求批准”模式所有操作都走人工审批。
version: 1

# 文件工具层面直接判高风险的操作类型
high_risk_tool_kinds:
  - file_delete

# shell 命令正则（re.IGNORECASE，命中任一 pattern 即高风险）
shell_rules:
  - id: shell.delete
    label: 删除类命令
    patterns:
      - '\brm\b'
      - '\bdel\b'
      - '\berase\b'
      - '\brmdir\b'
      - '\bRemove-Item\b'
      - '\bshred\b'
  - id: shell.git_destructive
    label: git 破坏性命令
    patterns:
      - 'git\s+reset\s+--hard'
      - 'git\s+clean\s+-\w*f'
      - 'git\s+checkout\s+--'
      - 'git\s+push\s+.*(--force|-f\b)'
      - 'git\s+branch\s+-D'
      - 'git\s+commit\s+--amend'
      - 'git\s+stash\s+(drop|clear)'
      - 'git\s+rebase\b'
  - id: shell.network
    label: 网络访问
    patterns:
      - '\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm)\b'
      - '\b(ssh|scp|sftp|nc|ncat)\b'
      - 'git\s+(push|fetch|pull|clone)\b'
  - id: shell.package
    label: 依赖安装与环境变更
    patterns:
      - '\b(pip|pip3|npm|pnpm|yarn|bun|choco|winget|scoop|apt|apt-get|brew)\b\s+(install|add|remove|uninstall|upgrade)'
  - id: shell.system
    label: 系统级操作
    patterns:
      - '\b(reg|regedit|shutdown|restart-computer|taskkill|Stop-Process|Format-Volume|diskpart|sudo|chmod|chown)\b'

# 单次 patch 涉及文件数超过该值视为批量修改
patch_max_files: 5

# 敏感路径（fnmatch 风格，命中即高风险，读取和写入都算）
sensitive_paths:
  - '**/.env'
  - '**/.env.*'
  - '**/*.pem'
  - '**/*.key'
  - '**/id_rsa*'
  - '**/id_ed25519*'
  - '**/secrets*'
  - '**/credentials*'
```

`core/risk_rules.py` 提供：

```python
def load_risk_rules(path: Path) -> RiskRules: ...

def match_high_risk(op: PendingOperation, rules: RiskRules) -> str | None:
    """返回命中规则的中文 label；未命中返回 None。"""
    # 1. op.tool_kind 属于 high_risk_tool_kinds → 返回对应说明
    # 2. tool_kind == "shell"：逐条规则逐条 pattern 用 re.IGNORECASE 匹配 command
    # 3. tool_kind == "patch"：patch_file_count > patch_max_files → 命中
    # 4. op.paths 中任意路径 fnmatch 命中 sensitive_paths → 命中
    # 5. 以上都不命中 → None
```

**第 3 步：审批管理 `core/approval.py`**

```python
class ApprovalManager:
    def __init__(self, mode: ApprovalMode, rules: RiskRules, reviewer: Reviewer | None):
        self._session_allow: set[str] = set()   # “本对话内允许”的缓存

    async def gate(self, op: PendingOperation) -> ApprovalDecision: ...
```

三种模式的分流逻辑：

- `FULL_AUTO`：直接返回 `ALLOW`，不产生审批事件，工具事件照常持久化。
- `REQUEST_APPROVAL`：先算操作签名（见下），命中 `self._session_allow` 直接放行；否则发出 `approval.requested`（payload 含操作摘要、三个选项、`actor="user"`），挂起等待 UI 决策。用户选“本对话内允许”时把签名写入缓存，当前聊天结束时清空。
- `REVIEW`：先跑 `match_high_risk`；未命中返回 `ALLOW`；命中则把操作和近期上下文交给 `reviewer.review(...)`，裁决写入 `approval.requested / approval.resolved`（`actor="reviewer"`，payload 含 `reason` 和 `suggestion`）。否决时把理由和调整建议作为一条 `system` 消息回给助手，助手据此修改方案后重试。

操作签名规则（保持简单，不要做得更细）：shell 取命令第一个单词（如 `git`、`pip`），文件操作取 `tool_kind + 路径后缀名`，patch 统一为 `patch`。

**第 4 步：审查智能体 `adapters/reviewer.py`**

```python
class Reviewer(Protocol):
    async def review(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict: ...


class ScriptedReviewer:
    """计划 A 的测试实现：按预先给定的 ReviewerVerdict 列表依次返回。"""


class DialogueModelReviewer:
    """计划 B 的真实实现：复用当前 DialogueModel 适配器。
    提示词要求模型只输出 JSON：{"allow": bool, "reason": str, "suggestion": str}。
    输入只包含 PendingOperation 摘要和当前聊天中用户最后发送的 3 条消息，
    不给任何工具。"""
```

约束（与设计文档 §6.3 一致）：提示词先检查用户是否直接要求或明确批准了当前操作，再结合风险规则裁决。审查智能体不能修改文件、调用执行工具、创建子助手或继续委派；否决时 `reason` 和 `suggestion` 都必须非空，测试实现也要遵守。

**第 5 步：与 Orchestrator 的接线**

`EngineEvent` 进入 Orchestrator 后，凡是会产生文件写入、删除、shell 或 patch 的 `tool.started`，先包装成 `PendingOperation` 依次过 `ProjectSandbox` 和 `ApprovalManager.gate`，通过后才允许引擎继续。计划 A 用 `ScriptedCodingEngine` 验证整条链路，不碰真实文件。

**第 6 步：测试**

- `test_sandbox.py`：根目录内相对路径放行；`..` 越界拒绝；目录外绝对路径拒绝；指向目录外的符号链接拒绝（用 `tmp_path` 建真实软链）；`enforce_cwd(None)` 返回项目根。
- `test_risk_rules.py`：每个规则类别至少一个命中用例和一个不命中用例；`patch_file_count` 边界（5 放行、6 命中）；敏感路径命中。
- `test_approval_modes.py`：三种模式分流正确；“本对话内允许”第二次同签名操作不再请求；否决后 turn 以失败结束。
- `test_reviewer.py`：低风险操作不经过审查智能体；高风险操作经过；否决 verdict 的 `reason` 和 `suggestion` 非空且回给助手。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_sandbox.py tests\unit\test_risk_rules.py tests\unit\test_approval_modes.py tests\unit\test_reviewer.py
```

建议提交：`feat: add sandbox and approval modes`

### A4. Codex app-server 适配器的离线实现

状态：**🟦 未开始，可以立即实施；真实子进程联调等待计划 B**

新增文件：

- `src/pair_harness/settings.py`
- `src/pair_harness/adapters/codex/transport.py`
- `src/pair_harness/adapters/codex/codec.py`
- `src/pair_harness/adapters/codex/engine.py`
- `tests/fixtures/fake_codex_app_server.py`
- `tests/unit/test_codex_event_mapping.py`
- `tests/integration/test_codex_transport.py`

实现步骤：

**第 1 步：配置 `settings.py`**

`PAIR_HARNESS_CODEX_BIN` 保存 Codex 可执行文件路径或命令名。适配器固定追加 `app-server` 参数，不接收任意命令字符串，避免把设置项变成命令注入入口。

**第 2 步：传输层 `transport.py`**

`JsonlProcessTransport` 负责：启动子进程、给每个请求分配 id 并关联响应、单一 `asyncio` 读取循环把 stdout 按行解析为 dict 分发给等待方。进程退出时唤醒所有等待方并抛 `TransportClosed`。

**第 3 步：事件编解码 `codec.py`**

`CodexCodec` 把 app-server 原生通知映射为稳定 `EngineEvent`。映射关系（照此实现，原生字段名以联调时实际为准，先在 fake 里约定）：

| 原生通知 | EngineEvent.type |
|---|---|
| turn 开始 | `turn.started` |
| 助手文本增量 | `assistant.delta` |
| 工具调用开始/进度/结束 | `tool.started` / `tool.progress` / `tool.finished` |
| 文件补丁 | `file.patch` |
| 审批请求/已处理 | `approval.requested` / `approval.resolved` |
| turn 成功/失败 | `turn.completed` / `turn.failed` |

**第 4 步：引擎 `engine.py`**

`CodexAppServerEngine` 实现 `CodingEngine` 全部五个方法：`thread_id` 私有解析并编码进 `EngineSessionRef.opaque`，应用层只保存和回传；实现取消、任务修改和审批响应通道；进程退出转换为 `turn.failed`。不实现任何 MCP 客户端、注册表、代理层或网关。沙箱策略映射（workspace-write）在计划 B1 联调时接入，本阶段只在 `open_session` 参数里留出位置。

**第 5 步：fake 与测试**

`tests/fixtures/fake_codex_app_server.py` 用 `asyncio.Queue` 模拟 stdin/stdout 的 app-server，不启动真实 Codex。

- `test_codex_event_mapping.py`：上表每种映射至少一个用例；未知通知被安全忽略。
- `test_codex_transport.py`：请求响应关联；进程中途退出转换为 `turn.failed`。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_codex_event_mapping.py tests\integration\test_codex_transport.py
```

建议提交：`feat: add offline codex app-server adapter`

### A5. 最小 PyQt5 双模式界面

状态：**🟦 未开始，可以立即实施**

新增文件：

- `src/pair_harness/__main__.py`
- `src/pair_harness/ui/app.py`
- `src/pair_harness/ui/main_window.py`
- `src/pair_harness/ui/message_list.py`
- `src/pair_harness/ui/tool_card.py`
- `src/pair_harness/ui/input_bar.py`
- `src/pair_harness/ui/approval_bar.py`
- `src/pair_harness/ui/qt_bridge.py`
- `tests/ui/test_main_window.py`
- `tests/ui/test_tool_card.py`
- `tests/ui/test_input_bar.py`
- `tests/ui/test_approval_bar.py`

实现步骤：

**第 1 步：应用骨架**

使用 PyQt5 与 qasync，`app.py` 负责把 `asyncio` 事件循环挂进 Qt。`qt_bridge.py` 提供 asyncio → Qt signal 的单向桥，PyQt 组件不直接调用模型、ASR、TTS 或工具，一切经过 `ConversationOrchestrator`。

**第 2 步：主窗口布局**

- 首阶段只显示白厄与神秘的古代机械。
- 聊天模式：全宽角色对话，发送目标固定为白厄。
- 协作模式：左侧角色对话，右侧助手工作台（自然语言 + 工具卡片），底部共享输入区。
- 配色使用设计文档 §4.5 确认的蓝色与新铸青铜金；用户、工具、系统消息用 §4.5 的中性样式。

**第 3 步：输入区 `input_bar.py`**

- 发送对象选择（白厄 / 神秘的古代机械），选助手时隐藏 VAD 选项。
- 输入方式：VAD、按住说话、文字。
- 左下角放一个 `QComboBox` 作为审批模式切换（布局参考 Codex），三项依次是“请求批准”“帮我审核”“完全允许运行”。切换后立即写入项目设置（A6 的 `projects.approval_mode`），打开项目时恢复上次选择。

**第 4 步：审批区 `approval_bar.py`**

- 一个横跨窗口整个宽度、位于输入区正下方的 `QFrame`，默认隐藏。
- 请求批准模式下收到 `approval.requested` 时展开：第一行显示操作摘要（来自 `PendingOperation.summary`），第二行三个按钮“允许”“本对话内允许”“否决”。
- 用户点击任一按钮后：发出 `decided(ApprovalDecision)` 信号，区域立即隐藏；裁决结果作为 `system` 卡片留在消息时间线。
- 多个审批请求排队，逐条显示，不同时展开。
- 帮我审核模式下只显示“审查中…”和审查智能体的最终裁决文字，不显示按钮；完全允许运行模式下永不出现。

**第 5 步：工具卡片 `tool_card.py`**

按 `tool_call_id` 更新同一张卡片：第一行简短自然语言说明，命令、文件变更和检查结果默认折叠，点击展开；卡片状态随 `tool.started/progress/finished` 流式更新。

**第 6 步：测试**

`QT_QPA_PLATFORM=offscreen` 下运行：

- `test_main_window.py`：双模式切换布局正确；搭档轨道只显示白厄一组。
- `test_tool_card.py`：同一 `tool_call_id` 更新同一卡片；默认折叠。
- `test_input_bar.py`：选助手后 VAD 隐藏；模式下拉框三项齐全且切换发信号。
- `test_approval_bar.py`：默认隐藏；收到请求展开；点击按钮后隐藏并发出正确 `ApprovalDecision`；审查模式无按钮。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ui,dev]"
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests\ui
.\.venv\Scripts\python.exe -m pair_harness --demo
```

建议提交：`feat: add pyqt5 roleplay workbench`

### A6. SQLite、项目与聊天恢复

状态：**🟦 未开始，可以立即实施**

新增文件：

- `src/pair_harness/core/repository.py`
- `src/pair_harness/storage/schema.sql`
- `src/pair_harness/storage/sqlite_store.py`
- `src/pair_harness/app_paths.py`
- `src/pair_harness/ui/project_library.py`
- `tests/unit/test_sqlite_store.py`
- `tests/integration/test_conversation_restore.py`

实现步骤：

**第 1 步：数据目录 `app_paths.py`**

默认目录 `%LOCALAPPDATA%\PairHarness\`，含 `pair_harness.db` 和 `cache\`。支持 `--data-dir` 覆盖，方便演示和测试。不保存原始麦克风录音。

**第 2 步：建表 `storage/schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS projects (
  project_id      TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  root_path       TEXT NOT NULL,
  approval_mode   TEXT NOT NULL DEFAULT 'request_approval',
  archived        INTEGER NOT NULL DEFAULT 0,
  last_opened_at  TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL REFERENCES projects(project_id),
  pair_id         TEXT NOT NULL,
  title           TEXT,
  last_mode       TEXT,
  archived        INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  message_id      TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
  pair_id         TEXT,
  turn_id         TEXT,
  source          TEXT NOT NULL,
  kind            TEXT NOT NULL,
  text            TEXT,
  payload_json    TEXT,
  tts_eligible    INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_runs (
  tool_run_id     TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
  task_id         TEXT,
  engine_turn_id  TEXT,
  tool_call_id    TEXT,
  sequence        INTEGER,
  status          TEXT,
  summary         TEXT,
  detail          TEXT
);

CREATE TABLE IF NOT EXISTS engine_sessions (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(conversation_id),
  engine_type     TEXT NOT NULL,
  session_ref     TEXT NOT NULL,
  last_turn_id    TEXT,
  restore_state   TEXT
);
```

注意 `projects.approval_mode` 存 A5 输入区下拉框的选择，取值是 `ApprovalMode` 的三个枚举值。

**第 3 步：存取层 `sqlite_store.py` 与 `repository.py`**

`sqlite_store.py` 实现 `StateStore` 接口；`repository.py` 提供项目与聊天的创建、切换、归档、恢复。行为要求：

- 项目绑定一个文件夹；每个项目可保存多次聊天；每条聊天固定一组搭档。
- 消息在生成完成时立即写入，不依赖退出时集中保存。
- 只保存最终助手消息和最终工具卡片，不保存流式增量。
- 纯角色聊天延迟创建 `engine_sessions` 记录；新聊天不继承旧聊天内容或编程会话。
- 项目路径失效时历史仍可读，协作模式暂停；从应用移除项目只归档，不动磁盘文件。

**第 4 步：项目与聊天库 `ui/project_library.py`**

主窗口左上角入口，展开后可创建或切换项目，按当前项目列出全部未归档聊天（显示固定搭档、标题、更新时间）。

**第 5 步：测试**

- `test_sqlite_store.py`：五张表读写；`approval_mode` 持久化；消息字段与 `Message` 模型往返一致。
- `test_conversation_restore.py`：写入消息后重建 store，消息和工具卡片完整恢复；归档项目可恢复。

验收命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_sqlite_store.py tests\integration\test_conversation_restore.py
.\.venv\Scripts\python.exe -m pair_harness --demo --data-dir .\.tmp\demo-data
```

关闭并重新运行第二条命令，消息和工具卡片必须恢复。

建议提交：`feat: persist projects and conversations`

### A7. 语音规则、麦克风层与测试语音闭环

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

实现步骤：

**第 1 步：采集与播放 `sounddevice_io.py`**

列出输入/输出设备，采集 16 kHz 单声道 PCM，提供播放队列。真实设备不可用时给出明确错误，不静默失败。

**第 2 步：测试语音适配器 `audio/demo.py`**

Demo ASR 接收注入文本产出转写事件；Demo TTS 产出测试音频或状态事件；VAD 用注入事件模拟监听、说话开始、结束和误触发。

**第 3 步：语音策略 `voice_policy.py`**

- 输入矩阵：聊天模式和“对角色说”提供 VAD、按键说话、文字；“直接交给助手”隐藏 VAD。
- TTS 准入：只有 `character.speech` 和 `assistant.natural_language` 进入 `SpeechQueue`；命令、路径、代码、工具、审批和系统消息全部静音。助手 Markdown 按块拆分，只有自然语言段落入队。
- 播放时暂停 VAD；按下说话键先停止当前播放并清空待播队列。

**第 4 步：界面 `audio_controls.py`**

按住说话按钮、VAD 开关、停止播放按钮，状态与 `voice_policy` 一致。

**第 5 步：测试**

- `test_input_matrix.py`：三种场景下的可用输入方式与设计文档 §7.1 一致。
- `test_tts_filter.py`：各类 `source/kind` 消息的 `tts_eligible` 判定正确；含代码块和命令的助手消息只有自然语言段入队。
- `test_speech_queue.py`：播放中暂停 VAD；按说话键清空队列。
- `test_audio_controls.py`：控件状态联动。

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
- 沙箱拦截目录外操作，三种审批模式可以切换和演示。
- 麦克风层与全部语音交互状态可演示。
- 所有测试使用测试适配器，不依赖外部 API。

建议提交：`feat: add demo voice interaction loop`

## 5. 计划 B：完整 MVP 闭环

### B1. 外部模型 API 接入（DeepSeek 优先）与 Codex app-server

状态：**⏳ 未开始，等待外部前置**

用户需要准备：

- 可以由 Python `subprocess` 启动的 Codex app-server 命令。
- Codex 的本地登录或认证状态。
- 角色对话 API 的 base URL、API Key 和模型名。**首选 DeepSeek 官方 API**（`https://api.deepseek.com`，模型从预设列表选择）；其他 OpenAI 兼容端点通过同一套配置接入。

配置项：

```text
PAIR_HARNESS_CODEX_BIN
PAIR_HARNESS_DIALOGUE_BASE_URL
PAIR_HARNESS_DIALOGUE_API_KEY
PAIR_HARNESS_DIALOGUE_MODEL
```

#### B1.1 外部模型 API 接入设计（参考 DeepSeek-Reasonix）

角色对话模型的外部 API 接入是 MVP 的明确功能，参考仓库内 `DeepSeek-Reasonix/`（MIT License）的实现方式，但不引入 Go 代码本身：

- **供应商预设 + 环境变量密钥**：参考 `DeepSeek-Reasonix/internal/config/provider_presets.go` 与其 `reasonix.example.toml` 的 `[[providers]]` 模式——预设只保存 base URL、模型列表、默认模型和上下文窗口等公开信息，API Key 一律经环境变量（如 `DEEPSEEK_API_KEY`）注入，配置文件永不持有密钥。本项目落为 `Settings` 扩展 + 环境变量，预设数据进入 `config/`。
- **按 Base URL 识别后端**：参考 `internal/provider/openai/host.go` 的 `IsDeepSeek` 等识别函数——识别 `api.deepseek.com` / `*.deepseek.com` 后自动应用 DeepSeek 请求形态，用户只填 base URL 即可获得正确行为。
- **DeepSeek 请求形态**：参考 `docs/REASONING_PROVIDERS.zh-CN.md` 与 `internal/provider/openai/` 的实现——`thinking.type` 控制思考开关、`reasoning_effort` 档位归一化、依赖 DeepSeek 自动前缀缓存降低重复提示词成本；角色扮演对话默认开启流式输出。
- **请求健壮性**：参考 `internal/provider/retry.go`（有界重试、尊重 `Retry-After`、响应体读取超时、401/403 区分瞬时拒绝与配置错误）与 `stream_error.go`——本阶段在 Python 适配器中实现等价语义，不照搬代码。
- **提示词装配与委派解析**属优化计划 O3.2（`docs/plans/2026-08-11-harness-optimization-plan.md`），先于本阶段联调完成；B1 只负责让装配好的请求在真实 API 上跑通。

新增测试：

- `tests/unit/test_dialogue_provider_presets.py`
- `tests/unit/test_deepseek_request_shape.py`
- `tests/integration/test_text_loop_live.py`

实施内容：

- 对可执行命令运行 `app-server --help` 预检。
- 实现供应商预设加载与 DeepSeek 请求形态，离线单测验证请求体字段（不发起真实请求）。
- 真实创建和恢复 app-server 会话。
- 把目录级沙箱映射到 app-server 的 workspace-write 策略（按优化计划 O3.1 的统一审批设计执行）。
- 在临时项目内执行一次真实文件修改任务，并验证三种审批模式的实际拦截行为。
- 验证工具事件、文件差异和真实回执。
- 让白厄只依据 `CharacterResultSummary` 作结果回应。
- 把 `DialogueModelReviewer` 接到真实对话模型，验证否决理由和调整建议的质量。

验收命令：

```powershell
$env:PAIR_HARNESS_CODEX_BIN = "C:\可执行路径\codex.exe"
$env:PAIR_HARNESS_DIALOGUE_BASE_URL = "https://api.deepseek.com"
$env:PAIR_HARNESS_DIALOGUE_API_KEY = "..."
$env:PAIR_HARNESS_DIALOGUE_MODEL = "deepseek-v4-flash"

.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_dialogue_provider_presets.py tests\unit\test_deepseek_request_shape.py
New-Item -ItemType Directory -Path .\.tmp\codex-smoke -Force | Out-Null
.\.venv\Scripts\python.exe -m pair_harness.cli --real --pair phainon_ancient_machine --project .\.tmp\codex-smoke --message "请让古代机械创建 hello.txt，内容为 hello"
Get-Content -LiteralPath .\.tmp\codex-smoke\hello.txt
```

完成标准：真实文件存在，旧聊天可以恢复同一编程会话，新聊天不会继承旧会话；DeepSeek 端点上角色回复、结构化委派与结果回应全部可用；切换任意 OpenAI 兼容端点只需改三个环境变量。

建议提交：`feat: connect live dialogue and codex backends`

### B2. Silero VAD 与 Qwen 流式 ASR/TTS

状态：**⏳ 未开始，等待外部前置**

用户需要准备：

- `DASHSCOPE_API_KEY`。已有。

- 服务地域和对应 WebSocket 地址：

  API Host

  llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com

  OpenAI 兼容地址

  https://llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com/compatible-mode/v1

  DashScope

  https://llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com/api/v1

- 白厄与神秘古代机械的参考语音，或已经创建的两个 `voice_id`。
  白厄参考语音：E:\AI\HSR Partner Harness\assets\reference_voices\白厄 下。神秘古代机械使用声音设计进行。
  参考文档：

  "E:\AI\HSR Partner Harness\docs\referances\千问声音复刻文档.md"
  "E:\AI\HSR Partner Harness\docs\referances\千问声音设计文档.md"
  "E:\AI\HSR Partner Harness\docs\referances\千问语音识别文档.md"

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
- 三组输入矩阵、工具权限、审批模式和 TTS 规则一致。

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
- 三种审批模式在真实 Codex 后端上行为正确。
- Qwen 流式 ASR/TTS 与本地 VAD 完成闭环。
- 所有已确认的身份、输入矩阵和静音规则通过验收。

建议提交：`feat: add all companion pairs`

## 6. 用户准备清单

### 启动 B1 前

- [ ] 提供可从终端启动的 Codex app-server 命令或可执行路径。
- [ ] 确认 Codex 已登录。
- [ ] 在本地 `.env` 中填写角色对话 API 配置；首选 DeepSeek（`DEEPSEEK_API_KEY` 或映射到 `PAIR_HARNESS_DIALOGUE_API_KEY`），也可填其他 OpenAI 兼容端点。

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
| B1：外部模型 API（DeepSeek 优先）+ Codex | ⏳ 等待外部前置 | 0% |
| B2：Qwen 语音 | ⏳ 等待外部前置 | 0% |
| B3：另外两组搭档 | ⬜ 后续 | 0% |

## 8. 明确不进入计划

- 自定义 MCP 网关、统一代理层或工具市场
- 复杂多 Agent 和动态拓扑
- 永久自治或自动生成目标
- RBAC、审计平台和遥测体系
- 容器集群和微服务编排
- Electron、React 和 3D/MMD 链路
- 字面触发词 `@板砖`、梦境监督器等隐藏多轮链路
- 自动长期记忆和大规模测试矩阵
