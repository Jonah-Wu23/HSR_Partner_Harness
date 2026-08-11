from __future__ import annotations

import re
from enum import Enum

from pair_harness.core.contracts import MessageKind, MessageSource


class InputMethod(str, Enum):
    VAD = "vad"
    PUSH_TO_TALK = "push_to_talk"
    TEXT = "text"


def available_input_methods(*, target: str) -> tuple[InputMethod, ...]:
    """输入矩阵：对角色说话提供 VAD；直接交给助手不提供 VAD。

    聊天模式与协作模式的"对角色说"一致，都包含 VAD、按键说话和文字；
    "直接交给助手"只提供按键说话和文字。
    """
    if target == "assistant":
        return (InputMethod.PUSH_TO_TALK, InputMethod.TEXT)
    return (InputMethod.VAD, InputMethod.PUSH_TO_TALK, InputMethod.TEXT)


def is_tts_eligible(source: MessageSource, kind: MessageKind) -> bool:
    """只有角色发言与助手自然语言进入 TTS，其余一律静音。"""
    return (source, kind) in {
        (MessageSource.CHARACTER, MessageKind.CHARACTER_SPEECH),
        (MessageSource.ASSISTANT, MessageKind.ASSISTANT_NATURAL_LANGUAGE),
    }


# 围栏代码块（``` ... ```，含语言标注）
_FENCE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
# 行内代码（`...`）
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
# 命令/路径行：Windows 路径、可执行文件路径、常见命令前缀。
# 仅对不含中文的行判定，避免误伤自然语言句子。
_COMMAND_LINE_RE = re.compile(
    r"^\s*(?:"
    r"(?:[A-Za-z]:[\\/][^\s]+)"  # Windows 路径 E:\...
    r"|(?:/(?:[\w.-]+/)*[\w.-]+\.(?:py|exe|sh|cmd|ps1|bat)\b[^\s]*)"
    r"|(?:cd |dir |ls |python |pip |npm |npx |git |codex |set |export |\.venv[\\/])"
    r")",
    re.IGNORECASE,
)
_HAS_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_EMBEDDED_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\u4e00-\u9fff，。！？；]+)"
    r"|(?:/(?:[^\u4e00-\u9fff，。！？；\n]+/)+[^\u4e00-\u9fff，。！？；\n]+)"
)


def extract_speech_segments(markdown: str) -> list[str]:
    """把助手 Markdown 输出切成适合 TTS 的自然语言段落。

    规则（§7.3）：围栏代码块与行内代码剔除；命令/路径行剔除
    （含中文的句子不判定）；按空行分段，段落内多行合并；保持顺序；
    全空输入返回空列表。
    """
    if not markdown or not markdown.strip():
        return []

    text = _FENCE_BLOCK_RE.sub("", markdown)
    text = _INLINE_CODE_RE.sub("", text)

    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        # 空行与命令/路径行都作为段落分隔：前者来自原文，后者被剔除
        if not line or (not _HAS_CJK_RE.search(line) and _COMMAND_LINE_RE.match(line)):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        line = _EMBEDDED_PATH_RE.sub("", line).strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(re.sub(r"\s+", " ", line))
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs
