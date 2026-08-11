"""供应商预设与推理请求形态（B1）。

按 Base URL 识别后端并应用对应请求形态。本模块的识别与档位语义参考
DeepSeek-Reasonix（MIT License，Copyright (c) 2026 Reasonix Contributors，
https://github.com/deepseek-ai/DeepSeek-Reasonix 的 internal/provider/openai/
host.go 与 effort.go），按本项目范围小范围移植为 Python 实现：
- 只识别 DeepSeek（api.deepseek.com / *.deepseek.com）与通用 OpenAI 兼容端点；
- ``thinking.type`` 控制思考开关，``reasoning_effort`` 控制思考深度；
- 兼容性输入归一化：Flash 的 medium/xhigh → high；Pro 的 low/medium → high、
  xhigh → max；未知档位返回 None（不写入请求体，交给服务端默认）。

预设只保存公开信息（host 识别规则、档位），API Key 一律经环境变量注入，
配置文件与日志永不持有密钥（B1 原则，与 MVP 计划 §5 B1.1 一致）。
"""

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
    """某后端的推理请求形态预设（参考 Reasonix ``REASONING_PROVIDERS.zh-CN.md``）。

    - ``thinking_control``：True 表示用 ``thinking.type`` 开关思考；
    - ``effort_levels``：该后端支持的深度档位（不含开关类取值）；
    - ``default_thinking``：默认是否开启思考（DeepSeek 默认开启）。
    """

    kind: ProviderKind
    thinking_control: bool
    effort_levels: tuple[str, ...]
    default_thinking: bool = True

    def supports_effort(self, effort: str) -> bool:
        return effort in self.effort_levels


_DEEPSEEK_FLASH_PRESET = ReasoningPreset(
    kind=ProviderKind.DEEPSEEK,
    thinking_control=True,
    effort_levels=("auto", "low", "high", "max"),
)
_DEEPSEEK_PRO_PRESET = ReasoningPreset(
    kind=ProviderKind.DEEPSEEK,
    thinking_control=True,
    effort_levels=("auto", "high", "max"),
)
_OPENAI_COMPATIBLE_PRESET = ReasoningPreset(
    kind=ProviderKind.OPENAI_COMPATIBLE,
    thinking_control=False,
    effort_levels=(),
    default_thinking=False,
)


def _is_flash_model(model: str) -> bool:
    return "flash" in model.lower()


def load_reasoning_preset(base_url: str, model: str = "") -> ReasoningPreset:
    """加载后端推理预设。

    DeepSeek 按模型区分档位：``*-flash`` 支持 low（Reasonix 文档——
    "the only official DeepSeek model with effort=low"），Pro 系列 low/medium
    归一化为 high。无法判断型号时按 Flash 处理（本项目预设模型
    deepseek-v4-flash）。
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


def deepseek_request_extras(
    *,
    thinking: bool | None = None,
    effort: str | None = None,
    model: str = "",
) -> dict[str, Any]:
    """DeepSeek 请求形态的扩展字段（参考 Reasonix think.go/effort.go）。

    - ``thinking``：True/False → ``{"thinking": {"type": "enabled"|"disabled"}}``；
      None 采用预设默认（开启）。
    - ``effort``：经 :func:`normalize_effort` 归一化后写入
      ``reasoning_effort``；非法档位忽略。
    """
    preset = load_reasoning_preset("https://api.deepseek.com", model=model)
    thinking_on = preset.default_thinking if thinking is None else thinking
    extras: dict[str, Any] = {}
    if preset.thinking_control:
        extras["thinking"] = {"type": "enabled" if thinking_on else "disabled"}
    if effort:
        normalized = normalize_effort(effort, preset)
        if normalized is not None and normalized != "auto":
            extras["reasoning_effort"] = normalized
    return extras
