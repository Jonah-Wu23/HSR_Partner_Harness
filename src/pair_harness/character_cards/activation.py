# 世界书运行时激活，语义参照 SillyTavern world-info.js v1.18.0；下文 §x.y 指 docs/plans/V0.3.7-契约冻结.md，
# 其中 §3.9 是 ST 行号对照，§3.10-§3.11 列出与 ST 的差异。激活结果只决定条目是否注入角色侧提示词。

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterator, Sequence

from pair_harness.character_cards.models import CharacterBook, WorldBookEntry

# 位置枚举：支持值 -> 归一化桶名（契约 §3.6，ST :855-864）。
_POSITION_BUCKET = {
    "before_char": "before_char",
    0: "before_char",
    "after_char": "after_char",
    1: "after_char",
    "atDepth": "atDepth",
    4: "atDepth",
}

# atDepth 角色数值映射（ST ``extension_prompt_roles``）。
_ROLE_MAP = {0: "system", 1: "user", 2: "assistant"}
_VALID_ROLES = frozenset({"system", "user", "assistant"})

# /pattern/flags 形态；flags 限 gimsuy 子集（契约 §3.3，ST :2821-2846）。
_REGEX_FORM_RE = re.compile(r"^/(.+)/([gimsuy]*)$")
_REGEX_FLAG_MAP = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
}

# 存而不运行字段检测：标签 -> extensions/extras 中可能出现的键名。
# ST 扩展用 camelCase；本仓库模型也可能出现 snake_case 别名，两者都查。
_NOT_RUN_FIELD_KEYS = (
    ("probability", {"probability"}),
    ("useProbability", {"useProbability", "use_probability"}),
    ("recursive_scanning", {"recursive_scanning", "prevent_recursion", "exclude_recursion"}),
    ("group", {"group"}),
    ("groupOverride", {"groupOverride", "group_override"}),
    ("groupWeight", {"groupWeight", "group_weight"}),
    ("sticky", {"sticky"}),
    ("cooldown", {"cooldown"}),
    ("delay", {"delay"}),
    ("min_activations", {"min_activations", "minActivations"}),
    ("automationId", {"automation_id", "automationId"}),
    ("matchPersona*", {"match_persona_description", "matchPersonaDescription"}),
    ("matchCharacter*", {
        "match_character_description", "matchCharacterDescription",
        "match_character_personality", "matchCharacterPersonality",
        "match_character_depth_prompt", "matchCharacterDepthPrompt",
        "match_creator_notes", "matchCreatorNotes",
        "match_scenario", "matchScenario",
    }),
    ("条目级scanDepth", {"scan_depth", "scanDepth"}),
    ("ignoreBudget", {"ignore_budget", "ignoreBudget"}),
)


@dataclass(frozen=True)
class ActivatedEntry:
    """单条命中条目（契约 §3.1）。"""

    entry: WorldBookEntry
    position: str            # "before_char" | "after_char" | "atDepth"
    depth: int | None        # 仅 atDepth
    role: str                # 仅 atDepth：system | user | assistant
    text: str                # 条目 content（宏展开前原文）
    matched_keys: list[str]
    tokens_estimate: int
    not_run_fields: list[str]


@dataclass(frozen=True)
class DepthEntryGroup:
    """同 (depth, role) 聚合的 atDepth 分组（契约 §3.1、§3.6）。"""

    depth: int
    role: str
    entries: list[ActivatedEntry]  # 桶内拼接序


@dataclass(frozen=True)
class ActivationDiagnostics:
    """激活诊断（契约 §3.1、§4.6）。

    - ``budget_total``：书级限额，只约束非 constant 条目；constant 条目无条件
      注入，但文本计入累计门控。
    - ``budget_used``：门控最后接受的激活序拼接文本的 ``token_estimate``。装配器
      按桶与 depth 分别拼接，分隔符不同，因此它与装配体积可以有差；constant
      较多时它可以大于 ``budget_total``。
    - ``budget_constant_used`` / ``budget_prunable_used``：每个注入条目加入前后
      累计估算之差，分别按 constant 与非 constant 求和。后者不超过 ``budget_total``。
    - ``budget_limit_reached``：非 constant 条目触发了限额门控，其后的非 constant
      条目全部排除，``overflow_entries`` 列出这些未注入的条目。
    """

    scan_depth: int
    scanned_message_count: int
    budget_total: int
    budget_used: int
    overflow_entries: list[str]   # 被预算排除条目的 comment/entry_id
    not_run_fields: list[str]     # 存而不运行字段清单（条目级聚合）
    warnings: list[str]           # 非法正则退化、预算溢出等
    activated_count: int
    budget_constant_used: int
    budget_prunable_used: int
    budget_limit_reached: bool


@dataclass(frozen=True)
class ActivationResult:
    """世界书激活结果（契约 §3.1）。"""

    before_char: list[ActivatedEntry]
    after_char: list[ActivatedEntry]
    depth_entries: list[DepthEntryGroup]
    diagnostics: ActivationDiagnostics


def token_estimate(text: str) -> int:
    """近似 token 计数（契约 §3.8）。

    ``CJK 字符数 + ceil(非 CJK 字符数 / 4)``；CJK 判定含中日韩统一表意
    文字及扩展 A 区、假名、谚文。仅用于预算门控与诊断。
    """
    cjk = sum(1 for ch in text if _is_cjk_char(ch))
    return cjk + math.ceil((len(text) - cjk) / 4)


def _is_cjk_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3400 <= cp <= 0x4DBF   # 中日韩统一表意文字扩展 A 区
        or 0x4E00 <= cp <= 0x9FFF  # 中日韩统一表意文字
        or 0x3040 <= cp <= 0x30FF  # 平假名/片假名
        or 0x1100 <= cp <= 0x11FF  # 谚文字母（Jamo）
        or 0xAC00 <= cp <= 0xD7AF  # 谚文音节
    )


def _entry_ref(entry: WorldBookEntry) -> str:
    """条目的可读引用：comment 优先，其次 entry_id，最后占位。"""
    if entry.comment:
        return entry.comment
    if entry.entry_id is not None:
        return str(entry.entry_id)
    return "<无 id/comment 条目>"


def _regex_flags(flag_chars: str) -> int:
    flags = 0
    for ch in flag_chars:
        # g/y/u 在 Python 无对应语义或为默认，忽略。
        flags |= _REGEX_FLAG_MAP.get(ch, 0)
    return flags


def _literal_match(key: str, haystack: str, entry: WorldBookEntry) -> bool:
    if entry.case_sensitive:
        return key in haystack
    return key.lower() in haystack.lower()


def _key_matches(
    key: str, haystack: str, entry: WorldBookEntry, warnings: list[str]
) -> bool:
    """单个关键字匹配（契约 §3.3，ST :337-366 ``matchKeys``）。"""
    regex_form = _REGEX_FORM_RE.match(key)
    if regex_form:
        pattern, flags = regex_form.group(1), regex_form.group(2)
        try:
            return re.search(pattern, haystack, _regex_flags(flags)) is not None
        except re.error as exc:
            warnings.append(
                f"世界书条目 key {key!r} 正则编译失败（{exc}），已退化为字面包含匹配"
            )
            return _literal_match(key, haystack, entry)
    if entry.use_regex:
        flag_chars = "" if entry.case_sensitive else "i"
        try:
            return re.search(key, haystack, _regex_flags(flag_chars)) is not None
        except re.error as exc:
            warnings.append(
                f"世界书条目 key {key!r} 正则编译失败（{exc}），已退化为字面包含匹配"
            )
            return _literal_match(key, haystack, entry)
    return _literal_match(key, haystack, entry)


def _match_entry(
    entry: WorldBookEntry, haystack: str, warnings: list[str]
) -> list[str] | None:
    """主/次关键字判定；未命中返回 None，命中返回命中的 key 列表。

    constant 条目无条件激活（契约 §3.5），不做关键字匹配。
    """
    if entry.constant:
        return []
    if not entry.keys:
        return None
    matched_main = [k for k in entry.keys if _key_matches(k, haystack, entry, warnings)]
    if not matched_main:
        return None
    matched = list(matched_main)
    if not (entry.selective and entry.secondary_keys):
        return matched
    logic = entry.extensions.get("selectiveLogic", 0)
    if isinstance(logic, bool) or not isinstance(logic, int) or logic not in (0, 1, 2, 3):
        warnings.append(
            f"世界书条目 {_entry_ref(entry)} selectiveLogic={logic!r} 越界，按 0(AND_ANY) 处理"
        )
        logic = 0
    sec_matched = [k for k in entry.secondary_keys if _key_matches(k, haystack, entry, warnings)]
    any_hit = bool(sec_matched)
    all_hit = len(sec_matched) == len(entry.secondary_keys)
    # 四逻辑布尔表（契约 §3.4，ST :4831-4866）。
    if logic == 0:      # AND_ANY：任一次 key 命中
        ok = any_hit
    elif logic == 1:    # NOT_ALL：并非全部命中
        ok = not all_hit
    elif logic == 2:    # NOT_ANY：全部未命中
        ok = not any_hit
    else:               # AND_ALL：全部命中
        ok = all_hit
    if not ok:
        return None
    matched.extend(sec_matched)
    return matched


def entry_position(entry: WorldBookEntry) -> str | int:
    """条目的生效位置，取值顺序与 SillyTavern 导入一致。

    ST 把真实位置写在 ``extensions.position``（数值枚举：0 before_char、
    1 after_char、2/3 作者注释、4 atDepth、5/6 示例消息、7 outlet），顶层
    ``position`` 只区分 before_char/after_char；前者存在时优先。
    """
    position = entry.extensions.get("position")
    return entry.position if position is None else position


def _resolve_position(
    entry: WorldBookEntry, warnings: list[str]
) -> tuple[str, int | None, str] | None:
    """位置解析（契约 §3.6）。

    返回 ``(桶名, depth, role)``；不支持位置返回 None（存而不运行）。
    """
    bucket = _POSITION_BUCKET.get(entry_position(entry))
    if bucket is None:
        return None
    if bucket == "atDepth":
        depth = entry.extensions.get("depth")
        if depth is None:
            depth = entry.extras.get("depth")
        if depth is None:
            depth = 4
        role = _normalize_role(entry, warnings)
        return ("atDepth", depth, role)
    return (bucket, None, "")


def _normalize_role(entry: WorldBookEntry, warnings: list[str]) -> str:
    role = entry.extensions.get("role")
    if role is None:
        role = entry.extras.get("role")
    if role is None:
        return "system"
    if isinstance(role, str) and role in _VALID_ROLES:
        return role
    if isinstance(role, bool) or not isinstance(role, int):
        warnings.append(f"世界书条目 {_entry_ref(entry)} role={role!r} 非法，按 system 处理")
        return "system"
    mapped = _ROLE_MAP.get(role)
    if mapped is None:
        warnings.append(f"世界书条目 {_entry_ref(entry)} role={role!r} 非法，按 system 处理")
        return "system"
    return mapped


def _entry_not_run_fields(entry: WorldBookEntry) -> list[str]:
    """条目级存而不运行字段标签（契约 §3.11）。

    从 entry.extensions 与 extras 检测，并含注释行 ``@@activate`` /
    ``@@dont_activate`` 装饰器与外链世界书 ``extensions.world``。
    """
    labels: list[str] = []
    sources = (entry.extensions, entry.extras)
    for label, keys in _NOT_RUN_FIELD_KEYS:
        if any(any(k in src for k in keys) for src in sources):
            labels.append(label)
    if "world" in entry.extensions:
        labels.append("extensions.world")
    for line in (entry.comment or "").splitlines():
        stripped = line.strip()
        if stripped == "@@activate":
            labels.append("@@activate 装饰器")
        elif stripped == "@@dont_activate":
            labels.append("@@dont_activate 装饰器")
    for src in sources:
        if "@@activate" in src:
            labels.append("@@activate 装饰器")
        if "@@dont_activate" in src:
            labels.append("@@dont_activate 装饰器")
    return labels


def _id_sort_key(entry_id: int | str | None, index: int) -> tuple:
    """同序条目按 entry_id 升序，无 entry_id 按书内下标（契约 §3.7）；int 与 str 分组比较。"""
    if entry_id is None:
        return (2, 0, index)
    if isinstance(entry_id, int):
        return (0, entry_id, index)
    return (1, entry_id, index)


def _priority_sort_key(item: tuple) -> tuple:
    """激活优先序：insertion_order 降序（契约 §3.7）。"""
    index, entry = item[0], item[1]
    return (-entry.insertion_order, _id_sort_key(entry.entry_id, index))


def _join_sort_key(item: tuple) -> tuple:
    """桶内拼接序：insertion_order 升序（契约 §3.7）。"""
    index, activated = item
    entry = activated.entry
    return (entry.insertion_order, _id_sort_key(entry.entry_id, index))


def _append_budget_warnings(
    warnings: list[str],
    *,
    budget_total: int,
    budget_used: int,
    budget_constant_used: int,
    budget_prunable_used: int,
    overflow_entries: Sequence[str],
) -> None:
    """有条目被预算排除，或 constant 条目使累计估算超出限额时告警。"""
    if budget_used <= budget_total and not overflow_entries:
        return
    if overflow_entries:
        warnings.append(
            f"世界书预算已排除 {len(overflow_entries)} 条未注入条目（其后非 constant "
            f"条目一并排除）；激活序累计估算 {budget_used}（非装配体积），其中 constant 边际 "
            f"{budget_constant_used}、受门控条目边际 {budget_prunable_used}"
        )
    else:
        warnings.append(
            f"激活序累计估算 {budget_used}（非装配体积）超出限额 {budget_total}（constant 边际 "
            f"{budget_constant_used} + 受门控条目边际 {budget_prunable_used}）；"
            "constant 条目免于裁剪但计入累计门控（契约 §3.5、§3.8），超出量来自该部分"
        )


def activate_world_book(
    book: CharacterBook,
    scan_texts: Sequence[str],
    *,
    context_tokens: int = 8192,
) -> ActivationResult:
    """世界书运行时激活（契约 §3.2-§3.8）。

    ``scan_texts`` 为时间正序的最近对话文本；生效扫描深度
    ``book.scan_depth ?? 2``，取最后 N 条以 ``"\n"`` 拼接为 haystack。
    """
    scan_depth = book.scan_depth if book.scan_depth is not None else 2
    budget_total = (
        book.token_budget
        if book.token_budget is not None
        else round(0.25 * context_tokens)
    )
    warnings: list[str] = []

    # 与 ST 一致，scan_depth 为 0 时不扫描任何消息，只有 constant 条目激活。
    haystack = "\n".join(scan_texts[-scan_depth:]) if scan_depth > 0 else ""

    # 存而不运行字段聚合：对书内全部条目静态检测（契约 §3.11）。
    aggregated_not_run: list[str] = []
    for entry in book.entries:
        for label in _entry_not_run_fields(entry):
            if label not in aggregated_not_run:
                aggregated_not_run.append(label)
        position = entry_position(entry)
        if _POSITION_BUCKET.get(position) is None:
            label = f"不支持位置({position})"
            if label not in aggregated_not_run:
                aggregated_not_run.append(label)

    # 候选筛选：enabled 跳过、constant 无条件、空 keys 跳过、关键字判定。
    candidates: list[tuple[int, WorldBookEntry, tuple, list[str]]] = []
    for index, entry in enumerate(book.entries):
        if not entry.enabled:
            continue
        position = _resolve_position(entry, warnings)
        if position is None:
            continue  # 不支持位置：已聚合进 not_run_fields，不注入
        matched = _match_entry(entry, haystack, warnings)
        if matched is None:
            continue
        candidates.append((index, entry, position, matched))

    # 激活优先序：insertion_order 降序（契约 §3.7）。
    candidates.sort(key=_priority_sort_key)

    before_bucket: list[tuple[int, ActivatedEntry]] = []
    after_bucket: list[tuple[int, ActivatedEntry]] = []
    depth_buckets: dict[tuple[int, str], list[tuple[int, ActivatedEntry]]] = {}
    overflow: list[str] = []
    cumulative_text = ""  # 门控接受的累计拼接文本（下一条候选即在其上拼接）
    accepted_cost = 0  # 该累计文本的估算（= budget_used）
    budget_constant_used = 0  # constant 条目边际之和（不受预算约束）
    budget_prunable_used = 0  # 受预算门控条目的边际之和
    over_budget = False  # 限额门控是否已触发

    for index, entry, position, matched_keys in candidates:
        # 候选文本 = 已接受文本 + "\n" + 本条正文；累计文本为空时不加分隔符。
        candidate_text = (
            cumulative_text + "\n" + entry.content if cumulative_text else entry.content
        )
        # constant 条目不受预算排除（契约 §3.5）；其余条目一旦溢出，本条及其后
        # 所有非 constant 条目整体排除（契约 §3.8，ST :4942-4953）。
        if not entry.constant:
            if over_budget:
                overflow.append(_entry_ref(entry))
                continue
            if token_estimate(candidate_text) >= budget_total:
                over_budget = True
                overflow.append(_entry_ref(entry))
                continue
        # 边际 = 并入后累计估算的增量；空正文条目也会因分隔符产生边际。
        candidate_cost = token_estimate(candidate_text)
        marginal = candidate_cost - accepted_cost
        if entry.constant:
            budget_constant_used += marginal
        else:
            budget_prunable_used += marginal
        accepted_cost = candidate_cost
        cumulative_text = candidate_text
        activated = ActivatedEntry(
            entry=entry,
            position=position[0],
            depth=position[1],
            role=position[2],
            text=entry.content,
            matched_keys=matched_keys,
            tokens_estimate=token_estimate(entry.content),
            not_run_fields=_entry_not_run_fields(entry),
        )
        if position[0] == "before_char":
            before_bucket.append((index, activated))
        elif position[0] == "after_char":
            after_bucket.append((index, activated))
        else:
            depth_buckets.setdefault((position[1], position[2]), []).append(
                (index, activated)
            )

    # 桶内拼接序：insertion_order 升序（契约 §3.7）。
    before_char = [a for _, a in sorted(before_bucket, key=_join_sort_key)]
    after_char = [a for _, a in sorted(after_bucket, key=_join_sort_key)]
    depth_entries = [
        DepthEntryGroup(
            depth=depth,
            role=role,
            entries=[a for _, a in sorted(group, key=_join_sort_key)],
        )
        for (depth, role), group in sorted(
            depth_buckets.items(), key=lambda item: (item[0][0], item[0][1])
        )
    ]

    budget_used = accepted_cost
    _append_budget_warnings(
        warnings,
        budget_total=budget_total,
        budget_used=budget_used,
        budget_constant_used=budget_constant_used,
        budget_prunable_used=budget_prunable_used,
        overflow_entries=overflow,
    )

    diagnostics = ActivationDiagnostics(
        scan_depth=scan_depth,
        scanned_message_count=len(scan_texts),
        budget_total=budget_total,
        budget_used=budget_used,
        overflow_entries=overflow,
        not_run_fields=aggregated_not_run,
        warnings=warnings,
        activated_count=(
            len(before_char)
            + len(after_char)
            + sum(len(group.entries) for group in depth_entries)
        ),
        budget_constant_used=budget_constant_used,
        budget_prunable_used=budget_prunable_used,
        budget_limit_reached=over_budget,
    )
    return ActivationResult(
        before_char=before_char,
        after_char=after_char,
        depth_entries=depth_entries,
        diagnostics=diagnostics,
    )


def iter_runtime_trigger_declarations(
    hsr_event_system: dict,
) -> Iterator[tuple[dict, dict]]:
    """递归遍历 hsr.event_system 子树（dict/list 混合），产出触发声明。

    只认「dict 含保留字段 ``runtime_trigger`` 且其值为 dict」的显式声明
    （契约 §6.1），产出 ``(条目 dict, runtime_trigger dict)`` 对。
    """
    if isinstance(hsr_event_system, dict):
        trigger = hsr_event_system.get("runtime_trigger")
        if isinstance(trigger, dict):
            yield hsr_event_system, trigger
        for key, value in hsr_event_system.items():
            if key == "runtime_trigger":
                continue
            yield from iter_runtime_trigger_declarations(value)
    elif isinstance(hsr_event_system, list):
        for item in hsr_event_system:
            yield from iter_runtime_trigger_declarations(item)


def collect_turn_triggers(hsr_event_system: dict, turn_index: int) -> list[dict]:
    """返回本轮命中的确定性触发条目 dict 列表（契约 §6.1）。

    ``{"kind": "turn", "turn": N, "once": true缺省}``：once=true 时
    ``turn_index == N`` 命中；once=false 时 ``turn_index >= N`` 命中。
    非 turn kind、turn 非正整数一律不命中（存而不运行）。
    """
    hits: list[dict] = []
    for entry, trigger in iter_runtime_trigger_declarations(hsr_event_system):
        if _trigger_matches_turn(trigger, turn_index):
            hits.append(entry)
    return hits


def _trigger_matches_turn(trigger: dict, turn_index: int) -> bool:
    if trigger.get("kind") != "turn":
        return False
    turn = trigger.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, int) or turn < 1:
        return False
    once = trigger.get("once", True)
    if not isinstance(once, bool):
        once = True  # 非布尔 once 按缺省 true 处理，只在精确回合命中
    if once:
        return turn_index == turn
    return turn_index >= turn
