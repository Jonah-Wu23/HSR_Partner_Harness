"""增量 JSON 解析：从 DeepSeek 流式输出中提取干净的 speech 字段（V0.2 M2）。

角色适配器的流式输出是 JSON 对象分片（``{"speech": "台词", "delegation": ...}``）。
M1 直接把原始 content 分片作为 speech.delta 上屏，气泡里会闪烁 JSON 键名与
引号残片。本模块在缓冲上推进一个轻量状态机，只提取 ``speech`` 字符串值增量
上屏；``delegation`` 等结构字段仍等流结束后的完整解析（``full_object``）。

三条通道：
- JSON 输出（以 ``{`` 开头）：增量提取 ``speech`` 字符串值，键值中途被
  SSE 分片截断时保持扫描位置，下一块继续；
- 非 JSON 输出（角色卡降级/纯台词）：整段增量作为 speech（与解析降级路径
  一致，原文即干净正文，无 JSON 包裹）；
- 流结束时 ``full_object`` 拿到完整对象，以最终值为准覆盖增量预览
  （``speech`` 属性即最终干净文本）。

注意：本解析器只负责增量预览；权威台词仍由
``OpenAICompatibleDialogueModel._parse_output`` 在流结束后对全文解析产生，
两者结论一致（同一份原始输出）。
"""

from __future__ import annotations

import json
from typing import Any

_SPEECH_KEY = '"speech"'


class IncrementalJsonSpeechParser:
    """流式 JSON 输出中的增量 speech 提取器。"""

    def __init__(self) -> None:
        self._buffer = ""
        self._speech = ""  # 完整提取的 speech（含已上屏部分）
        self._emitted = ""  # 已上屏部分
        self._full_object: dict[str, Any] | None = None
        self._seek = 0  # 键扫描起点（已确认不是键起始的位置）
        self._value_pos = -1  # 位于 speech 字符串值内部时的未扫描起点
        self._plain = False  # 已判定为非 JSON 输出，整段当台词

    @property
    def speech(self) -> str:
        return self._speech

    @property
    def full_object(self) -> dict[str, Any] | None:
        return self._full_object

    @property
    def raw(self) -> str:
        return self._buffer

    def feed(self, chunk: str) -> str:
        """喂入一段 content 分片，返回新增的干净 speech 文本。"""
        self._buffer += chunk
        if self._full_object is not None:
            # 已拿到完整对象：不再增量（final 以对象值为准）
            return ""
        stripped = self._buffer.lstrip()
        if not self._plain and stripped and not stripped.startswith("{"):
            # 非 JSON 输出（空白开头不算判定，等首个非空白字符）
            self._plain = True
        delta = self._extract()
        obj = self._try_complete()
        if obj is not None:
            self._full_object = obj
            value = str(obj.get("speech") or "").strip()
            # 增量预览与最终值一致时补齐尾部；不一致（转义字符等在预览中
            # 呈现为原始序列）时不再上屏，由 character.final 以最终值为准
            # 整体覆盖。
            delta = value[len(self._emitted) :] if value.startswith(self._emitted) else ""
            self._speech = value
            self._emitted = value
        elif delta:
            self._speech += delta
            self._emitted += delta
        return delta

    # ---- 增量提取 ----

    def _extract(self) -> str:
        if self._plain:
            return self._buffer[len(self._emitted) :]
        if self._value_pos >= 0:
            return self._scan_value()
        buf = self._buffer
        found = buf.find(_SPEECH_KEY, self._seek)
        if found == -1:
            # 键可能被截断在缓冲末尾：回退最多 len(KEY)-1 个字符重扫
            keep = max(0, len(buf) - len(_SPEECH_KEY) + 1)
            if keep < self._seek:
                self._seek = keep
            return ""
        after = found + len(_SPEECH_KEY)
        idx = self._skip_ws(buf, after)
        if idx >= len(buf):
            return ""
        if buf[idx] != ":":
            self._seek = after
            return ""
        idx = self._skip_ws(buf, idx + 1)
        if idx >= len(buf):
            return ""
        if buf[idx] != '"':
            self._seek = idx
            return ""
        self._value_pos = idx + 1
        return self._scan_value()

    def _scan_value(self) -> str:
        """扫描 speech 字符串值；只返回已确认属于值的字符。"""
        buf = self._buffer
        i = self._value_pos
        out: list[str] = []
        while i < len(buf):
            ch = buf[i]
            if ch == "\\":
                if i + 1 >= len(buf):
                    break  # 反斜杠被截断在末尾：停在原地，下一块继续
                out.append(buf[i : i + 2])
                i += 2
                continue
            if ch == '"':
                # 值闭合；继续从闭合位置之后找可能的后续 speech 键
                self._value_pos = -1
                self._seek = i + 1
                return "".join(out)
            out.append(ch)
            i += 1
        self._value_pos = i
        return "".join(out)

    @staticmethod
    def _skip_ws(buf: str, idx: int) -> int:
        while idx < len(buf) and buf[idx] in " \t\r\n":
            idx += 1
        return idx

    def _try_complete(self) -> dict[str, Any] | None:
        text = self._buffer.strip()
        if not text:
            return None
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            return None
        return obj if isinstance(obj, dict) else None
