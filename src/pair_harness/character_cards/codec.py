"""Character Card v2/v3 JSON 导入与 v3 JSON 导出（纯编解码）。

只做协议一致性：根级兼容字段与 ``data`` 正式字段归一化、未知合法
扩展原样保留、缺失/非法字段直接失败。不做语义猜测，不执行任何
导入内容，不把失败改写为空卡。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pair_harness.character_cards.activation import iter_runtime_trigger_declarations
from pair_harness.character_cards.macros import find_macros
from pair_harness.character_cards.models import (
    FIXED_TTS_MODEL,
    HSR_SCHEMA_VERSION,
    AvatarAsset,
    CharacterBook,
    CharacterCard,
    HsrExtension,
    VoiceProfile,
    WorldBookEntry,
)

EXPORT_SPEC = "chara_card_v3"
EXPORT_SPEC_VERSION = "3.0"

# v2/v3 规范定义的标准字段：根级兼容副本与 data 正式字段同名同义。
STANDARD_TEXT_FIELDS = (
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "creator_notes",
    "system_prompt",
    "post_history_instructions",
    "creator",
    "character_version",
)
STANDARD_LIST_FIELDS = ("tags", "alternate_greetings", "group_only_greetings")
_ROOT_STANDARD_KEYS = frozenset(STANDARD_TEXT_FIELDS) | frozenset(STANDARD_LIST_FIELDS)
_ROOT_RESERVED_KEYS = _ROOT_STANDARD_KEYS | {
    "spec",
    "spec_version",
    "data",
    "character_book",
}
_DATA_RESERVED_KEYS = _ROOT_STANDARD_KEYS | {"extensions", "character_book"}

# Character Book v3 在 v2 基础上增补的条目字段。
_ENTRY_V3_FIELDS = ("name", "case_sensitive", "priority")

# 世界书支持的 position 值（契约 §3.6，与激活引擎一致）。
_SUPPORTED_POSITIONS = frozenset({"before_char", 0, "after_char", 1, "atDepth", 4})

# 数据宏白名单（契约 §5.2）：大小写敏感、精确匹配这两个 token。
_WHITELIST_MACROS = frozenset({"{{char}}", "{{user}}"})

# 关键字 ``/pattern/flags`` 形态与可编译 flags（契约 §3.3，与激活引擎一致）。
_REGEX_FORM_RE = re.compile(r"^/(.+)/([gimsuy]*)$")
_REGEX_FLAG_MAP = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}

# 世界书条目级存而不运行字段：报告字段名 -> extensions/extras 中可能出现的键。
# camelCase 与 snake_case 双查，只按键存在判定（值 0/空串仍是明确声明）。
_WORLD_BOOK_NOT_RUN_FIELDS = (
    ("probability", {"probability"}),
    ("useProbability", {"useProbability", "use_probability"}),
    ("recursive_scanning", {"recursive_scanning", "recursiveScanning"}),
    ("group", {"group"}),
    ("groupOverride", {"groupOverride", "group_override"}),
    ("groupWeight", {"groupWeight", "group_weight"}),
    ("sticky", {"sticky"}),
    ("cooldown", {"cooldown"}),
    ("delay", {"delay"}),
    ("min_activations", {"min_activations", "minActivations"}),
    ("automationId", {"automation_id", "automationId"}),
    ("matchPersonaDescription", {"matchPersonaDescription", "match_persona_description"}),
    ("matchCharacterDescription", {"matchCharacterDescription", "match_character_description"}),
    ("matchPersonaDescriptionOnly", {
        "matchPersonaDescriptionOnly", "match_persona_description_only"}),
    ("matchCharacterDescriptionOnly", {
        "matchCharacterDescriptionOnly", "match_character_description_only"}),
    ("matchPersonaDepth", {"matchPersonaDepth", "match_persona_depth"}),
    ("matchCharacterDepth", {"matchCharacterDepth", "match_character_depth"}),
    ("matchPersonaCard", {"matchPersonaCard", "match_persona_card"}),
    ("matchCharacterCard", {"matchCharacterCard", "match_character_card"}),
    ("scanDepth", {"scanDepth", "scan_depth"}),
    ("ignoreBudget", {"ignoreBudget", "ignore_budget"}),
)


class CardImportError(ValueError):
    """角色卡导入失败（JSON 非法、缺必填字段、结构不符）。

    携带可读原因；调用方据此把卡置为 ``invalid`` 并保留原始错误。
    """


@dataclass
class CompatReport:
    """导入/导出兼容报告。

    - ``applied``：已进入内部规范模型并将在运行时装配的模块。
    - ``preserved``：未识别但合法、已原样保留的字段路径。
    - ``not_executed``：已保留但永不会作为应用代码执行的字段路径
      （政策性声明，与内容无关；本模块从不执行任何导入内容）。
    - ``normalized_from_root``：因 ``data`` 缺失而从根级兼容字段读取的字段。
    - ``warnings`` / ``errors``：软告警与致命错误（errors 非空时导入失败）。
    """

    spec: str = ""
    applied: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    not_executed: list[str] = field(default_factory=list)
    normalized_from_root: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "spec": self.spec,
            "applied": list(self.applied),
            "preserved": list(self.preserved),
            "not_executed": list(self.not_executed),
            "normalized_from_root": list(self.normalized_from_root),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class ImportResult:
    """导入结果：规范模型 + 兼容报告。"""

    card: CharacterCard
    report: CompatReport


def load_card_json(text: str) -> ImportResult:
    """解析酒馆 Character Card v2/v3 JSON 文本并归一化为内部模型。"""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CardImportError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise CardImportError(f"角色卡必须是 JSON 对象，得到 {type(payload).__name__}")
    return load_card_payload(payload)


def load_card_payload(payload: dict) -> ImportResult:
    """解析已反序列化的角色卡字典（PNG 元数据复用同一入口）。"""
    report = CompatReport()
    spec_raw = payload.get("spec")
    spec = spec_raw if isinstance(spec_raw, str) else ""
    if spec not in ("chara_card_v2", "chara_card_v3"):
        # SillyTavern 导出的 v2 卡常缺少 spec；只要存在标准结构即可导入，
        # 但必须在报告中说明，不能静默当作确认过的 v3。
        if spec:
            raise CardImportError(f"不支持的 spec: {spec!r}")
        report.warnings.append("缺少 spec 字段，按 v2 兼容结构解析")
        spec = "chara_card_v2"
    report.spec = spec
    spec_version = _take_str(payload, "spec_version")

    data = payload.get("data")
    if data is None:
        # 部分 v2 卡只有根级字段。
        data = {}
        report.warnings.append("缺少 data 块，全部字段取根级兼容副本")
    elif not isinstance(data, dict):
        raise CardImportError(f"data 必须是 JSON 对象，得到 {type(data).__name__}")

    fields: dict = {}
    for key in STANDARD_TEXT_FIELDS:
        value, from_root = _pick_text(payload, data, key)
        fields[key] = value
        if from_root:
            report.normalized_from_root.append(key)
    for key in STANDARD_LIST_FIELDS:
        value, from_root = _pick_list(payload, data, key)
        fields[key] = value
        if from_root:
            report.normalized_from_root.append(key)

    if not fields["name"]:
        raise CardImportError("缺少必填字段 name（data 与根级均无有效值）")

    book_raw = data.get("character_book", payload.get("character_book"))
    if book_raw is None:
        character_book = None
    elif isinstance(book_raw, dict):
        character_book = _load_book(book_raw)
    else:
        raise CardImportError(
            f"character_book 必须是 JSON 对象，得到 {type(book_raw).__name__}"
        )

    extensions_raw = data.get("extensions")
    if extensions_raw is None:
        extensions: dict = {}
    elif isinstance(extensions_raw, dict):
        extensions = dict(extensions_raw)
    else:
        raise CardImportError(
            f"data.extensions 必须是 JSON 对象，得到 {type(extensions_raw).__name__}"
        )
    hsr_raw = extensions.pop("hsr", None)
    if hsr_raw is not None and not isinstance(hsr_raw, dict):
        raise CardImportError(
            f"data.extensions.hsr 必须是 JSON 对象，得到 {type(hsr_raw).__name__}"
        )
    hsr = _load_hsr(hsr_raw) if isinstance(hsr_raw, dict) else None
    if hsr is not None:
        _voice = hsr.voice_profile
        _raw_voice = hsr_raw.get("voice_profile") if isinstance(hsr_raw, dict) else None
        _raw_model = (
            _raw_voice.get("target_model") if isinstance(_raw_voice, dict) else None
        )
        if _raw_model not in (None, "", FIXED_TTS_MODEL):
            report.warnings.append(
                f"导入卡 voice_profile.target_model={_raw_model!r} 与固定模型不符，"
                f"已按产品常量归一为 {FIXED_TTS_MODEL}"
            )
    report.preserved.extend(f"data.extensions.{key}" for key in extensions)

    data_extras = {k: v for k, v in data.items() if k not in _DATA_RESERVED_KEYS}
    report.preserved.extend(f"data.{key}" for key in sorted(data_extras))

    root_extras = {k: v for k, v in payload.items() if k not in _ROOT_RESERVED_KEYS}
    report.preserved.extend(sorted(root_extras))

    card = CharacterCard(
        **fields,
        character_book=character_book,
        extensions=extensions,
        hsr=hsr,
        data_extras=data_extras,
        root_extras=root_extras,
        spec=spec,
        spec_version=spec_version,
    )

    report.applied.extend(["name", "description", "personality", "scenario"])
    report.applied.extend(["first_mes", "mes_example", "system_prompt"])
    report.applied.extend(["post_history_instructions", "tags", "creator"])
    report.applied.extend(["character_version", "alternate_greetings"])
    report.applied.extend(["group_only_greetings", "creator_notes"])
    if character_book is not None:
        report.applied.append("character_book")
    if card.depth_prompt is not None:
        report.applied.append("data.extensions.depth_prompt")
    if hsr is not None:
        report.applied.append("data.extensions.hsr")
        if hsr.command_panels:
            # 政策性声明：声明式面板只作为数据保留与呈现，永不执行。
            report.not_executed.append("data.extensions.hsr.command_panels")
    # 兼容报告增补（契约 §11）：世界书存而不运行字段、非白名单宏、
    # runtime_trigger 非 turn kind，以及关键字非法正则退化的警告。
    # 只在成功路径上做静态扫描，不改变 errors 语义。
    _extend_compat_report(card, report)
    return ImportResult(card=card, report=report)


def dump_card_v3(card: CharacterCard) -> str:
    """导出酒馆兼容 Character Card v3 JSON。

    ``data`` 为正式字段权威位置；根级写标准字段兼容副本与原根级
    未知字段，保持 SillyTavern 的读写惯例。
    """
    data = _card_data_dict(card)
    root: dict = {}
    for key in _ROOT_STANDARD_KEYS:
        root[key] = data[key]
    root["spec"] = EXPORT_SPEC
    root["spec_version"] = EXPORT_SPEC_VERSION
    root.update(card.root_extras)
    root["data"] = data
    return json.dumps(root, ensure_ascii=False, indent=4)


def _card_data_dict(card: CharacterCard) -> dict:
    data: dict = dict(card.data_extras)
    data.update({key: getattr(card, key) for key in STANDARD_TEXT_FIELDS})
    data.update({key: list(getattr(card, key)) for key in STANDARD_LIST_FIELDS})
    extensions = dict(card.extensions)
    if card.hsr is not None:
        extensions["hsr"] = _hsr_to_dict(card.hsr)
    if extensions:
        data["extensions"] = extensions
    if card.character_book is not None:
        data["character_book"] = _book_to_dict(card.character_book)
    return data


# ---------------------------------------------------------------- 载入辅助


def _take_str(source: dict, key: str) -> str:
    value = source.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CardImportError(f"{key} 必须是字符串，得到 {type(value).__name__}")
    return value


def _pick_text(root: dict, data: dict, key: str) -> tuple[str, bool]:
    """按 v3 规范优先取 data，缺失时回退根级兼容副本。"""
    if key in data:
        return _take_str(data, key), False
    if key in root:
        return _take_str(root, key), True
    return "", False


def _pick_list(root: dict, data: dict, key: str) -> tuple[list, bool]:
    if key in data:
        value = data[key]
        from_root = False
    elif key in root:
        value = root[key]
        from_root = True
    else:
        return [], False
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CardImportError(f"{key} 必须是字符串数组")
    return list(value), from_root


def _load_book(raw: dict) -> CharacterBook:
    entries_raw = raw.get("entries")
    if entries_raw is None:
        entries_raw = []
    if not isinstance(entries_raw, list):
        raise CardImportError(
            f"character_book.entries 必须是数组，得到 {type(entries_raw).__name__}"
        )
    entries = [_load_entry(item) for item in entries_raw]
    known = {"entries", "name", "description", "scan_depth", "token_budget",
             "recursive_scanning", "extensions"}
    book = CharacterBook(
        entries=entries,
        name=_take_str(raw, "name"),
        description=_take_str(raw, "description"),
        scan_depth=_optional_int(raw, "scan_depth"),
        token_budget=_optional_int(raw, "token_budget"),
        recursive_scanning=_optional_bool(raw, "recursive_scanning"),
        extensions=_take_dict(raw, "extensions"),
        extras={k: v for k, v in raw.items() if k not in known},
    )
    return book


def _load_entry(raw: dict) -> WorldBookEntry:
    if not isinstance(raw, dict):
        raise CardImportError(
            f"世界书条目必须是 JSON 对象，得到 {type(raw).__name__}"
        )
    for key_field in ("keys", "secondary_keys"):
        value = raw.get(key_field, [])
        if not isinstance(value, list) or not all(isinstance(k, str) for k in value):
            raise CardImportError(f"世界书条目 {key_field} 必须是字符串数组")
    entry_id = raw.get("id")
    if entry_id is not None and not isinstance(entry_id, (int, str)):
        raise CardImportError("世界书条目 id 必须是整数或字符串")
    known = {"id", "keys", "secondary_keys", "comment", "content", "constant",
             "selective", "insertion_order", "enabled", "position", "use_regex",
             "extensions", *(_ENTRY_V3_FIELDS)}
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise CardImportError("世界书条目 enabled 必须是布尔值")
    constant = _bool_with_default(raw, "constant", False)
    selective = _bool_with_default(raw, "selective", True)
    use_regex = _bool_with_default(raw, "use_regex", True)
    insertion_order = _optional_int(raw, "insertion_order")
    return WorldBookEntry(
        keys=list(raw["keys"]) if "keys" in raw else [],
        secondary_keys=list(raw.get("secondary_keys", [])),
        content=_take_str(raw, "content"),
        enabled=enabled,
        constant=constant,
        selective=selective,
        insertion_order=100 if insertion_order is None else insertion_order,
        position=raw.get("position", "before_char"),
        use_regex=use_regex,
        comment=_take_str(raw, "comment"),
        entry_id=entry_id,
        name=_optional_str(raw, "name"),
        case_sensitive=_optional_bool(raw, "case_sensitive"),
        priority=_optional_int(raw, "priority"),
        extensions=_take_dict(raw, "extensions"),
        extras={k: v for k, v in raw.items() if k not in known},
    )


def _load_hsr(raw: dict) -> HsrExtension:
    known = {"schema_version", "world_architecture", "character_architecture",
             "relationship_system", "event_system", "narrative_rules",
             "command_panels", "avatar_asset", "voice_profile"}
    avatar_raw = raw.get("avatar_asset")
    voice_raw = raw.get("voice_profile")
    command_panels = raw.get("command_panels", [])
    if not isinstance(command_panels, list) or not all(
        isinstance(item, dict) for item in command_panels
    ):
        raise CardImportError("hsr.command_panels 必须是对象数组")
    if avatar_raw is not None and not isinstance(avatar_raw, dict):
        raise CardImportError("hsr.avatar_asset 必须是 JSON 对象")
    if voice_raw is not None and not isinstance(voice_raw, dict):
        raise CardImportError("hsr.voice_profile 必须是 JSON 对象")
    voice = _load_voice_profile(voice_raw) if isinstance(voice_raw, dict) else None
    return HsrExtension(
        schema_version=_take_str(raw, "schema_version") or HSR_SCHEMA_VERSION,
        world_architecture=_take_dict(raw, "world_architecture"),
        character_architecture=_take_dict(raw, "character_architecture"),
        relationship_system=_take_dict(raw, "relationship_system"),
        event_system=_take_dict(raw, "event_system"),
        narrative_rules=_take_dict(raw, "narrative_rules"),
        command_panels=list(command_panels),
        avatar_asset=_load_avatar_asset(avatar_raw)
        if isinstance(avatar_raw, dict) else None,
        voice_profile=voice,
        extras={k: v for k, v in raw.items() if k not in known},
    )


def _load_avatar_asset(raw: dict) -> AvatarAsset:
    known = {"asset_id", "source", "source_ref", "mime_type", "exported_in_png"}
    exported_in_png = _optional_bool(raw, "exported_in_png")
    return AvatarAsset(
        asset_id=_take_str(raw, "asset_id"),
        source=_take_str(raw, "source") or "none",
        source_ref=_take_str(raw, "source_ref"),
        mime_type=_take_str(raw, "mime_type") or "image/png",
        exported_in_png=True if exported_in_png is None else exported_in_png,
        extras={k: v for k, v in raw.items() if k not in known},
    )


def _load_voice_profile(raw: dict) -> VoiceProfile:
    known = {"state", "voice_id", "target_model", "creation_mode", "prefix",
             "reference_audio_asset", "reference_audio_url", "voice_prompt_asset",
             "last_error", "updated_at"}
    return VoiceProfile(
        state=_take_str(raw, "state") or "voice_unconfigured",
        voice_id=_take_str(raw, "voice_id"),
        # 固定模型：忽略外部卡中的任何模型名，统一产品常量。
        target_model=FIXED_TTS_MODEL,
        creation_mode=_take_str(raw, "creation_mode"),
        prefix=_take_str(raw, "prefix"),
        reference_audio_asset=_take_str(raw, "reference_audio_asset"),
        reference_audio_url=_take_str(raw, "reference_audio_url"),
        voice_prompt_asset=_take_str(raw, "voice_prompt_asset"),
        last_error=_take_str(raw, "last_error"),
        updated_at=_take_str(raw, "updated_at"),
        extras={k: v for k, v in raw.items() if k not in known},
    )


# ---------------------------------------------------------------- 导出辅助


def _hsr_to_dict(hsr: HsrExtension) -> dict:
    out: dict = {"schema_version": hsr.schema_version}
    out["world_architecture"] = hsr.world_architecture
    out["character_architecture"] = hsr.character_architecture
    out["relationship_system"] = hsr.relationship_system
    out["event_system"] = hsr.event_system
    out["narrative_rules"] = hsr.narrative_rules
    out["command_panels"] = hsr.command_panels
    if hsr.avatar_asset is not None:
        avatar = hsr.avatar_asset
        avatar_out = {
            "asset_id": avatar.asset_id,
            "source": avatar.source,
            "source_ref": avatar.source_ref,
            "mime_type": avatar.mime_type,
            "exported_in_png": avatar.exported_in_png,
        }
        avatar_out.update(avatar.extras)
        out["avatar_asset"] = avatar_out
    if hsr.voice_profile is not None:
        voice = hsr.voice_profile
        voice_out = {
            "state": voice.state,
            "voice_id": voice.voice_id,
            "target_model": voice.target_model,
            "creation_mode": voice.creation_mode,
            "prefix": voice.prefix,
            "reference_audio_asset": voice.reference_audio_asset,
            "reference_audio_url": voice.reference_audio_url,
            "voice_prompt_asset": voice.voice_prompt_asset,
            "last_error": voice.last_error,
            "updated_at": voice.updated_at,
        }
        voice_out.update(voice.extras)
        out["voice_profile"] = voice_out
    out.update(hsr.extras)
    return out


def _book_to_dict(book: CharacterBook) -> dict:
    out: dict = {"entries": [_entry_to_dict(entry) for entry in book.entries]}
    if book.name:
        out["name"] = book.name
    if book.description:
        out["description"] = book.description
    if book.scan_depth is not None:
        out["scan_depth"] = book.scan_depth
    if book.token_budget is not None:
        out["token_budget"] = book.token_budget
    if book.recursive_scanning is not None:
        out["recursive_scanning"] = book.recursive_scanning
    if book.extensions:
        out["extensions"] = book.extensions
    out.update(book.extras)
    return out


def _entry_to_dict(entry: WorldBookEntry) -> dict:
    out: dict = {}
    if entry.entry_id is not None:
        out["id"] = entry.entry_id
    out["keys"] = list(entry.keys)
    out["secondary_keys"] = list(entry.secondary_keys)
    if entry.comment:
        out["comment"] = entry.comment
    out["content"] = entry.content
    out["constant"] = entry.constant
    out["selective"] = entry.selective
    out["insertion_order"] = entry.insertion_order
    out["enabled"] = entry.enabled
    out["position"] = entry.position
    out["use_regex"] = entry.use_regex
    for v3_field in _ENTRY_V3_FIELDS:
        value = getattr(entry, v3_field)
        if value is not None:
            out[v3_field] = value
    if entry.extensions:
        out["extensions"] = entry.extensions
    out.update(entry.extras)
    return out


# ---------------------------------------------------------------- 通用小工具


def _take_dict(source: dict, key: str) -> dict:
    value = source.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CardImportError(f"{key} 必须是 JSON 对象，得到 {type(value).__name__}")
    return dict(value)


def _optional_int(source: dict, key: str) -> int | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise CardImportError(f"{key} 必须是整数，得到 {value!r}")
    return value


def _optional_bool(source: dict, key: str) -> bool | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise CardImportError(f"{key} 必须是布尔值，得到 {value!r}")
    return value


def _bool_with_default(source: dict, key: str, default: bool) -> bool:
    value = _optional_bool(source, key)
    return default if value is None else value


def _optional_str(source: dict, key: str) -> str | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CardImportError(f"{key} 必须是字符串，得到 {type(value).__name__}")
    return value


# ---------------------------------------------------------------- 兼容报告增补扫描


def _extend_compat_report(card: CharacterCard, report: CompatReport) -> None:
    """在导入成功路径上追加静态兼容扫描（契约 §11）。

    只调整 ``not_executed`` 与 ``warnings``，绝不触碰 ``errors`` 语义
    （errors 非空时仍由调用方决定导入失败）。全部基于输入数据推导，
    对同一卡重复导入结果完全一致（幂等）。
    """
    book = card.character_book
    if book is not None:
        report.not_executed.extend(_scan_world_book_not_run(book))
        for index, entry in enumerate(book.entries):
            _scan_entry_warnings(entry, index, report.warnings)
    report.not_executed.extend(_scan_card_macros(card))
    if card.hsr is not None:
        _extend_runtime_trigger_not_run(card.hsr, report)


def _scan_world_book_not_run(book: CharacterBook) -> list[str]:
    """世界书存而不运行字段（契约 §3.11），返回 ``not_executed`` 条目。"""
    items: list[str] = []
    declared: dict[str, list[int]] = {}
    for index, entry in enumerate(book.entries):
        sources = (entry.extensions, entry.extras)
        for field, keys in _WORLD_BOOK_NOT_RUN_FIELDS:
            if any(any(k in src for k in keys) for src in sources):
                declared.setdefault(field, []).append(index)
    for field, _ in _WORLD_BOOK_NOT_RUN_FIELDS:
        indices = declared.get(field)
        if not indices:
            continue
        if len(indices) == 1:
            items.append(f"character_book.entries[{indices[0]}].{field}（存而不运行）")
        else:
            items.append(
                f"character_book.entries[...].{field}（存而不运行，{len(indices)} 处）"
            )

    # content 首行 ``@@`` 开头的装饰器（@@activate / @@dont_activate 及其他）。
    decorators: dict[str, list[int]] = {}
    for index, entry in enumerate(book.entries):
        content = (entry.content or "").strip()
        if not content:
            continue
        first_line = content.splitlines()[0].strip()
        if first_line.startswith("@@") and first_line:
            decorators.setdefault(first_line, []).append(index)
    for token, indices in decorators.items():
        if len(indices) == 1:
            items.append(f"character_book.entries[{indices[0]}].{token}（存而不运行）")
        else:
            items.append(
                f"character_book.entries[...].{token}（存而不运行，{len(indices)} 处）"
            )

    # position 不属于支持集合的条目整体排除（契约 §3.6）。
    for index, entry in enumerate(book.entries):
        if entry.position not in _SUPPORTED_POSITIONS:
            items.append(
                f"character_book.entries[{index}]（存而不运行：position={entry.position}）"
            )

    # CharacterBook 级递归扫描声明同样存而不运行。
    if book.recursive_scanning is not None:
        items.append("character_book.recursive_scanning（存而不运行）")
    return items


def _scan_entry_warnings(
    entry: WorldBookEntry, index: int, warnings: list[str]
) -> None:
    """世界书条目静态可判定的警告：非法正则关键字、selectiveLogic 越界。"""
    for key in entry.keys:
        match = _REGEX_FORM_RE.match(key)
        if match:
            # `/pattern/flags` 形态：按形态自带 flags 编译。
            try:
                re.compile(match.group(1), _regex_flags(match.group(2)))
            except re.error:
                warnings.append(
                    f"character_book.entries[{index}].keyword 非法正则已退化字面匹配: {key}"
                )
        elif entry.use_regex:
            # bare key 在 use_regex=True 时按正则编译（契约 §3.3，ST 无此概念）。
            flag_chars = "" if entry.case_sensitive else "i"
            try:
                re.compile(key, _regex_flags(flag_chars))
            except re.error:
                warnings.append(
                    f"character_book.entries[{index}].keyword 非法正则已退化字面匹配: {key}"
                )
    logic = entry.extensions.get("selectiveLogic")
    if logic is not None and (
        isinstance(logic, bool)
        or not isinstance(logic, int)
        or logic not in (0, 1, 2, 3)
    ):
        warnings.append(f"character_book.entries[{index}].selectiveLogic 越界: {logic}")


def _regex_flags(flag_chars: str) -> int:
    flags = 0
    for ch in flag_chars:
        flags |= _REGEX_FLAG_MAP.get(ch, 0)
    return flags


def _scan_card_macros(card: CharacterCard) -> list[str]:
    """全卡文本字段非白名单宏扫描（契约 §5.3），返回 ``not_executed`` 条目。

    只对字符串值扫描，键名不是值不入扫描；白名单宏 ``{{char}}``/``{{user}}``
    精确匹配不报告。同一 (宏 token, 字段路径) 按实际出现次数合并计数。
    """
    counts: dict[tuple[str, str], int] = {}
    order: list[tuple[str, str]] = []
    for path, text in _iter_card_text_fields(card):
        for token in find_macros(text):
            if token in _WHITELIST_MACROS:
                continue
            key = (token, path)
            if key not in counts:
                counts[key] = 0
                order.append(key)
            counts[key] += text.count(token)
    return [
        f"macro:{token} @ {path}（未展开，{counts[(token, path)]} 处）"
        for token, path in order
    ]


def _iter_card_text_fields(card: CharacterCard):
    """按确定顺序产出 (字段路径, 文本) 对，供宏扫描复用。"""
    for name in (
        "description",
        "personality",
        "scenario",
        "first_mes",
        "mes_example",
        "system_prompt",
        "post_history_instructions",
        "creator_notes",
    ):
        yield f"data.{name}", getattr(card, name)
    for i, greeting in enumerate(card.alternate_greetings):
        yield f"data.alternate_greetings[{i}]", greeting
    for i, greeting in enumerate(card.group_only_greetings):
        yield f"data.group_only_greetings[{i}]", greeting
    if card.character_book is not None:
        for i, entry in enumerate(card.character_book.entries):
            yield f"data.character_book.entries[{i}].content", entry.content
    depth = card.depth_prompt
    if depth is not None and isinstance(depth.get("prompt"), str):
        yield "data.extensions.depth_prompt.prompt", depth["prompt"]
    if card.hsr is not None:
        for block in (
            "world_architecture",
            "character_architecture",
            "relationship_system",
            "event_system",
            "narrative_rules",
        ):
            prefix = f"data.extensions.hsr.{block}"
            for leaf_path, text in _string_leaves(getattr(card.hsr, block), prefix):
                yield leaf_path, text


def _string_leaves(node, prefix):
    """递归枚举 dict/list 中的全部字符串叶子，产出 (可读路径, 文本)。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _string_leaves(value, f"{prefix}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _string_leaves(value, f"{prefix}[{index}]")
    elif isinstance(node, str):
        yield prefix, node


def _extend_runtime_trigger_not_run(hsr: HsrExtension, report: CompatReport) -> None:
    """runtime_trigger 非 turn kind 存而不运行（契约 §6.1）。"""
    paths: dict[int, str] = {}
    _collect_runtime_trigger_paths(hsr.event_system, "", paths)
    for entry, trigger in iter_runtime_trigger_declarations(hsr.event_system):
        kind = trigger.get("kind")
        # kind 非 turn，或 kind 为 turn 却缺 turn 字段，均不会在运行时执行。
        if kind != "turn" or "turn" not in trigger:
            prefix = paths.get(id(entry), "")
            base = (
                f"hsr.event_system.runtime_trigger.kind={kind}"
                if not prefix
                else f"hsr.event_system.{prefix}.runtime_trigger.kind={kind}"
            )
            report.not_executed.append(f"{base}（存而不运行）")


def _collect_runtime_trigger_paths(node, prefix: str, out: dict) -> None:
    """为每个 runtime_trigger 声明记录其子树路径（与 iter_runtime_trigger_declarations 同规则）。"""
    if isinstance(node, dict):
        trigger = node.get("runtime_trigger")
        if isinstance(trigger, dict):
            out[id(node)] = prefix
        for key, value in node.items():
            if key == "runtime_trigger":
                continue
            child = f"{prefix}.{key}" if prefix else key
            _collect_runtime_trigger_paths(value, child, out)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _collect_runtime_trigger_paths(item, f"{prefix}[{index}]", out)
