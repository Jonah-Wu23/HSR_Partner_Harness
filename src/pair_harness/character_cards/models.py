"""内部角色卡数据契约（V0.4.0 逻辑底座）。

本模块是纯数据模型，不依赖 SQLite、Sidecar、React 状态或当前配对系统。

契约原则（与 AGENTS.md 一致）：

- 酒馆标准已有的数据只保存在标准字段，唯一权威位置；
- 酒馆标准没有覆盖的内容进入 ``data.extensions.hsr``，同样唯一；
- 未识别但合法的第三方扩展原样保留，不做语义猜测、不执行任何内容；
- 世界书关键词只用于角色卡内容激活，代码不得据此猜测用户意图或任务成败。

各字段的权威位置、类型、默认值、必填性与导入导出方式见
``docs/character-card/角色卡数据契约.md``。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 固定语音产品常量：TTS、声音复刻、声音设计永久绑定该模型，
# 用户、界面、配置文件与导入的角色卡都不能修改。
FIXED_TTS_MODEL = "qwen-audio-3.0-tts-flash"
FIXED_ASR_MODEL = "qwen-audio-3.0-asr-flash-streaming"

# HSR 扩展当前契约版本。
HSR_SCHEMA_VERSION = "1.0"


@dataclass
class WorldBookEntry:
    """酒馆世界书条目（character_book.entries 元素）。

    已知字段进入类型化成员；条目 ``extensions`` 与其余未知顶层字段
    原样保留在 :attr:`extensions` / :attr:`extras`，导出时写回。
    """

    keys: list[str] = field(default_factory=list)
    secondary_keys: list[str] = field(default_factory=list)
    content: str = ""
    enabled: bool = True
    constant: bool = False
    selective: bool = True
    insertion_order: int = 100
    position: str | int = "before_char"
    use_regex: bool = True
    comment: str = ""
    entry_id: int | str | None = None
    # Character Book v3 增补字段；缺失时保持 None，导出时不写入。
    name: str | None = None
    case_sensitive: bool | None = None
    priority: int | None = None
    extensions: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)


@dataclass
class CharacterBook:
    """酒馆世界书（character_book）。"""

    entries: list[WorldBookEntry] = field(default_factory=list)
    name: str = ""
    description: str = ""
    scan_depth: int | None = None
    token_budget: int | None = None
    recursive_scanning: bool | None = None
    extensions: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)


@dataclass
class AvatarAsset:
    """``data.extensions.hsr.avatar_asset``：内部头像资产引用。

    只保存引用与来源信息，不把图片二进制写进角色卡 JSON；
    头像字节由 PNG 编解码（``png.py``）与受管理资产目录持有。
    """

    asset_id: str = ""
    source: str = "none"  # none | png_import | user_upload | json_avatar_field
    source_ref: str = ""
    mime_type: str = "image/png"
    exported_in_png: bool = True
    # 未来契约版本新增的未知字段原样保留。
    extras: dict = field(default_factory=dict)


@dataclass
class VoiceProfile:
    """``data.extensions.hsr.voice_profile``：角色与音色的绑定数据。

    永远不保存明文 API Key；Key 属于本地账号的凭据存储。
    ``target_model`` 固定为 :data:`FIXED_TTS_MODEL`，导入外部卡时
    即使含其他模型字段也不得改变该值。
    """

    state: str = "voice_unconfigured"  # CharacterVoiceState 值
    voice_id: str = ""
    target_model: str = FIXED_TTS_MODEL
    creation_mode: str = ""  # clone | design | ""
    prefix: str = ""
    reference_audio_asset: str = ""
    reference_audio_url: str = ""
    voice_prompt_asset: str = ""
    last_error: str = ""
    updated_at: str = ""
    # 未来契约版本新增的未知字段原样保留。
    extras: dict = field(default_factory=dict)


@dataclass
class HsrExtension:
    """``data.extensions.hsr``：酒馆标准未覆盖的 HSR 高级扩展。

    内容块（world_architecture 等）是角色作者的结构化自由内容，
    本层只约定键名与粗类型（对象/数组），不解释其语义、不检测意图；
    运行时按确定顺序装配为角色提示词模块。
    """

    schema_version: str = HSR_SCHEMA_VERSION
    world_architecture: dict = field(default_factory=dict)
    character_architecture: dict = field(default_factory=dict)
    relationship_system: dict = field(default_factory=dict)
    event_system: dict = field(default_factory=dict)
    narrative_rules: dict = field(default_factory=dict)
    # 声明式面板与展示数据；只作为数据保留与声明式呈现，永不执行。
    command_panels: list = field(default_factory=list)
    avatar_asset: AvatarAsset | None = None
    voice_profile: VoiceProfile | None = None
    # 未来版本新增的未知 hsr 字段原样保留。
    extras: dict = field(default_factory=dict)


@dataclass
class CharacterCard:
    """内部角色卡规范模型。

    导入 v2/v3 JSON 或 PNG 时归一化到本模型；导出生成 v3 JSON/PNG。
    每个字段只有一个权威位置：标准字段在本模型成员中，
    第三方扩展在 :attr:`extensions`，HSR 扩展在 :attr:`hsr`，
    根级未知字段在 :attr:`root_extras`。
    """

    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    creator_notes: str = ""
    system_prompt: str = ""
    post_history_instructions: str = ""
    tags: list[str] = field(default_factory=list)
    creator: str = ""
    character_version: str = ""
    alternate_greetings: list[str] = field(default_factory=list)
    group_only_greetings: list[str] = field(default_factory=list)
    character_book: CharacterBook | None = None
    # data.extensions 中除 hsr 之外的键，原样保留（含 depth_prompt、
    # talkativeness、fav、world 等 SillyTavern 惯例扩展）。
    extensions: dict = field(default_factory=dict)
    hsr: HsrExtension | None = None
    # data 中除标准字段、extensions、character_book 之外的未来字段。
    # 导入和导出时原样保留，避免新版本角色卡经过本应用后丢字段。
    data_extras: dict = field(default_factory=dict)
    # 根级未知字段（creatorcomment、avatar、create_date 等），导出时写回根。
    root_extras: dict = field(default_factory=dict)
    # 导入时识别到的规范标记；导出 v3 时统一写 chara_card_v3 / 3.0。
    spec: str = ""
    spec_version: str = ""

    @property
    def depth_prompt(self) -> dict | None:
        """SillyTavern depth prompt（权威位置：``data.extensions.depth_prompt``）。

        以扩展数据为唯一存储位置，这里只提供类型化读取视图，
        不在标准字段中复制一份。
        """
        value = self.extensions.get("depth_prompt")
        return value if isinstance(value, dict) else None

    def greeting_count(self) -> int:
        """首句 + 备选问候总数（导入结果展示用）。"""
        return (1 if self.first_mes else 0) + len(self.alternate_greetings)
