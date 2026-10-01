from __future__ import annotations

import pytest

from pair_harness.character_cards.macros import expand_data_macros, find_macros

_NOT_WHITELISTED = "{{time}} {{date}} {{setvar::a::b}} {{random:x}} {{//注释}} {{unknown}}"


@pytest.mark.parametrize(
    ("text", "names", "expected_text", "expected_unexpanded"),
    [
        pytest.param(
            "我是{{char}}，{{user}}你好。", {"char_name": "白厄"},
            "我是白厄，用户你好。", [], id="char与user默认名",
        ),
        pytest.param(
            "{{user}}", {"char_name": "卡", "user_name": "开拓者"},
            "开拓者", [], id="自定义user名",
        ),
        # 与 ST substituteParams 一致，宏名大小写敏感。
        pytest.param(
            "{{CHAR}} {{Char}} {{char}}", {"char_name": "白厄"},
            "{{CHAR}} {{Char}} 白厄", ["{{CHAR}}", "{{Char}}"], id="大小写敏感",
        ),
        pytest.param(
            "{{ char }}", {"char_name": "白厄"},
            "{{ char }}", ["{{ char }}"], id="宏名带空白不展开",
        ),
        pytest.param(
            _NOT_WHITELISTED, {"char_name": "卡"},
            _NOT_WHITELISTED,
            ["{{time}}", "{{date}}", "{{setvar::a::b}}", "{{random:x}}", "{{//注释}}", "{{unknown}}"],
            id="非白名单宏原样保留",
        ),
        pytest.param(
            "{{time}} {{char}} {{time}} {{date}} {{time}}", {"char_name": "卡"},
            "{{time}} 卡 {{time}} {{date}} {{time}}", ["{{time}}", "{{date}}"],
            id="未展开清单去重保序",
        ),
        pytest.param(
            "纯文本，没有宏", {"char_name": "卡"}, "纯文本，没有宏", [], id="无宏",
        ),
        # 单遍替换：替换值里的宏不再展开。
        pytest.param(
            "{{char}}说{{user}}", {"char_name": "{{user}}"},
            "{{user}}说用户", [], id="不递归展开",
        ),
    ],
)
def test_expand_data_macros(
    text: str, names: dict, expected_text: str, expected_unexpanded: list[str]
) -> None:
    result = expand_data_macros(text, **names)
    assert result.text == expected_text
    assert result.unexpanded == expected_unexpanded


def test_find_macros_dedup_preserve_order() -> None:
    assert find_macros("{{a}} {{b}} {{a}}") == ["{{a}}", "{{b}}"]
    assert find_macros("{{char}} 无 {{unknown}}") == ["{{char}}", "{{unknown}}"]
    assert find_macros("无宏文本") == []
