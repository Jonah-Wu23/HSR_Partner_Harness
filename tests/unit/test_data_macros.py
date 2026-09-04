"""数据宏展开纯模块测试（V0.3.7 契约 §5、§12）。"""

from __future__ import annotations

from pair_harness.character_cards import (
    MacroExpansionResult,
    expand_data_macros,
    find_macros,
)


def test_char_and_user_replaced() -> None:
    result = expand_data_macros("我是{{char}}，{{user}}你好。", char_name="白厄")
    assert result.text == "我是白厄，用户你好。"
    assert result.unexpanded == []


def test_user_name_custom() -> None:
    result = expand_data_macros("{{user}}", char_name="卡", user_name="开拓者")
    assert result.text == "开拓者"
    assert result.unexpanded == []


def test_case_sensitive_macro_name_not_expanded() -> None:
    # ST substituteParams 宏名大小写敏感：{{CHAR}}/{{Char}} 不展开并进未展开清单。
    result = expand_data_macros("{{CHAR}} {{Char}} {{char}}", char_name="白厄")
    assert result.text == "{{CHAR}} {{Char}} 白厄"
    assert result.unexpanded == ["{{CHAR}}", "{{Char}}"]


def test_whitespace_form_not_expanded() -> None:
    # 宏名必须紧贴花括号；首尾空白形式记入未展开。
    result = expand_data_macros("{{ char }}", char_name="白厄")
    assert result.text == "{{ char }}"
    assert result.unexpanded == ["{{ char }}"]


def test_non_whitelist_macros_preserved_and_listed() -> None:
    text = "{{time}} {{date}} {{setvar::a::b}} {{random:x}} {{//注释}} {{unknown}}"
    result = expand_data_macros(text, char_name="卡")
    assert result.text == text
    assert result.unexpanded == [
        "{{time}}",
        "{{date}}",
        "{{setvar::a::b}}",
        "{{random:x}}",
        "{{//注释}}",
        "{{unknown}}",
    ]


def test_unexpanded_dedup_preserve_order() -> None:
    result = expand_data_macros("{{time}} {{char}} {{time}} {{date}} {{time}}", char_name="卡")
    assert result.text == "{{time}} 卡 {{time}} {{date}} {{time}}"
    assert result.unexpanded == ["{{time}}", "{{date}}"]


def test_no_macro_returns_unchanged() -> None:
    text = "纯文本，没有宏"
    result = expand_data_macros(text, char_name="卡")
    assert result.text == text
    assert result.unexpanded == []


def test_non_string_input_returned_unchanged() -> None:
    result = expand_data_macros(None, char_name="卡")
    assert result.text is None
    assert result.unexpanded == []
    result_num = expand_data_macros(123, char_name="卡")
    assert result_num.text == 123
    assert result_num.unexpanded == []


def test_no_recursive_expansion() -> None:
    # 替换值内若再含宏不二次处理（单遍）。
    result = expand_data_macros("{{char}}说{{user}}", char_name="{{user}}")
    assert result.text == "{{user}}说用户"
    assert result.unexpanded == []


def test_result_is_frozen_dataclass() -> None:
    result = expand_data_macros("{{char}}", char_name="卡")
    assert isinstance(result, MacroExpansionResult)
    try:
        result.text = "改写"
    except Exception as exc:  # noqa: BLE001 - 冻结约束按 dataclass 语义抛出
        assert isinstance(exc, (AttributeError, ValueError))
    else:  # pragma: no cover - 冻结 dataclass 不应允许赋值
        raise AssertionError("MacroExpansionResult 应为冻结 dataclass")


def test_find_macros_dedup_preserve_order() -> None:
    assert find_macros("{{a}} {{b}} {{a}}") == ["{{a}}", "{{b}}"]
    assert find_macros("{{char}} 无 {{unknown}}") == ["{{char}}", "{{unknown}}"]
    assert find_macros("无宏文本") == []
    assert find_macros(None) == []
