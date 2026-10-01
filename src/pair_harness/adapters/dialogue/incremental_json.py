from __future__ import annotations

from pydantic_core import from_json


class IncrementalJsonSpeechParser:
    """从流式 content 分片中提取 speech 预览增量。

    以 ``{`` 开头的输出按部分 JSON 解析，只取顶层 ``speech`` 字符串值，
    转义序列解码后上屏；其他输出整段作为台词。权威台词由流结束后的
    完整解析产生，并由 character.final 覆盖预览。
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._speech = ""  # 已上屏的 speech 预览

    @property
    def speech(self) -> str:
        return self._speech

    def feed(self, chunk: str) -> str:
        """喂入一段 content 分片，返回新增的 speech 文本。"""
        self._buffer += chunk
        text = self._buffer.lstrip()
        if not text:
            return ""
        if text.startswith("{"):
            try:
                obj = from_json(text, allow_partial="trailing-strings")
            except ValueError:
                # JSON 已损坏：预览停在已上屏部分，流结束后的完整解析如实报错。
                return ""
            value = obj.get("speech") if isinstance(obj, dict) else None
            if not isinstance(value, str):
                return ""
        else:
            value = text
        # 预览只能追加；新值与已上屏部分不连续时等 character.final 覆盖。
        if not value.startswith(self._speech):
            return ""
        delta = value[len(self._speech) :]
        self._speech = value
        return delta
