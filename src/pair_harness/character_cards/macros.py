"""数据宏展开纯模块（V0.3.7 契约 §5）。

白名单宏 ``{{char}}`` / ``{{user}}`` 在装配渲染时单遍展开；白名单之外的
宏 token（``{{time}}``/``{{date}}``/``{{setvar...}}``/``{{random:...}}``/
``{{//...}}``/未知宏）一律原样保留并进入未展开清单，供诊断与兼容报告使用。

宏名大小写敏感、必须紧贴花括号，与 SillyTavern ``substituteParams`` 一致；
替换值内若再含宏不做二次处理（单遍）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ``{{...}}`` token：内层不允许再含花括号。
_MACRO_RE = re.compile(r"\{\{([^{}]*)\}\}")


@dataclass(frozen=True)
class MacroExpansionResult:
    """数据宏展开结果。

    - ``text``：展开后的文本；
    - ``unexpanded``：出现过但未展开的宏 token（含花括号原文，去重保序）。
    """

    text: str
    unexpanded: list[str]


def expand_data_macros(
    text: str, *, char_name: str, user_name: str = "用户"
) -> MacroExpansionResult:
    """单遍展开数据宏 ``{{char}}`` / ``{{user}}``。

    白名单之外（含大小写变体、首尾空白形式与未知宏）一律原样保留并
    记录到 ``unexpanded``。输入非 str 或无宏 token 时原样返回。
    """
    if not isinstance(text, str):
        return MacroExpansionResult(text=text, unexpanded=[])
    unexpanded: list[str] = []
    seen: set[str] = set()

    def _repl(match: re.Match) -> str:
        token = match.group(0)
        name = match.group(1)
        if name == "char":
            return char_name
        if name == "user":
            return user_name
        if token not in seen:
            seen.add(token)
            unexpanded.append(token)
        return token

    return MacroExpansionResult(
        text=_MACRO_RE.sub(_repl, text),
        unexpanded=unexpanded,
    )


def find_macros(text: str) -> list[str]:
    """返回文本中的全部 ``{{...}}`` token（含花括号原文，去重保序）。

    供 codec 导入扫描复用（契约 §5.3：非白名单宏写入兼容报告）。
    """
    if not isinstance(text, str):
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _MACRO_RE.finditer(text):
        token = match.group(0)
        if token not in seen:
            seen.add(token)
            found.append(token)
    return found
