import pytest

from pair_harness.config.providers import (
    ProviderKind,
    detect_provider,
    is_deepseek_host,
    load_reasoning_preset,
    normalize_effort,
)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
        "https://us-east.deepseek.com",
        "https://some.sub.deepseek.com/chat/completions",
    ],
)
def test_deepseek_hosts_recognized(base_url: str) -> None:
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
def test_other_hosts_fall_back_to_openai_compatible(base_url: str) -> None:
    assert not is_deepseek_host(base_url)
    assert detect_provider(base_url) == ProviderKind.OPENAI_COMPATIBLE


FLASH = ("https://api.deepseek.com", "deepseek-v4-flash")
PRO = ("https://api.deepseek.com", "deepseek-v4-pro")
# 无法判断型号时按 Flash 处理
UNKNOWN_DEEPSEEK_MODEL = ("https://api.deepseek.com", "")
OPENAI_COMPATIBLE = ("https://example.com/v1", "some-model")


@pytest.mark.parametrize(
    ("endpoint", "effort", "expected"),
    [
        (FLASH, "low", "low"),
        (FLASH, "high", "high"),
        (FLASH, "max", "max"),
        (FLASH, "auto", "auto"),
        (FLASH, "medium", "high"),
        (FLASH, "xhigh", "high"),
        (FLASH, "", None),
        (FLASH, "bogus", None),
        (FLASH, "  HIGH ", "high"),
        (UNKNOWN_DEEPSEEK_MODEL, "low", "low"),
        (PRO, "high", "high"),
        (PRO, "max", "max"),
        (PRO, "low", "high"),
        (PRO, "medium", "high"),
        (PRO, "xhigh", "max"),
        (OPENAI_COMPATIBLE, "high", None),
    ],
)
def test_effort_normalized_to_backend_levels(
    endpoint: tuple[str, str], effort: str, expected: str | None
) -> None:
    base_url, model = endpoint
    assert normalize_effort(effort, load_reasoning_preset(base_url, model)) == expected
