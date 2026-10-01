from __future__ import annotations

from pathlib import Path

import pytest

from pair_harness.character_cards.codec import load_card_json
from pair_harness.character_cards.models import (
    CharacterBook,
    CharacterCard,
    HsrExtension,
    WorldBookEntry,
)
from pair_harness.core.character_prompt_assembler import (
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
    card = _load_baiyu_card()
    result = assemble_character_prompt(card)
    # 白厄 first_mes 不含任何宏 token，展开后与原文一致。
    assert result.first_mes == card.first_mes
    assert result.first_mes.startswith("*午后的光穿过回廊的拱门")
    assert "<speak>你来啦，伙伴。" in result.first_mes


def test_baiyu_base_macro_expansion() -> None:
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
    # 顶层 dict 键渲染为 `### 键名` 小节行，嵌套层按键值与列表渲染。
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
    # 顶层不是 dict 的 HSR 块没有 `### ` 头行。
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
    result = assemble_character_prompt(CharacterCard(name="空白卡"))
    assert result.system_text == "你扮演 空白卡。"
    assert result.modules == []
    assert result.first_mes == ""
    assert result.depth_injections == ()
    assert result.diagnostics["unexpanded_macros"] == []


def test_minimal_card_name_and_description() -> None:
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
    original = "  我  是 作者原文，\n换行后也有\t制表符与标点！？……「末」    "
    result = assemble_character_prompt(
        CharacterCard(name="原文卡", description=original)
    )
    assert result.modules[0].content == original
    assert original in result.system_text


def test_empty_string_fields_skipped() -> None:
    # 字段以 strip 后非空为准；保留的字段内容仍是原文。
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
    """世界书与 depth_prompt 由回合装配叠加，基座不包含它们。"""
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


def test_turn_at_depth_entry_and_depth_prompt_become_depth_injections() -> None:
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
    no_dp = assemble_turn_prompt(_turn_card(), scan_texts=[], turn_index=1)
    assert no_dp.depth_injections == ()
    empty_dp = assemble_turn_prompt(
        _turn_card(extensions={"depth_prompt": {"prompt": "", "depth": 10}}),
        scan_texts=[],
        turn_index=1,
    )
    assert empty_dp.depth_injections == ()


def test_turn_depth_prompt_entries_variant_not_run() -> None:
    # entries 数组形态（多条注入）存而不运行。
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


@pytest.mark.parametrize(
    ("turn_index", "fires"),
    [(1, True), (2, False), (0, False), (-5, False)],
)
def test_turn_event_trigger_fires_only_on_declared_turn(turn_index: int, fires: bool) -> None:
    card = _turn_card(
        hsr=HsrExtension(
            event_system={
                "任务": {"runtime_trigger": {"kind": "turn", "turn": 1}, "content": "首回合提示"}
            }
        )
    )
    result = assemble_turn_prompt(card, scan_texts=[], turn_index=turn_index)
    triggers = [m for m in result.modules if m.kind == "hsr.event_trigger"]
    if fires:
        assert [(m.title, m.content) for m in triggers] == [
            ("事件触发（第 1 回合）", "首回合提示")
        ]
    else:
        assert triggers == []


def test_turn_event_trigger_renders_dict_without_runtime_trigger() -> None:
    # 触发条目没有 content 字段时渲染去掉 runtime_trigger 后的 dict。
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


def test_turn_budget_overflow_excludes_low_priority_entry() -> None:
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
    # 溢出条目 B 不进模块；constant 条目未命中关键字也无条件注入。
    wb = next(m for m in result.modules if m.kind == "world_book.before")
    assert "甲" in wb.content
    assert "甲乙丙丁" not in wb.content
    assert "常驻" in wb.content
    # 激活层的预算诊断随装配诊断透出。
    d = result.diagnostics
    assert d["budget_total"] == 4
    assert d["budget_limit_reached"] is True
    assert d["overflow_entries"] == ["B"]
    assert d["warnings"] and "已排除" in d["warnings"][0]


def test_turn_unexpanded_macros_from_field_and_entry() -> None:
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


def test_baiyu_fixture_world_book_hit_and_miss() -> None:
    card = _load_baiyu_card()
    hit = assemble_turn_prompt(
        card, scan_texts=["翁法罗斯是世界的中心"], turn_index=1
    )
    # 命中的世界书模块插在基座五段之前，条目 0 的原文进入模块。
    assert [m.kind for m in hit.modules] == [
        "world_book.before",
        "description",
        "personality",
        "scenario",
        "system_prompt",
        "post_history_instructions",
    ]
    assert "翁法罗斯是一个与世隔绝" in hit.modules[0].content

    miss = assemble_turn_prompt(
        card, scan_texts=["完全不相关的闲聊话语"], turn_index=1
    )
    assert not any(m.kind == "world_book.before" for m in miss.modules)
    # depth_prompt 与扫描无关，两次都注入。
    for result in (hit, miss):
        assert len(result.depth_injections) == 1
        d = result.depth_injections[0]
        assert d.depth == 4
        assert d.role == "system"
        assert "你扮演3.4版本之前的白厄" in d.text