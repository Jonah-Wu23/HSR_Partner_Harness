# 酒馆字段与 HSR 扩展字段映射表

> 配套契约：`角色卡数据契约.md`（hsr schema 1.0）
> 用途：导入/导出实现、强视觉 AI 字段核对、V0.3.7 酒馆双向兼容开发的对照基准。

## 1. 酒馆标准字段 → 内部模型

| 酒馆位置（v3） | 内部模型（`pair_harness.character_cards`） | 导入 | 导出 v3 |
|---|---|---|---|
| `spec` / `spec_version` | `CharacterCard.spec` / `.spec_version` | 识别 v2/v3；缺失按 v2 兼容并告警 | 固定 `chara_card_v3` / `3.0` |
| `data.name`（回退根级） | `CharacterCard.name` | data 优先 | data + 根级副本 |
| `data.description` | `.description` | 同上 | 同上 |
| `data.personality` | `.personality` | 同上 | 同上 |
| `data.scenario` | `.scenario` | 同上 | 同上 |
| `data.first_mes` | `.first_mes` | 同上 | 同上 |
| `data.mes_example` | `.mes_example` | 同上 | 同上 |
| `data.creator_notes` | `.creator_notes` | 同上 | 同上 |
| `data.system_prompt` | `.system_prompt` | 同上 | 同上 |
| `data.post_history_instructions` | `.post_history_instructions` | 同上 | 同上 |
| `data.tags` | `.tags` | data 优先 | 同上 |
| `data.creator` | `.creator` | 同上 | 同上 |
| `data.character_version` | `.character_version` | 同上 | 同上 |
| `data.alternate_greetings` | `.alternate_greetings` | 同上 | 同上 |
| `data.group_only_greetings` | `.group_only_greetings` | 同上 | 同上 |
| `data.character_book` | `.character_book: CharacterBook` | 见 §3 | 全量写回 |
| `data.extensions.{第三方键}` | `.extensions`（dict，原样） | 原样保留 | 原样写回 |
| `data.extensions.depth_prompt` | `.extensions["depth_prompt"]` + 只读视图 `.depth_prompt` | 原样保留（不复制到标准字段） | 原样写回 |
| 根级未知字段（`creatorcomment`、`avatar`、`talkativeness`、`fav`、`create_date` 等） | `.root_extras`（dict，原样） | 原样保留 | 写回根级 |
| `data` 下未知字段 | `.data_extras`（dict，原样） | 原样保留 | 写回 `data` |
| PNG `tEXt:ccv3` / `tEXt:chara` | `read_png_card` / `write_png_card` | ccv3 优先 | 仅写 ccv3，头像块字节不变 |

注：SillyTavern 把根级 `avatar`、`talkativeness`、`fav` 视为 UI 元数据，同时在 `data.extensions` 有镜像（如白厄样例）。两侧都是「未知但合法」数据，各自原样保留，不在中间再造第三份。

## 2. mufy 参考内容 → `data.extensions.hsr`

mufy 模板中**酒馆标准字段已经能承载的内容**（名称、标签、简介、人设文本、开场白、示例对话、世界书）继续使用标准字段；其余模块按下表进入 HSR 扩展，唯一权威位置：

| mufy 模板板块 | `hsr` 字段 | 类型 | 承载内容 |
|---|---|---|---|
| （模板头：角色信息/标签） | 标准字段 `name` / `tags` / `description` | — | 不进 hsr |
| 板块一 世界观构建：世界基底、地理与城市 | `world_architecture` | dict | `world_foundation`、`geography`（含 districts、key_locations） |
| 板块一 社会系统、文化与哲学 | `world_architecture` | dict | `social_systems`、`culture_philosophy` |
| 板块二 身份锚点、物理存在 | `character_architecture` | dict | `identity`、`physical_presence` |
| 板块二 语言指纹系统 | `character_architecture` | dict | `voice_system`（语言画像、语气光谱、register shifts、非语言沟通） |
| 板块二 行为状态机 | `character_architecture` | dict | `behavioral_states`（默认态、情绪光谱、特殊状态） |
| 板块二 心理内核、生活方式、背景故事、元指令 | `character_architecture` | dict | `psychological_core`、`lifestyle`、`background`、`meta_instructions` |
| B. 关系阶段门控 | `relationship_system` | dict | `relationship_gates`（阶段、回退、不可逆节点、与用户关系） |
| C. 时间轴事件 | `event_system` | dict | `timeline_events`（绝对/相对时间线） |
| A. 开局模式 | `event_system` | dict | `opening_scenarios` |
| D. 条件触发器 | `event_system` | dict | `conditional_triggers` |
| E. 随机事件池 | `event_system` | dict | `random_events` |
| 叙事规则/文风 | `narrative_rules` | dict | `pacing`、`perspective`、`dialogue_rules`、`violence_rules`、`absolute_bans` |
| F. 指令面板 | `command_panels` | list[dict] | 声明式面板定义（`command`、`function`、`output_format` 等）；**只保留数据 + 声明式呈现，永不执行** |
| 角色头像 | `avatar_asset` | dict | 受管理资产引用、来源、导出信息（§6 of 契约） |
| 角色音色 | `voice_profile` | dict | 音色 ID 绑定与创建状态（§7 of 契约；模型固定 `qwen-audio-3.0-tts-flash`） |
| 物品栏、资料库等 mufy 平台功能 | 暂无对应运行能力 | — | 属于酒馆/mufy 平台特性；作为未知第三方数据按原样保留路径处理（`extensions`/`root_extras`），运行期「已保留但未运行」，待后续版本决定是否纳入 |

## 3. 世界书条目映射

| 酒馆条目字段 | 内部 `WorldBookEntry` | 备注 |
|---|---|---|
| `id` | `entry_id` | int/str 原样 |
| `keys` / `secondary_keys` | `keys` / `secondary_keys` | 只用于条目内容激活 |
| `content` / `comment` | `content` / `comment` | 原样 |
| `constant` / `selective` / `enabled` | 同名 | 布尔 |
| `insertion_order` / `position` / `use_regex` | 同名 | position 保留原始形态（str/int） |
| `case_sensitive` / `name` / `priority`（v3） | 同名 | 缺省 None，不导出 |
| `extensions`（ST：probability、depth、role、selectiveLogic、display_index 等约 30 键） | `extensions` | **整体原样保留与写回**，不逐键解释 |
| 其他未知顶层字段 | `extras` | 原样写回 |

## 4. 固定模型与导入卡的边界

- `hsr.voice_profile.target_model` 恒为 `qwen-audio-3.0-tts-flash`；ASR 恒为 `qwen-audio-3.0-asr-flash-streaming`（不随卡导入变化）。
- 导入卡任何位置出现其他模型名（含第三方扩展如 `regex_scripts` 内的配置）：数据原样保留，但**不改变应用实际使用的固定模型**，`voice_profile` 层强制归一并告警。
- 任何脚本/HTML（`command_panels` 的 `output_format`、`regex_scripts`、开场设计代码块等）只作为数据保留；兼容报告标记「已保留但未运行」。
