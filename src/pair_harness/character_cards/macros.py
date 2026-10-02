# 数据宏只展开白名单 {{char}} / {{user}}，单遍替换；宏名大小写敏感、紧贴花括号，与 SillyTavern
# substituteParams 一致。其余宏 token 原样保留并记入未展开清单。

from __future__ import annotations

import re
from dataclasses import dataclass

# ``{{...}}`` token：内层不允许再含花括号。
_MACRO_RE = re.compile(r"\{\{([^{}]*)\}\}")


@dataclass(frozen=True)
class MacroExpansionResult:
    """数据宏展开结果；``unexpanded`` 是未展开的宏 token（含花括号原文，去重保序）。"""

    text: str
    unexpanded: list[str]


def expand_data_macros(
    text: str, *, char_name: str, user_name: str = "用户"
) -> MacroExpansionResult:
    """单遍展开数据宏 ``{{char}}`` / ``{{user}}``，大小写变体与带空白的形式不展开。"""
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
    """返回文本中的全部 ``{{...}}`` token（含花括号原文，去重保序）。"""
    found: list[str] = []
    seen: set[str] = set()
    for match in _MACRO_RE.finditer(text):
        token = match.group(0)
        if token not in seen:
            seen.add(token)
            found.append(token)
    return found
