# 按 Base URL 识别供应商并给出推理请求形态。DeepSeek 主机识别与推理档位语义改写自
# DeepSeek-Reasonix（MIT License，Copyright (c) 2026 Reasonix Contributors）：
# https://github.com/esengine/DeepSeek-Reasonix/tree/main-v2/internal/provider/openai
# 2026 年改写为 Python，范围缩减为 DeepSeek 与通用 OpenAI 兼容端点。

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlparse


class ProviderKind(str, Enum):
    DEEPSEEK = "deepseek"
    OPENAI_COMPATIBLE = "openai_compatible"


def _host_of(base_url: str) -> str:
    try:
        parsed = urlparse(base_url)
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def is_deepseek_host(base_url: str) -> bool:
    """api.deepseek.com 或任意 *.deepseek.com 子域 → DeepSeek。

    与 Reasonix ``matchesVendorHost`` 语义一致：裸 apex（deepseek.com 本身）
    视为配置错误，不自动接受。
    """
    host = _host_of(base_url)
    return host == "api.deepseek.com" or host.endswith(".deepseek.com")


def detect_provider(base_url: str) -> ProviderKind:
    """按 Base URL 识别后端；识别不了的一律按通用 OpenAI 兼容处理。"""
    if is_deepseek_host(base_url):
        return ProviderKind.DEEPSEEK
    return ProviderKind.OPENAI_COMPATIBLE


@dataclass(frozen=True)
class ReasoningPreset:
    """某后端的推理档位预设（参考 Reasonix ``REASONING_PROVIDERS.zh-CN.md``）。

    ``effort_levels`` 是该后端支持的深度档位。
    """

    kind: ProviderKind
    effort_levels: tuple[str, ...]

    def supports_effort(self, effort: str) -> bool:
        return effort in self.effort_levels


_DEEPSEEK_FLASH_PRESET = ReasoningPreset(
    kind=ProviderKind.DEEPSEEK,
    effort_levels=("auto", "low", "high", "max"),
)
_DEEPSEEK_PRO_PRESET = ReasoningPreset(
    kind=ProviderKind.DEEPSEEK,
    effort_levels=("auto", "high", "max"),
)
_OPENAI_COMPATIBLE_PRESET = ReasoningPreset(
    kind=ProviderKind.OPENAI_COMPATIBLE,
    effort_levels=(),
)


def _is_flash_model(model: str) -> bool:
    return "flash" in model.lower()


def load_reasoning_preset(base_url: str, model: str = "") -> ReasoningPreset:
    """加载后端推理预设。

    DeepSeek 按模型区分档位：``*-flash`` 支持 low（Reasonix 文档说明它是
    唯一支持 effort=low 的官方 DeepSeek 模型），Pro 系列 low/medium 归一化
    为 high。无法判断型号时按 Flash 处理（本项目预设模型 deepseek-v4-flash）。
    """
    if detect_provider(base_url) == ProviderKind.DEEPSEEK:
        if model and not _is_flash_model(model):
            return _DEEPSEEK_PRO_PRESET
        return _DEEPSEEK_FLASH_PRESET
    return _OPENAI_COMPATIBLE_PRESET


def normalize_effort(effort: str, preset: ReasoningPreset) -> str | None:
    """把请求档位归一化为后端支持的取值；不支持/非法输入返回 None。

    返回 None 表示不写入请求体（交给服务端默认），绝不硬塞非法值。
    Reasonix 档位语义：Flash 的 medium/xhigh → high；Pro 的 low/medium →
    high、xhigh → max。是否 Flash 以是否支持 low 档判断。
    """
    want = effort.strip().lower()
    if not want:
        return None
    if preset.supports_effort(want):
        return want
    if want == "medium" and preset.supports_effort("high"):
        return "high"
    if want == "xhigh":
        # Flash 支持 low → xhigh → high；Pro 不支持 low → xhigh → max
        if preset.supports_effort("low"):
            return "high" if preset.supports_effort("high") else None
        if preset.supports_effort("max"):
            return "max"
        return "high" if preset.supports_effort("high") else None
    if want in {"low", "medium"} and preset.supports_effort("high"):
        return "high"
    return None


def deepseek_request_extras(*, thinking: bool) -> dict[str, Any]:
    """DeepSeek 用 ``thinking.type`` 开关思考的请求字段（参考 Reasonix think.go）。"""
    return {"thinking": {"type": "enabled" if thinking else "disabled"}}
