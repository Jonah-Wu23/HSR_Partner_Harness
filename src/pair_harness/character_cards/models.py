# 内部角色卡模型。酒馆标准字段与 data.extensions.hsr 各有唯一权威位置，未识别的合法扩展原样保留；
# 字段类型、默认值与导入导出方式见 docs/character-card/角色卡数据契约.md。

from __future__ import annotations

from dataclasses import dataclass, field

from pair_harness.voice_models import VOICE_TTS_MODEL

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
    """``data.extensions.hsr.avatar_asset``：头像资产引用，图片字节存于受管理资产目录。"""

    asset_id: str = ""
    source: str = "none"  # none | png_import | user_upload | json_avatar_field
    source_ref: str = ""
    mime_type: str = "image/png"
    exported_in_png: bool = True
    # 未知字段原样保留。
    extras: dict = field(default_factory=dict)


@dataclass
class VoiceProfile:
    """``data.extensions.hsr.voice_profile``：角色与音色的绑定数据。

    不保存 API Key。``target_model`` 固定为产品常量，导入外部卡时不受卡内取值影响。
    """

    state: str = "voice_unconfigured"  # CharacterVoiceState 值
    voice_id: str = ""
    target_model: str = VOICE_TTS_MODEL
    creation_mode: str = ""  # clone | design | ""
    prefix: str = ""
    reference_audio_asset: str = ""
    reference_audio_url: str = ""
    voice_prompt_asset: str = ""
    last_error: str = ""
    updated_at: str = ""
    # 未知字段原样保留。
    extras: dict = field(default_factory=dict)


@dataclass
class HsrExtension:
    """``data.extensions.hsr``：酒馆标准未覆盖的 HSR 高级扩展。

    内容块（world_architecture 等）是角色作者的结构化自由内容，这里只约定
    键名与粗类型，运行时按确定顺序装配为角色提示词模块。
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
    # 未知 hsr 字段原样保留。
    extras: dict = field(default_factory=dict)


# depth_prompt.role 的数值写法（SillyTavern extension_prompt_roles）。
DEPTH_PROMPT_ROLES = {0: "system", 1: "user", 2: "assistant"}


@dataclass(frozen=True)
class DepthPrompt:
    """``data.extensions.depth_prompt`` 的单条注入；depth 缺省 4，role 缺省 system。"""

    prompt: str
    depth: int
    role: str


def parse_depth_prompt(raw: dict) -> DepthPrompt:
    """校验并解析单条 depth_prompt，字段类型或取值非法时抛 ValueError。"""
    prompt = raw.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError(
            f"depth_prompt.prompt 必须是字符串，得到 {type(prompt).__name__}"
        )
    depth = raw.get("depth", 4)
    if not isinstance(depth, int) or isinstance(depth, bool):
        raise ValueError(f"depth_prompt.depth 必须是整数，得到 {depth!r}")
    role = raw.get("role", "system")
    if isinstance(role, int) and not isinstance(role, bool):
        role = DEPTH_PROMPT_ROLES.get(role, role)
    if role not in DEPTH_PROMPT_ROLES.values():
        raise ValueError(
            "depth_prompt.role 必须是 system、user、assistant 或 0、1、2，"
            f"得到 {role!r}"
        )
    return DepthPrompt(prompt=prompt, depth=depth, role=role)


@dataclass
class CharacterCard:
    """内部角色卡规范模型。

    标准字段在本模型成员中，第三方扩展在 :attr:`extensions`，HSR 扩展在
    :attr:`hsr`，根级未知字段在 :attr:`root_extras`。
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
        """SillyTavern depth prompt 的只读视图，数据存于 ``extensions["depth_prompt"]``。"""
        value = self.extensions.get("depth_prompt")
        return value if isinstance(value, dict) else None

    def greeting_count(self) -> int:
        """首句与备选问候总数。"""
        return (1 if self.first_mes else 0) + len(self.alternate_greetings)
