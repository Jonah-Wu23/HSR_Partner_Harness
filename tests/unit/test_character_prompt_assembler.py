"""角色提示词装配器测试（V0.3.5 契约 §4.2 / 角色卡数据契约 §9 装配子集）。"""

from __future__ import annotations

from pathlib import Path

from pair_harness.character_cards import (
    CharacterBook,
    CharacterCard,
    HsrExtension,
    load_card_json,
)
from pair_harness.core.character_prompt_assembler import (
    assemble_character_prompt,
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
    assert card.scenario in system_text
    assert card.system_prompt in system_text
    # 模块字符数可诊断。
    assert result.modules[0].char_count == len(card.description)


def test_baiyu_sample_first_mes_verbatim() -> None:
    """first_mes 为作者原文，不做改写。"""
    card = _load_baiyu_card()
    result = assemble_character_prompt(card)
    assert result.first_mes == card.first_mes
    assert result.first_mes.startswith("*午后的光穿过回廊的拱门")
    assert "<speak>你来啦，伙伴。" in result.first_mes


def test_hsr_content_blocks_rendered_in_order() -> None:
    """全部 HSR 内容块：中文键、嵌套 dict、list、list-of-dict 确定性渲染。"""
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
    # 块内容全文确定性渲染（键按作者原始顺序，嵌套缩进两个空格）。
    expected_world = "\n".join(
        [
            "世界基底: 翁法罗斯",
            "时代与技术:",
            "  计算载体: 权杖δ-me13",
            "  演算目标: 生命的第一因",
            "地理城市:",
            "  - 奥赫玛",
            "  - 哀丽秘榭",
            "  - 悬锋城",
        ]
    )
    assert result.modules[0].content == expected_world
    assert result.modules[0].char_count == len(expected_world)
    expected_event = "\n".join(
        [
            "开场模式:",
            "  类型: 日常",
            "  地点: 回廊",
            "条件触发器:",
            "  - 名称: 提及故乡",
            "    条件: 用户提及哀丽秘榭",
            "  - 名称: 训练",
            "    条件: 用户提出对练",
            "随机事件池:",
            "  - 树洞探险",
            "  - 广场偶遇",
        ]
    )
    assert result.modules[4].content == expected_event
    system_text = result.system_text
    assert "世界基底: 翁法罗斯" in system_text
    assert "  计算载体: 权杖δ-me13" in system_text
    assert "  - 奥赫玛" in system_text
    assert "  - 口语化" in system_text
    assert "  - 名称: 提及故乡" in system_text
    assert "    条件: 用户提及哀丽秘榭" in system_text
    assert "  - 树洞探险" in system_text
    assert "节奏: 先接住情绪，再给行动建议" in system_text
    assert "与用户关系: 并肩伙伴" in system_text
    # HSR 五个小节按规格顺序出现。
    assert system_text.index("## 世界架构") < system_text.index("## 角色架构")
    assert system_text.index("## 角色架构") < system_text.index("## 叙事规则")
    assert system_text.index("## 叙事规则") < system_text.index("## 关系系统")
    assert system_text.index("## 关系系统") < system_text.index("## 事件系统")
    # 无标准字段时不得出现标准小节。
    assert "## 角色设定" not in system_text


def test_empty_card_minimal_frame() -> None:
    """空卡（只有 name）：固定框架文本，modules 为空列表。"""
    result = assemble_character_prompt(CharacterCard(name="空白卡"))
    assert result.system_text == "你扮演 空白卡。"
    assert result.modules == []
    assert result.first_mes == ""


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
    """V0.3.7 边界锁定：character_book 与 depth_prompt 不产生模块。"""
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
