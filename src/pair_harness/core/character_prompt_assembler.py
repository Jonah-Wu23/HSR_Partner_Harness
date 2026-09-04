"""角色提示词装配器（V0.3.7 两段式装配纯模块）。

契约出处：

- 装配顺序：``docs/character-card/角色卡数据契约.md`` §9；
- V0.3.5 装配子集：``docs/plans/V0.3.5-契约冻结.md`` §4.2；
- V0.3.7 装配扩展：``docs/plans/V0.3.7-契约冻结.md`` §4（两段式装配、
  HSR 分节渲染、世界书与深度注入、确定性触发、装配诊断、数据宏展开）。

装配职责只到「定序 + 小节标题 + 结构化呈现」：标准字段按作者原文装配，
``data.extensions.hsr`` 内容块渲染为确定性的分节行文本；数据宏
（``{{char}}``/``{{user}}``）在装配时单遍展开，白名单之外的宏进入未展开
清单。不改写、不摘要、不补全、不解析作者内容，不做任何语义猜测。

- **基座装配** ``assemble_character_prompt``（静态段）：标准字段 + HSR 五块
  + 数据宏展开 + 装配诊断；世界书与 ``depth_prompt`` 不进基座。
- **回合装配** ``assemble_turn_prompt``（现算段）：基座之上叠加世界书激活
  结果、``depth_prompt`` 深度注入与确定性触发，产出完整 ``AssembledPrompt``。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from pair_harness.character_cards.activation import (
    ActivatedEntry,
    activate_world_book,
    collect_turn_triggers,
)
from pair_harness.character_cards.macros import expand_data_macros
from pair_harness.character_cards.models import CharacterBook, CharacterCard


@dataclass(frozen=True)
class DepthInjection:
    """深度注入条目（V0.3.7 契约 §4.2/§4.4）。

    - ``depth``：距对话末尾第 N 条之前插入；0 = 追加到最后；
    - ``role``：system | user | assistant；
    - ``text``：注入文本（数据宏已展开）。
    对话适配器按鸭子类型读取（``injection.depth/.role/.text``），
    不依赖本模块的 import 方向。
    """

    depth: int
    role: str
    text: str


@dataclass(frozen=True)
class AssemblyModule:
    """一个可诊断的提示词装配模块。

    - ``kind``：模块类型标识。标准字段为字段名（``description`` 等），
      HSR 内容块为 ``hsr.<块名>``，世界书为 ``world_book.before/after``，
      确定性触发为 ``hsr.event_trigger``；
    - ``source_field``：来源字段路径；
    - ``title``：装配时使用的小节标题（中文）；
    - ``content``：该模块装配后的作者原文（已做数据宏展开，不做其他改写）；
    - ``char_count``：内容字符数（诊断用）；
    - ``char_start``/``char_end``：在最终 ``system_text`` 中的字符区间
      ``[start, end)``（世界书/深度注入/触发模块装配后统一回填）；
    - ``diagnostics``：模块级诊断（世界书模块：
      matched_keys/tokens_estimate/position/insertion_order/entry_refs）。
    """

    kind: str
    source_field: str
    title: str
    content: str
    char_count: int
    char_start: int | None = None
    char_end: int | None = None
    diagnostics: dict | None = None


@dataclass(frozen=True)
class AssembledPrompt:
    """装配结果：最终 system 文本 + 可诊断模块列表 + 首句原文 + 深度注入 + 装配诊断。

    - ``depth_injections``：深度注入条目（不在 system_text 中，由对话适配器
      splice 进对话消息列表）；基座装配恒为空元组；
    - ``diagnostics``：装配级诊断（§4.6：scan_depth/scanned_message_count/
      budget_total/budget_used/overflow_entries/not_run_fields/
      unexpanded_macros/warnings/activated_count 与 depth_injections 计数）。
    """

    system_text: str
    modules: list[AssemblyModule]
    first_mes: str
    depth_injections: tuple[DepthInjection, ...] = ()
    diagnostics: dict = field(default_factory=dict)


# 标准字段装配规格：(字段名, kind, 小节标题)；元组顺序即装配顺序，对应
# 角色卡数据契约 §9 第 1、2 步与第 5 步（世界书与 depth_prompt 由回合装配处理）。
_STANDARD_SPECS = (
    ("description", "description", "角色设定"),
    ("personality", "personality", "性格"),
    ("scenario", "scenario", "场景"),
    ("system_prompt", "system_prompt", "系统提示"),
    ("post_history_instructions", "post_history_instructions", "历史后指令"),
)

# HSR 高级扩展装配规格：(块名, kind, 小节标题)；元组顺序即契约 §9 第 6、7 步
# 的拼接顺序。``card.hsr`` 为 None 或块为空 dict 时不产生模块。
_HSR_SPECS = (
    ("world_architecture", "hsr.world_architecture", "世界架构"),
    ("character_architecture", "hsr.character_architecture", "角色架构"),
    ("narrative_rules", "hsr.narrative_rules", "叙事规则"),
    ("relationship_system", "hsr.relationship_system", "关系系统"),
    ("event_system", "hsr.event_system", "事件系统"),
)

# 框架引导模板（装配框架，不是人设合成）。
_FRAME_TEMPLATE = "你扮演 {name}。"

# atDepth / depth_prompt 角色数值映射（契约 §4.2，对齐 ST extension_prompt_roles）。
_ROLE_MAP = {0: "system", 1: "user", 2: "assistant"}


def _entry_ref(entry) -> str:
    """条目的可读引用：comment 优先，其次 entry_id，最后占位。"""
    if entry.comment:
        return entry.comment
    if entry.entry_id is not None:
        return str(entry.entry_id)
    return "<无 id/comment 条目>"


def _book_index(book: CharacterBook, target) -> int:
    """book.entries 中目标条目的身份下标（书内下标，用于 source_field）。"""
    for i, entry in enumerate(book.entries):
        if entry is target:
            return i
    return book.entries.index(target)


def _collect_unexpanded(
    text: str, char_name: str, source_field: str, unexpanded_macros: list
) -> str:
    """单遍展开数据宏并聚合未展开宏进清单（同 (macro, source_field) 去重）。"""
    result = expand_data_macros(text, char_name=char_name)
    for token in result.unexpanded:
        item = {"macro": token, "source_field": source_field}
        if item not in unexpanded_macros:
            unexpanded_macros.append(item)
    return result.text


def _build_system(
    frame: str, modules: list[AssemblyModule]
) -> tuple[str, list[AssemblyModule]]:
    """把有序模块序列渲染为最终 system_text 并回填字符区间。

    - 文本最前永远有框架引导 ``你扮演 {name}。``；
    - 每个非空模块渲染为 ``## <标题>\\n<内容>`` 小节，模块间空行分隔；
    - 逐模块计算 ``[char_start, char_end)`` 字符区间（诊断用）。
    """
    if not modules:
        return frame, []
    seq = [frame] + [f"## {m.title}\n{m.content}" for m in modules]
    text = "\n\n".join(seq)
    rebuilt: list[AssemblyModule] = []
    idx = 0
    for module in modules:
        marker = f"## {module.title}\n"
        start = text.index(marker, idx)
        end = start + len(marker) + len(module.content)
        rebuilt.append(replace(module, char_start=start, char_end=end))
        idx = end
    return text, rebuilt


def assemble_character_prompt(card: CharacterCard) -> AssembledPrompt:
    """基座装配（V0.3.7 契约 §4.1 静态段，纯函数，无副作用）。

    - 标准字段 + HSR 五块按顺序装配；每个模块内容经数据宏单遍展开，
      未展开宏聚合进 ``diagnostics.unexpanded_macros``；
    - ``first_mes`` 同样展开（白名单宏）；
    - 世界书与 ``depth_prompt`` 不进基座（归回合装配，边界由测试锁定）；
    - 每个模块记录在最终 ``system_text`` 中的字符区间。
    """
    modules: list[AssemblyModule] = []
    unexpanded_macros: list = []
    for field_name, kind, title in _STANDARD_SPECS:
        value = getattr(card, field_name)
        if value.strip():
            content = _collect_unexpanded(
                value, card.name, field_name, unexpanded_macros
            )
            modules.append(
                AssemblyModule(
                    kind=kind,
                    source_field=field_name,
                    title=title,
                    content=content,
                    char_count=len(content),
                )
            )
    hsr = card.hsr
    if hsr is not None:
        for block_name, kind, title in _HSR_SPECS:
            block = getattr(hsr, block_name)
            if block:
                rendered = _render_block_text(block)
                content = _collect_unexpanded(
                    rendered,
                    card.name,
                    f"data.extensions.hsr.{block_name}",
                    unexpanded_macros,
                )
                modules.append(
                    AssemblyModule(
                        kind=kind,
                        source_field=f"data.extensions.hsr.{block_name}",
                        title=title,
                        content=content,
                        char_count=len(content),
                    )
                )
    frame = _FRAME_TEMPLATE.format(name=card.name)
    first_mes = _collect_unexpanded(
        card.first_mes, card.name, "first_mes", unexpanded_macros
    )
    system_text, modules = _build_system(frame, modules)
    return AssembledPrompt(
        system_text=system_text,
        modules=modules,
        first_mes=first_mes,
        diagnostics={"unexpanded_macros": unexpanded_macros},
    )


def assemble_turn_prompt(
    card: CharacterCard,
    scan_texts,
    *,
    turn_index: int = 0,
    context_tokens: int = 8192,
    base: "AssembledPrompt | None" = None,
) -> AssembledPrompt:
    """回合装配（V0.3.7 契约 §4.1 现算段，不缓存）。

    - ``base`` 复用参数：传入调用方缓存基座时不重算；缺省内部现算；
    - 世界书：``card.character_book`` 非 None 时 ``activate_world_book``，
      before_char/after_char 条目成为 world_book.* 模块，atDepth 条目成为
      ``DepthInjection``（不进 system_text）；
    - ``depth_prompt``：非 None 且 prompt 非空 → ``DepthInjection``；
      ``entries`` 数组变体（v2 多条注入）存而不运行；
    - 确定性触发：``collect_turn_triggers`` 命中条目 → ``hsr.event_trigger``
      模块置于 system_text 最末；
    - 装配级 ``diagnostics`` 聚合激活诊断、未展开宏与深度注入计数。
    """
    if base is None:
        base = assemble_character_prompt(card)
    modules = list(base.modules)
    unexpanded_macros = list(base.diagnostics.get("unexpanded_macros", []))
    depth_injections: list[DepthInjection] = []
    not_run_labels = set(base.diagnostics.get("not_run_fields", []))

    scan_texts = [] if scan_texts is None else list(scan_texts)

    # ---- 世界书激活（契约 §3，§4.3） ----
    activation = None
    book = card.character_book
    if book is not None:
        activation = activate_world_book(
            book, scan_texts, context_tokens=context_tokens
        )
        before_mods = _world_book_modules(
            card, book, activation.before_char, "before_char", unexpanded_macros
        )
        after_mods = _world_book_modules(
            card, book, activation.after_char, "after_char", unexpanded_macros
        )
        modules[0:0] = before_mods
        modules = _insert_after_scenario(modules, after_mods)
        for group in activation.depth_entries:
            depth_injections.append(
                DepthInjection(
                    depth=group.depth,
                    role=group.role,
                    text=_join_entry_contents(
                        card,
                        book,
                        group.entries,
                        "data.character_book.entries",
                        unexpanded_macros,
                    ),
                )
            )

    # ---- depth_prompt 深度注入（契约 §4.4） ----
    _apply_depth_prompt(card, depth_injections, unexpanded_macros, not_run_labels)

    # ---- 确定性触发（契约 §6.1，模块置于最末） ----
    hsr = card.hsr
    event_system = hsr.event_system if hsr is not None else {}
    effective_turn = turn_index if turn_index > 0 else 0
    trigger_texts = _collect_trigger_texts(
        card, event_system, effective_turn, unexpanded_macros
    )
    if trigger_texts:
        content = "\n\n".join(trigger_texts)
        modules.append(
            AssemblyModule(
                kind="hsr.event_trigger",
                source_field="data.extensions.hsr.event_system",
                title=f"事件触发（第 {turn_index} 回合）",
                content=content,
                char_count=len(content),
            )
        )

    frame = _FRAME_TEMPLATE.format(name=card.name)
    system_text, modules = _build_system(frame, modules)

    diagnostics = _assemble_diagnostics(
        activation,
        scan_texts,
        context_tokens,
        unexpanded_macros,
        depth_injections,
        not_run_labels,
    )
    return AssembledPrompt(
        system_text=system_text,
        modules=modules,
        first_mes=base.first_mes,
        depth_injections=tuple(depth_injections),
        diagnostics=diagnostics,
    )


def _world_book_modules(
    card: CharacterCard,
    book: CharacterBook,
    activated: list[ActivatedEntry],
    position: str,
    unexpanded_macros: list,
) -> list[AssemblyModule]:
    """把一个世界书桶（before_char/after_char）装配为单个模块。

    - ``content``：桶内条目 content 宏展开后按拼接序以 ``"\n"`` 连接；
    - 模块诊断聚合 matched_keys/tokens_estimate/position/insertion_order/
      entry_refs；空桶返回空列表（不出模块，契约 §4.3）。
    """
    if not activated:
        return []
    title = (
        "世界书（角色设定前）" if position == "before_char" else "世界书（角色设定后）"
    )
    kind = "world_book.before" if position == "before_char" else "world_book.after"
    texts = []
    refs: list[str] = []
    matched: list[str] = []
    orders: list[int] = []
    tokens = 0
    for a in activated:
        refs.append(_entry_ref(a.entry))
        matched.extend(a.matched_keys)
        orders.append(a.entry.insertion_order)
        tokens += a.tokens_estimate
        idx = _book_index(book, a.entry)
        source_field = f"data.character_book.entries[{idx}]"
        texts.append(
            _collect_unexpanded(a.text, card.name, source_field, unexpanded_macros)
        )
    first_idx = _book_index(book, activated[0].entry)
    return [
        AssemblyModule(
            kind=kind,
            source_field=f"data.character_book.entries[{first_idx}]",
            title=title,
            content="\n".join(texts),
            char_count=sum(len(t) for t in texts),
            diagnostics={
                "matched_keys": matched,
                "tokens_estimate": tokens,
                "position": position,
                "insertion_order": orders,
                "entry_refs": refs,
            },
        )
    ]


def _join_entry_contents(
    card: CharacterCard,
    book: CharacterBook,
    entries: list[ActivatedEntry],
    source_prefix: str,
    unexpanded_macros: list,
) -> str:
    """桶内条目 content 宏展开后按拼接序以 "\n" 连接（供深度分组使用）。"""
    texts = []
    for a in entries:
        idx = _book_index(book, a.entry)
        source_field = f"{source_prefix}[{idx}]"
        texts.append(
            _collect_unexpanded(a.text, card.name, source_field, unexpanded_macros)
        )
    return "\n".join(texts)


def _insert_after_scenario(
    modules: list[AssemblyModule], new_mods: list[AssemblyModule]
) -> list[AssemblyModule]:
    """把 world_book.after 模块插入「场景之后、系统提示之前」（契约 §4.3）。

    ``new_mods`` 为空时原样返回；插入点按 kind 定位：场景后，其次系统提示前，
    否则落在首个 HSR 块之前（模块列表最前部）。
    """
    if not new_mods:
        return modules
    kinds = [m.kind for m in modules]
    if "scenario" in kinds:
        idx = kinds.index("scenario")
        modules[idx + 1 : idx + 1] = new_mods
    elif "system_prompt" in kinds:
        idx = kinds.index("system_prompt")
        modules[idx:idx] = new_mods
    else:
        idx = next(
            (i for i, k in enumerate(kinds) if k.startswith("hsr.")), len(modules)
        )
        modules[idx:idx] = new_mods
    return modules


def _normalize_depth_role(role) -> str:
    """depth_prompt role 归一化：字符串三值、数值 0/1/2、其余按 system。"""
    if role in ("system", "user", "assistant"):
        return role
    if isinstance(role, int) and not isinstance(role, bool) and role in (0, 1, 2):
        return _ROLE_MAP[role]
    return "system"


def _apply_depth_prompt(
    card: CharacterCard,
    depth_injections: list[DepthInjection],
    unexpanded_macros: list,
    not_run_labels: set,
) -> None:
    """depth_prompt 深度注入（契约 §4.4）。

    - ``extensions.depth_prompt`` 为 dict 且 prompt 非空 → 生成 DepthInjection
      （depth 缺省 4、role 缺省 system，数值 role 0/1/2 → system/user/assistant）；
    - dict 含 ``entries`` 数组变体（v2 多条注入）→ 存而不运行，
      记入 ``diagnostics.not_run_fields``。
    """
    dp = card.depth_prompt
    if dp is None:
        return
    if isinstance(dp.get("entries"), list):
        not_run_labels.add("depth_prompt.entries（存而不运行）")
        return
    prompt = dp.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return
    depth = dp.get("depth", 4)
    if not isinstance(depth, int) or isinstance(depth, bool):
        depth = 4
    role = _normalize_depth_role(dp.get("role", "system"))
    text = _collect_unexpanded(
        prompt, card.name, "data.extensions.depth_prompt.prompt", unexpanded_macros
    )
    depth_injections.append(DepthInjection(depth=depth, role=role, text=text))


def _collect_trigger_texts(
    card: CharacterCard,
    event_system: dict,
    turn_index: int,
    unexpanded_macros: list,
) -> list[str]:
    """确定性触发条目内容（契约 §6.1）。

    ``collect_turn_triggers`` 命中的条目：含字符串 ``content`` 字段取之，
    否则渲染剔除 ``runtime_trigger`` 后的整个 dict（``_block_lines`` 嵌套
    规则）；内容经数据宏展开。未命中返回空列表（不出模块）。
    """
    hits = collect_turn_triggers(event_system, turn_index)
    texts: list[str] = []
    for entry in hits:
        raw = entry.get("content")
        if not (isinstance(raw, str) and raw):
            filtered = {k: v for k, v in entry.items() if k != "runtime_trigger"}
            raw = _render_nested_block(filtered)
        texts.append(
            _collect_unexpanded(
                raw,
                card.name,
                "data.extensions.hsr.event_system",
                unexpanded_macros,
            )
        )
    return texts


def _assemble_diagnostics(
    activation,
    scan_texts: list,
    context_tokens: int,
    unexpanded_macros: list,
    depth_injections: list[DepthInjection],
    not_run_labels: set,
) -> dict:
    """装配级诊断（契约 §4.6）：激活诊断 + 未展开宏 + 深度注入计数。

    无世界书时提供确定性事实默认（契约 §3.1 空结果形状），字段齐备。
    """
    if activation is not None:
        ad = activation.diagnostics
        diagnostics = {
            "scan_depth": ad.scan_depth,
            "scanned_message_count": ad.scanned_message_count,
            "budget_total": ad.budget_total,
            "budget_used": ad.budget_used,
            "overflow_entries": list(ad.overflow_entries),
            "warnings": list(ad.warnings),
            "activated_count": ad.activated_count,
        }
        not_run_labels.update(ad.not_run_fields)
    else:
        diagnostics = {
            "scan_depth": 2,
            "scanned_message_count": len(scan_texts),
            "budget_total": round(0.25 * context_tokens),
            "budget_used": 0,
            "overflow_entries": [],
            "warnings": [],
            "activated_count": 0,
        }
    diagnostics["not_run_fields"] = sorted(not_run_labels)
    diagnostics["unexpanded_macros"] = unexpanded_macros
    diagnostics["depth_injections"] = len(depth_injections)
    return diagnostics


# ---------------------------------------------------------------- 结构块渲染


def _render_block_text(value: object) -> str:
    """把结构块渲染为确定性分节行文本（V0.3.7 契约 §4.7）。

    - 顶层为 dict：每个键升级为 ``### {键名}`` 小节行，后接该键值的既有
      渲染（键序不变、不翻译、不删除任何键，只排版不改写原文）；
    - 顶层 list/标量沿用现状（嵌套层规则交 ``_block_lines``）。
    """
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            lines.append(f"### {key}")
            lines.extend(_block_lines(item, ""))
        return "\n".join(lines)
    return "\n".join(_block_lines(value, ""))


def _render_nested_block(value: object) -> str:
    """把结构值渲染为无小节头的嵌套行文本（世界书/触发 dict 用，契约 §6.1）。"""
    return "\n".join(_block_lines(value, ""))


def _block_lines(value: object, indent: str) -> list[str]:
    """递归渲染一个结构值，返回带缩进行的行文本（嵌套层规则）。"""
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{indent}{key}:")
                lines.extend(_block_lines(item, indent + "  "))
            else:
                rendered = _scalar_text(item)
                if rendered:
                    lines.append(f"{indent}{key}: {rendered}")
                else:
                    lines.append(f"{indent}{key}:")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                nested = _block_lines(item, indent + "  ")
                if nested:
                    # 条目首行内联到 ``- `` 后，其余行保持该项的续行缩进。
                    lines.append(f"{indent}- {nested[0][len(indent) + 2:]}")
                    lines.extend(nested[1:])
                else:
                    lines.append(f"{indent}-")
            elif isinstance(item, list):
                lines.append(f"{indent}-")
                lines.extend(_block_lines(item, indent + "  "))
            else:
                rendered = _scalar_text(item)
                if rendered:
                    lines.append(f"{indent}- {rendered}")
                else:
                    lines.append(f"{indent}-")
        return lines
    return [f"{indent}{_scalar_text(value)}"]


def _scalar_text(value: object) -> str:
    """标量行文本：字符串原样输出，其余类型按 Python 确定性转字符串。"""
    if isinstance(value, str):
        return value
    return str(value)