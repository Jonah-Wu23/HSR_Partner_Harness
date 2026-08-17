# 强视觉 AI 交付：角色卡状态枚举与稳定样例数据

> 配套实现：`src/pair_harness/character_cards/states.py`（枚举唯一来源，本文件与之同步）
> 样例数据：`docs/character-card/samples/角色库样例.json`
> 边界：本文件只冻结状态与数据含义，不规定视觉风格、布局与控件形态。

## 1. 状态枚举（冻结）

### 角色卡状态 `CharacterCardState`（`card.state`）

| 值 | 含义 | 进入条件 | 界面必须如实表达 |
|---|---|---|---|
| `draft` | 草稿 | 新建未保存 / 编辑未落库 | 与已保存卡可区分；不显示「已保存」 |
| `saved` | 已保存 | 本应用创建或编辑后成功落库 | 显示保存成功与更新时间 |
| `imported` | 导入卡 | 酒馆 JSON/PNG 导入成功落库 | 显示来源、格式版本、导入摘要（世界书条目数、问候数、已识别扩展、兼容报告） |
| `invalid` | 无效卡 | 导入解析失败（JSON 非法、缺 `name`、PNG 元数据损坏等） | 保留并展示原始错误文本；不得显示为空卡或成功导入 |

### 音色状态 `CharacterVoiceState`（`card.voice_state`）

| 值 | 含义 | 进入条件 | 界面必须如实表达 |
|---|---|---|---|
| `voice_unconfigured` | 未配置 | 未选择参考音频/声音描述 | 引导配置；不得假装已有音色 |
| `voice_creating` | 创建中 | 已向 DashScope 提交创建请求、等待真实结果 | 进行中状态；不可重复触发同一创建 |
| `voice_ready` | 已就绪 | 创建成功并保存真实 `voice_id` | 可试听；`voice_id` 可核对 |
| `voice_failed` | 失败 | 创建失败 | 展示供应商原始错误（`voice.last_error`）与重试入口；不清空已有配置 |

两组状态正交：任何卡状态可与任何音色状态组合（如 `imported + voice_failed`）。真实失败必须保持失败外观，禁止用成功色、完成文案或空内容掩盖。`target_model` 恒为 `qwen-audio-3.0-tts-flash`（ASR 恒为 `qwen-audio-3.0-asr-flash-streaming`），界面只读展示，无任何模型输入入口。

## 2. 样例数据说明

`samples/角色库样例.json` 覆盖全部 4×4 状态组合所需的代表场景（5 张卡）：

- `card-01`（imported + voice_ready）：白厄导入卡，含完整 `import_summary` 与真实兼容报告结构（`applied` / `preserved` / `not_executed` / `normalized_from_root` / `warnings` / `errors`），世界书 20 条、问候 6 条。
- `card-02`（draft + voice_unconfigured）：最小草稿。
- `card-03`（saved + voice_creating）：创建进行中。
- `card-04`（invalid + voice_unconfigured）：JSON 损坏，`invalid_reason` 保留原始错误。
- `card-05`（saved + voice_failed）：`last_error` 使用真实验证记录中出现过的 DashScope 错误结构。

样例数据是手工构造的界面开发输入，**不是**功能验收证据；验收必须接真实 Sidecar 状态。

## 3. 界面需要承载的数据字段（从数据契约摘取）

- 列表/详情：`name`、`state`、`voice_state`、`source`、`updated_at`、`tags`。
- 导入结果展示：`import_summary.format`、`world_book_entry_count`、`greeting_count`、`recognized_extensions`、`compat_report`（其中 `not_executed` 需以「已保留但未运行」呈现，如声明式指令面板）。
- 音色区：`voice.creation_mode`（clone/design）、`voice.prefix`、`voice.last_error`、固定模型只读文本。
- 草稿编辑：标准字段（名称/简介/性格/场景/首句/示例对话/标签/头像等）+ 高级区（世界书、HSR 扩展、depth prompt、原始数据查看）。

## 4. 对接真实数据的约定

- 运行期以 Python 层为权威：卡片与音色状态由业务层按真实结果写入；前端只消费状态与样例同构的数据。
- 集成阶段（V0.3.3+）状态经由 Sidecar 快照/事件下发；本文枚举值即协议字面值，不得改名或增删（新增值须先改契约再同步双方）。
