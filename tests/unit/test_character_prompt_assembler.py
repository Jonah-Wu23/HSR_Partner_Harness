"""角色提示词装配器测试（V0.3.7 契约 §4、§5、§6）。

覆盖：

- 基座装配（§4.1 静态段）：标准字段 + HSR 五块分节渲染 + 数据宏展开 +
  装配诊断；世界书与 depth_prompt 不进基座（基座边界）。
- 回合装配（§4.1 现算段）：世界书激活模块、深度注入、depth_prompt、
  确定性触发、预算溢出、未展开宏、base 复用。
"""

from __future__ import annotations

from pathlib import Path

from pair_harness.character_cards import (
    CharacterBook,
    CharacterCard,
    HsrExtension,
    WorldBookEntry,
    load_card_json,
)
from pair_harness.core.character_prompt_assembler import (
    AssembledPrompt,
    DepthInjection,
    assemble_character_prompt,
    assemble_turn_prompt,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "character_cards"
    / "白厄（3.4前）.json"
)


def _load_baiyu_card() -> CharacterCard:
    return load_card_json(FIXTURE.read_text(encoding="utf-8")).card


def test_baiyu_sample_sections_and_module_order() -> None:
    """白厄样例：小节齐全、顺序正确、原文片段逐字出现。"""
    card = _load_baiyu_card()
    result = assemble_character_prompt(card)
    assert [module.kind for module in result.modules] == [
        "description",
        "personality",
        "scenario",
        "system_prompt",
        "post_history_instructions",
    ]
    assert [module.source_field for module in result.modules] == [
        "description",
        "personality",
        "scenario",
        "system_prompt",
        "post_history_instructions",
    ]
    assert [module.title for module in result.modules] == [
        "角色设定",
        "性格",
        "场景",
        "系统提示",
        "历史后指令",
    ]
    system_text = result.system_text
    assert system_text.startswith(
        "你扮演 白厄（3.4前）。\n\n## 角色设定\n白厄（Phainon）"
    )
    for heading in (
        "## 角色设定",
        "## 性格",
        "## 场景",
        "## 系统提示",
        "## 历史后指令",
    ):
        assert heading in system_text
    # 各字段作者的原文片段逐字出现。
    assert "银发蓝眸" in system_text
    assert "共情与守护" in system_text
    assert "(使用中文进行对话)" in system_text
    assert "Anti-Assistant" in system_text
    # 含内嵌换行的多行原文整段逐字保留。
    assert card.description in system_text
    assert card.system_prompt in system_text
    # scenario 含 {{char}}/{{user}}，宏展开后逐字出现展开值。
    assert result.modules[2].content == (
        card.scenario.replace("{{char}}", card.name).replace("{{user}}", "用户")
    )
    # 模块字符数可诊断。
    assert result.modules[0].char_count == len(card.description)


def test_baiyu_sample_first_mes_verbatim() -> None:
    """first_mes 为作者原文（无宏时逐字保留），不做改写。"""
    card = _load_baiyu_card()
    result = assemble_character_prompt(card)
    # 白厄 first_mes 不含任何宏 token，展开后与原文一致。
    assert result.first_mes == card.first_mes
    assert result.first_mes.startswith("*午后的光穿过回廊的拱门")
    assert "<speak>你来啦，伙伴。" in result.first_mes


def test_baiyu_base_macro_expansion() -> None:
    """白厄基座宏展开：personality 中 {{char}}/{{user}} 已被替换，
    system_text 无 {{char}} 残留，白名单宏不进未展开清单。"""
    card = _load_baiyu_card()
    result = assemble_character_prompt(card)
    personality = result.modules[1].content
    assert "{{char}}" not in personality
    assert "{{user}}" not in personality
    assert f"{card.name}的气质明亮" in personality
    assert "不愿让用户承担这份沉重" in personality
    assert "{{char}}" not in result.system_text
    assert result.diagnostics["unexpanded_macros"] == []


def test_hsr_content_blocks_rendered_in_order() -> None:
    """全部 HSR 内容块：§4.7 分节渲染（顶层 dict 键升级为 `### 键名` 小节行）、
    中文键、嵌套 dict、list、list-of-dict 确定性渲染。"""
    card = CharacterCard(
        name="测试角色",
        hsr=HsrExtension(
            world_architecture={
                "世界基底": "翁法罗斯",
                "时代与技术": {"计算载体": "权杖δ-me13", "演算目标": "生命的第一因"},
                "地理城市": ["奥赫玛", "哀丽秘榭", "悬锋城"],
            },
            character_architecture={
                "身份锚点": {"本名": "白厄", "称号": "救世主"},
                "语言指纹": ["口语化", "碎片化"],
            },
            narrative_rules={
                "节奏": "先接住情绪，再给行动建议",
                "禁区": "不主动展开深层真相",
            },
            relationship_system={"与用户关系": "并肩伙伴", "阶段门控": ["初识", "并肩"]},
            event_system={
                "开场模式": {"类型": "日常", "地点": "回廊"},
                "条件触发器": [
                    {"名称": "提及故乡", "条件": "用户提及哀丽秘榭"},
                    {"名称": "训练", "条件": "用户提出对练"},
                ],
                "随机事件池": ["树洞探险", "广场偶遇"],
            },
        ),
    )
    result = assemble_character_prompt(card)
    assert [module.kind for module in result.modules] == [
        "hsr.world_architecture",
        "hsr.character_architecture",
        "hsr.narrative_rules",
        "hsr.relationship_system",
        "hsr.event_system",
    ]
    assert [module.source_field for module in result.modules] == [
        "data.extensions.hsr.world_architecture",
        "data.extensions.hsr.character_architecture",
        "data.extensions.hsr.narrative_rules",
        "data.extensions.hsr.relationship_system",
        "data.extensions.hsr.event_system",
    ]
    assert [module.title for module in result.modules] == [
        "世界架构",
        "角色架构",
        "叙事规则",
        "关系系统",
        "事件系统",
    ]
    assert result.system_text.startswith("你扮演 测试角色。\n\n## 世界架构\n")
    # §4.7：顶层 dict 键升级为 `### 键名` 小节行，嵌套层沿用既有渲染。
    expected_world = "\n".join(
        [
            "### 世界基底",
            "翁法罗斯",
            "### 时代与技术",
            "计算载体: 权杖δ-me13",
            "演算目标: 生命的第一因",
            "### 地理城市",
            "- 奥赫玛",
            "- 哀丽秘榭",
            "- 悬锋城",
        ]
    )
    assert result.modules[0].content == expected_world
    assert result.modules[0].char_count == len(expected_world)
    expected_event = "\n".join(
        [
            "### 开场模式",
            "类型: 日常",
            "地点: 回廊",
            "### 条件触发器",
            "- 名称: 提及故乡",
            "  条件: 用户提及哀丽秘榭",
            "- 名称: 训练",
            "  条件: 用户提出对练",
            "### 随机事件池",
            "- 树洞探险",
            "- 广场偶遇",
        ]
    )
    assert result.modules[4].content == expected_event
    system_text = result.system_text
    assert "### 世界基底" in system_text
    assert "计算载体: 权杖δ-me13" in system_text
    assert "- 奥赫玛" in system_text
    assert "- 口语化" in system_text
    assert "- 名称: 提及故乡" in system_text
    assert "  条件: 用户提及哀丽秘榭" in system_text
    assert "- 树洞探险" in system_text
    assert "### 节奏" in system_text and "\n先接住情绪，再给行动建议" in system_text
    assert "### 与用户关系" in system_text and "\n并肩伙伴" in system_text
    # HSR 五个小节按规格顺序出现。
    assert system_text.index("## 世界架构") < system_text.index("## 角色架构")
    assert system_text.index("## 角色架构") < system_text.index("## 叙事规则")
    assert system_text.index("## 叙事规则") < system_text.index("## 关系系统")
    assert system_text.index("## 关系系统") < system_text.index("## 事件系统")
    # 无标准字段时不得出现标准小节。
    assert "## 角色设定" not in system_text
    # HSR 顶层标量块：非 dict 顶层沿用现状（无 `### ` 头行）。
    scalar_card = CharacterCard(
        name="标量卡",
        hsr=HsrExtension(
            narrative_rules=["规则一", "规则二"],
            relationship_system={},
        ),
    )
    scalar = assemble_character_prompt(scalar_card)
    assert scalar.modules[0].content == "- 规则一\n- 规则二"


def test_empty_card_minimal_frame() -> None:
    """空卡（只有 name）：固定框架文本，modules 为空列表。"""
    result = assemble_character_prompt(CharacterCard(name="空白卡"))
    assert result.system_text == "你扮演 空白卡。"
    assert result.modules == []
    assert result.first_mes == ""
    assert result.depth_injections == ()
    assert result.diagnostics["unexpanded_macros"] == []


def test_minimal_card_name_and_description() -> None:
    """只有 name + description 的最小卡：框架行 + 一个小节。"""
    result = assemble_character_prompt(
        CharacterCard(name="小卡", description="只有一句描述")
    )
    assert result.system_text == "你扮演 小卡。\n\n## 角色设定\n只有一句描述"
    assert len(result.modules) == 1
    module = result.modules[0]
    assert (
        module.kind,
        module.source_field,
        module.title,
        module.content,
        module.char_count,
    ) == ("description", "description", "角色设定", "只有一句描述", 6)


def test_author_text_verbatim_with_special_whitespace() -> None:
    """作者原文（含特殊空白与标点）在 system_text 中逐字出现，不被裁剪。"""
    original = "  我  是 作者原文，\n换行后也有\t制表符与标点！？……「末」    "
    result = assemble_character_prompt(
        CharacterCard(name="原文卡", description=original)
    )
    assert result.modules[0].content == original
    assert original in result.system_text


def test_empty_string_fields_skipped() -> None:
    """str 字段以 strip 后非空为准；空白字段跳过，内容仍保留原文。"""
    card = CharacterCard(
        name="跳过卡",
        description="",
        personality="   \n\t  ",
        scenario=" 场景内容  ",
        system_prompt="",
        post_history_instructions="   ",
        hsr=HsrExtension(),  # 全部内容块为空 dict，不产生 HSR 模块
    )
    result = assemble_character_prompt(card)
    assert [module.kind for module in result.modules] == ["scenario"]
    assert result.modules[0].content == " 场景内容  "


def test_character_book_and_depth_prompt_not_assembled() -> None:
    """基座边界（V0.3.7 契约 §4.1）：assemble_character_prompt 不含世界书与
    depth_prompt——它们由回合装配 assemble_turn_prompt 叠加，不进基座。"""
    card = CharacterCard(
        name="边界卡",
        description="设定",
        personality="性格",
        character_book=CharacterBook(name="世界书", entries=[]),
        extensions={
            "depth_prompt": {
                "prompt": "深层提示词",
                "depth": 4,
                "role": "system",
            }
        },
    )
    result = assemble_character_prompt(card)
    assert [module.kind for module in result.modules] == ["description", "personality"]
    assert all("book" not in module.kind for module in result.modules)
    assert "世界书" not in result.system_text
    assert "深层提示词" not in result.system_text
    # 深度注入恒空（深度注入属回合装配）。
    assert result.depth_injections == ()


# ---------------------------------------------------------------------------
# 回合装配（assemble_turn_prompt）
# ---------------------------------------------------------------------------


def _turn_card(**overrides) -> CharacterCard:
    base = dict(
        name="回合卡",
        description="角色描述",
        personality="性格",
        scenario="场景描述",
        system_prompt="系统提示",
        post_history_instructions="历史后指令",
        hsr=HsrExtension(world_architecture={"世界基底": "翁法罗斯"}),
    )
    base.update(overrides)
    return CharacterCard(**base)


def test_turn_system_text_order() -> None:
    """回合装配 system_text 顺序：框架行 → 世界书（设定前）→ 角色设定 → 性格
    → 场景 → 世界书（设定后）→ 系统提示 → 历史后指令 → HSR 五块 → 事件触发。"""
    book = CharacterBook(
        entries=[
            WorldBookEntry(
                keys=["命中词"],
                content="设定前内容",
                position="before_char",
                comment="before-1",
            ),
            WorldBookEntry(
                keys=["命中词"],
                content="设定后内容",
                position="after_char",
                comment="after-1",
            ),
        ]
    )
    card = _turn_card(
        character_book=book,
        hsr=HsrExtension(
            world_architecture={"键": "值"},
            event_system={
                "事件": {"runtime_trigger": {"kind": "turn", "turn": 3}, "content": "触发三"},
            },
        ),
    )
    result = assemble_turn_prompt(card, scan_texts=["命中词"], turn_index=3)
    kinds = [m.kind for m in result.modules]
    assert "world_book.before" in kinds
    assert "world_book.after" in kinds
    assert "hsr.event_trigger" in kinds
    t = result.system_text
    order = [
        t.index("你扮演 回合卡。"),
        t.index("## 世界书（角色设定前）"),
        t.index("## 角色设定"),
        t.index("## 性格"),
        t.index("## 场景"),
        t.index("## 世界书（角色设定后）"),
        t.index("## 系统提示"),
        t.index("## 历史后指令"),
        t.index("## 世界架构"),
        t.index("## 事件触发（第 3 回合）"),
    ]
    assert order == sorted(order)


def test_turn_at_depth_group_and_depth_prompt_not_in_system_text() -> None:
    """atDepth 条目进入 depth_injections 而非 system_text；depth_prompt 生成
    DepthInjection(depth=4)。"""
    book = CharacterBook(
        entries=[
            WorldBookEntry(
                keys=["深度词"],
                content="深度内容",
                position="atDepth",
                comment="depth-1",
                extensions={"depth": 2, "role": 1},
            ),
        ]
    )
    card = _turn_card(
        character_book=book,
        extensions={
            "depth_prompt": {"prompt": "深层提示", "depth": 4, "role": "system"}
        },
    )
    result = assemble_turn_prompt(card, scan_texts=["深度词"], turn_index=1)
    # atDepth 条目进深度注入（depth=2, role=1→user），不进 system_text。
    assert "深度内容" not in result.system_text
    # depth_prompt 生成 DepthInjection(depth=4, role=system)。
    assert DepthInjection(depth=4, role="system", text="深层提示") in result.depth_injections
    assert DepthInjection(depth=2, role="user", text="深度内容") in result.depth_injections
    assert "深层提示" not in result.system_text
    # 深度注入计数进装配诊断。
    assert result.diagnostics["depth_injections"] == 2


def test_turn_depth_prompt_missing_or_empty_no_injection() -> None:
    """depth_prompt 缺失或 prompt 为空 → 不生成深度注入。"""
    no_dp = assemble_turn_prompt(_turn_card(), scan_texts=[], turn_index=1)
    assert no_dp.depth_injections == ()
    empty_dp = assemble_turn_prompt(
        _turn_card(extensions={"depth_prompt": {"prompt": "", "depth": 10}}),
        scan_texts=[],
        turn_index=1,
    )
    assert empty_dp.depth_injections == ()


def test_turn_depth_prompt_entries_variant_not_run() -> None:
    """depth_prompt 含 entries 数组变体（v2 多条注入）→ 存而不运行，记入
    not_run_fields，不注入。"""
    card = _turn_card(
        extensions={
            "depth_prompt": {
                "entries": [
                    {"depth": 4, "role": "system", "text": "A"},
                    {"depth": 2, "role": "user", "text": "B"},
                ]
            }
        }
    )
    result = assemble_turn_prompt(card, scan_texts=[], turn_index=1)
    assert result.depth_injections == ()
    assert "depth_prompt.entries（存而不运行）" in result.diagnostics["not_run_fields"]


def test_turn_event_trigger_only_correct_turn() -> None:
    """确定性触发：runtime_trigger {"kind":"turn","turn":3}，turn_index=3 出现
    模块、2/4 不出现。"""
    card = _turn_card(
        hsr=HsrExtension(
            event_system={
                "任务": {"runtime_trigger": {"kind": "turn", "turn": 3}, "content": "第三回合提示"}
            }
        )
    )
    hit = assemble_turn_prompt(card, scan_texts=[], turn_index=3)
    assert any(m.kind == "hsr.event_trigger" for m in hit.modules)
    trigger = next(m for m in hit.modules if m.kind == "hsr.event_trigger")
    assert trigger.title == "事件触发（第 3 回合）"
    assert trigger.content == "第三回合提示"
    for idx in (2, 4):
        miss = assemble_turn_prompt(card, scan_texts=[], turn_index=idx)
        assert not any(m.kind == "hsr.event_trigger" for m in miss.modules)


def test_turn_event_trigger_renders_dict_without_runtime_trigger() -> None:
    """触发条目无 content 字段 → 渲染剔除 runtime_trigger 后的 dict。"""
    card = _turn_card(
        hsr=HsrExtension(
            event_system={
                "事件": {
                    "runtime_trigger": {"kind": "turn", "turn": 1, "once": True},
                    "标题": "独白",
                }
            }
        )
    )
    result = assemble_turn_prompt(card, scan_texts=[], turn_index=1)
    trigger = next(m for m in result.modules if m.kind == "hsr.event_trigger")
    assert "runtime_trigger" not in trigger.content
    assert "标题: 独白" in trigger.content


def test_turn_trigger_turn_index_non_positive_never_hits() -> None:
    """turn_index ≤ 0 时按 0 收集，不会命中任一正整数回合。"""
    card = _turn_card(
        hsr=HsrExtension(
            event_system={
                "回合一": {"runtime_trigger": {"kind": "turn", "turn": 1}, "content": "首回合"}
            }
        )
    )
    for idx in (0, -1, -5):
        result = assemble_turn_prompt(card, scan_texts=[], turn_index=idx)
        assert not any(m.kind == "hsr.event_trigger" for m in result.modules)


def test_turn_budget_overflow_excludes_low_priority_entry() -> None:
    """小 token_budget 下溢出条目整体排除、低优先条目不进 system_text；
    constant 条目不受预算排除。"""
    book = CharacterBook(
        token_budget=4,
        entries=[
            WorldBookEntry(
                keys=["击中"],
                content="甲",
                position="before_char",
                comment="A",
                insertion_order=100,
            ),
            WorldBookEntry(
                keys=["击中"],
                content="甲乙丙丁",
                position="before_char",
                comment="B",
                insertion_order=90,
            ),
            WorldBookEntry(
                keys=["未命中"],
                content="常驻",
                position="before_char",
                comment="C",
                constant=True,
            ),
        ],
    )
    card = _turn_card(character_book=book)
    result = assemble_turn_prompt(card, scan_texts=["击中"], turn_index=1)
    # 常驻条目 key 不受预算排除（虽未命中关键字，condition: constant 无条件激活）。
    wb = next(m for m in result.modules if m.kind == "world_book.before")
    assert "甲" in wb.content
    assert "甲乙丙丁" not in wb.content
    assert "常驻" in wb.content
    # 溢出条目 B 被记录到装配诊断。
    assert "B" in result.diagnostics["overflow_entries"]
    assert result.diagnostics["budget_total"] == 4
    assert result.diagnostics["budget_used"] > 0


def test_turn_unexpanded_macros_from_field_and_entry() -> None:
    """未展开宏清单含卡的字段与世界书条目两处来源。"""
    card = CharacterCard(
        name="宏卡",
        personality="性格{{setvar::a::1}}",
        character_book=CharacterBook(
            entries=[
                WorldBookEntry(
                    keys=["k"],
                    content="条目{{setvar::b::2}}内容",
                    position="before_char",
                    comment="宏条目",
                )
            ]
        ),
    )
    result = assemble_turn_prompt(card, scan_texts=["k"], turn_index=1)
    macros = result.diagnostics["unexpanded_macros"]
    assert {"macro": "{{setvar::a::1}}", "source_field": "personality"} in macros
    assert {
        "macro": "{{setvar::b::2}}",
        "source_field": "data.character_book.entries[0]",
    } in macros


def test_turn_base_reuse_matches_fresh_computation() -> None:
    """传入 base（缓存基座）时结果与不传（内部现算）一致，且不重复展开。"""
    book = CharacterBook(
        entries=[
            WorldBookEntry(
                keys=["命中词"],
                content="世界内容{{getvar::p}}",
                position="before_char",
                comment="before-1",
            ),
        ]
    )
    card = _turn_card(
        personality="性格{{user}}说{{char}}",
        character_book=book,
        hsr=HsrExtension(
            event_system={
                "任务": {"runtime_trigger": {"kind": "turn", "turn": 2}, "content": "触发二"}
            }
        ),
    )
    base = assemble_character_prompt(card)
    via_base = assemble_turn_prompt(
        card, scan_texts=["命中词"], turn_index=2, base=base
    )
    fresh = assemble_turn_prompt(card, scan_texts=["命中词"], turn_index=2)
    assert via_base.system_text == fresh.system_text
    assert via_base.modules == fresh.modules
    assert via_base.depth_injections == fresh.depth_injections
    assert via_base.first_mes == fresh.first_mes
    assert via_base.diagnostics == fresh.diagnostics


def test_turn_world_book_module_diagnostics() -> None:
    """世界书模块 diagnostics 聚合 matched_keys/tokens_estimate/position/
    insertion_order/entry_refs。"""
    book = CharacterBook(
        entries=[
            WorldBookEntry(
                keys=["命中文", "/另一个/"],
                content="内容A",
                position="before_char",
                comment="条目A",
                insertion_order=100,
            ),
        ]
    )
    card = _turn_card(character_book=book)
    result = assemble_turn_prompt(card, scan_texts=["命中文"], turn_index=1)
    wb = next(m for m in result.modules if m.kind == "world_book.before")
    d = wb.diagnostics
    assert "命中文" in d["matched_keys"]
    assert d["position"] == "before_char"
    assert d["insertion_order"] == [100]
    assert d["entry_refs"] == ["条目A"]
    assert d["tokens_estimate"] > 0
    assert wb.title == "世界书（角色设定前）"
    assert wb.source_field == "data.character_book.entries[0]"


def test_baiyu_real_fixture_hit_and_miss() -> None:
    """白厄真实 fixture：scan_texts 命中真实世界书关键字时才注入模块；
    未命中不产生 world_book 模块（两次调用对比）。"""
    card = _load_baiyu_card()
    hit = assemble_turn_prompt(
        card, scan_texts=["翁法罗斯是世界的中心"], turn_index=1
    )
    hit_before = [m for m in hit.modules if m.kind == "world_book.before"]
    assert len(hit_before) == 1
    # 条目 0（keys 含「翁法罗斯」）的真实 content 进入 system_text。
    assert "翁法罗斯是一个与世隔绝" in hit_before[0].content

    miss = assemble_turn_prompt(
        card, scan_texts=["完全不相关的闲聊话语"], turn_index=1
    )
    assert not any(m.kind == "world_book.before" for m in miss.modules)
    # 深度注入：白厄卡有 depth_prompt {prompt, depth:4, role:system}，
    # 恒注入一条 DepthInjection(depth=4, role=system)，与扫描无关。
    for result in (hit, miss):
        assert len(result.depth_injections) == 1
        d = result.depth_injections[0]
        assert d.depth == 4
        assert d.role == "system"
        assert "你扮演3.4版本之前的白厄" in d.text


def test_baiyu_real_fixture_turn_module_count() -> None:
    """白厄真实 fixture 回合装配：基座 5 模块 + 命中世界书 before 模块。"""
    card = _load_baiyu_card()
    result = assemble_turn_prompt(
        card, scan_texts=["回廊", "训练场"], turn_index=1
    )
    kinds = [m.kind for m in result.modules]
    # 世界书 before 插到最前，其后是基座五段。
    assert kinds[0] == "world_book.before"
    assert kinds[1:6] == [
        "description",
        "personality",
        "scenario",
        "system_prompt",
        "post_history_instructions",
    ]
    assert kinds.count("world_book.before") == 1
    assert not any(m.kind == "hsr.event_trigger" for m in result.modules)