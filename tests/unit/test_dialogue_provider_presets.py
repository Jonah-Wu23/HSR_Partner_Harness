"""B1：供应商预设与识别（离线，不触网）。

覆盖 MVP 计划 §5 B1.1 的按 Base URL 识别后端与档位归一化语义。
"""

import pytest

from pair_harness.config.providers import (
    ProviderKind,
    ReasoningPreset,
    deepseek_request_extras,
    detect_provider,
    is_deepseek_host,
    load_reasoning_preset,
    normalize_effort,
)


class TestProviderDetection:
    @pytest.mark.parametrize(
        "base_url",
        [
            "https://api.deepseek.com",
            "https://api.deepseek.com/v1",
            "https://us-east.deepseek.com",
            "https://some.sub.deepseek.com/chat/completions",
        ],
    )
    def test_deepseek_hosts_recognized(self, base_url: str) -> None:
        assert is_deepseek_host(base_url)
        assert detect_provider(base_url) == ProviderKind.DEEPSEEK

    @pytest.mark.parametrize(
        "base_url",
        [
            "https://deepseek.com",  # 裸 apex 视为配置错误，不识别
            "https://notdeepseek.com",
            "https://api.openai.com/v1",
            "https://example.com/v1",
            "not-a-url",
            "",
        ],
    )
    def test_other_hosts_fall_back_to_openai_compatible(self, base_url: str) -> None:
        assert not is_deepseek_host(base_url)
        assert detect_provider(base_url) == ProviderKind.OPENAI_COMPATIBLE


class TestReasoningPreset:
    def test_flash_preset_supports_low(self) -> None:
        preset = load_reasoning_preset(
            "https://api.deepseek.com", model="deepseek-v4-flash"
        )
        assert preset.effort_levels == ("auto", "low", "high", "max")
        assert preset.thinking_control is True
        assert preset.default_thinking is True

    def test_pro_preset_drops_low(self) -> None:
        preset = load_reasoning_preset(
            "https://api.deepseek.com", model="deepseek-v4-pro"
        )
        assert preset.effort_levels == ("auto", "high", "max")

    def test_openai_compatible_preset_has_no_thinking_control(self) -> None:
        preset = load_reasoning_preset("https://example.com/v1")
        assert preset == ReasoningPreset(
            kind=ProviderKind.OPENAI_COMPATIBLE,
            thinking_control=False,
            effort_levels=(),
            default_thinking=False,
        )

    def test_unknown_model_defaults_to_flash(self) -> None:
        # 本项目预设模型 deepseek-v4-flash；无法判断型号时按 Flash 处理
        preset = load_reasoning_preset("https://api.deepseek.com")
        assert "low" in preset.effort_levels


class TestEffortNormalization:
    @pytest.mark.parametrize(
        ("effort", "expected"),
        [
            ("low", "low"),
            ("high", "high"),
            ("max", "max"),
            ("auto", "auto"),
            ("medium", "high"),  # 兼容性输入归一化（Flash）
            ("xhigh", "high"),
            ("", None),
            ("bogus", None),
            ("  HIGH ", "high"),
        ],
    )
    def test_flash_normalization(self, effort: str, expected: str | None) -> None:
        preset = load_reasoning_preset(
            "https://api.deepseek.com", model="deepseek-v4-flash"
        )
        assert normalize_effort(effort, preset) == expected

    @pytest.mark.parametrize(
        ("effort", "expected"),
        [
            ("high", "high"),
            ("max", "max"),
            ("low", "high"),  # Pro 不支持 low → 归一化为 high
            ("medium", "high"),
            ("xhigh", "max"),
        ],
    )
    def test_pro_normalization(self, effort: str, expected: str | None) -> None:
        preset = load_reasoning_preset(
            "https://api.deepseek.com", model="deepseek-v4-pro"
        )
        assert normalize_effort(effort, preset) == expected

    def test_openai_compatible_normalization_returns_none(self) -> None:
        preset = load_reasoning_preset("https://example.com/v1")
        assert normalize_effort("high", preset) is None


class TestDeepSeekRequestExtras:
    def test_default_thinking_enabled_without_effort(self) -> None:
        extras = deepseek_request_extras(thinking=None, effort=None)
        assert extras == {"thinking": {"type": "enabled"}}

    def test_thinking_disabled(self) -> None:
        extras = deepseek_request_extras(thinking=False, effort=None)
        assert extras == {"thinking": {"type": "disabled"}}

    def test_effort_normalized(self) -> None:
        extras = deepseek_request_extras(thinking=True, effort="medium")
        assert extras == {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        }

    def test_invalid_effort_ignored(self) -> None:
        extras = deepseek_request_extras(thinking=True, effort="bogus")
        assert extras == {"thinking": {"type": "enabled"}}

    def test_auto_effort_not_written(self) -> None:
        # auto 是开关类取值，不写入 reasoning_effort（档位字段只写深度）
        extras = deepseek_request_extras(thinking=True, effort="auto")
        assert extras == {"thinking": {"type": "enabled"}}
