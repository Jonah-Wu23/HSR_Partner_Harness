"""主题令牌契约测试：深浅令牌一致、QSS 关键片段、气泡品牌色与偏好持久化。"""

from pair_harness.core.contracts import MessageSource
from pair_harness.ui.theme import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    bubble_style_for,
    build_app_stylesheet,
    load_theme_preference,
    save_theme_preference,
    status_color,
)

# 深浅主题都必须具备的关键键
_KEY_KEYS = {"window_bg", "accent", "radius_card", "font_family", "text_primary"}


def test_dark_and_light_tokens_have_identical_keys() -> None:
    assert set(DARK_TOKENS) == set(LIGHT_TOKENS)
    assert _KEY_KEYS <= set(DARK_TOKENS)
    assert _KEY_KEYS <= set(LIGHT_TOKENS)


def test_stylesheet_contains_button_rules_and_accent() -> None:
    dark_qss = build_app_stylesheet(DARK_TOKENS)
    assert "QPushButton" in dark_qss
    assert "#296CE1" in dark_qss
    light_qss = build_app_stylesheet(LIGHT_TOKENS)
    assert "#F4F6F9" in light_qss


def test_dark_character_bubble_keeps_brand_colors() -> None:
    style = bubble_style_for(MessageSource.CHARACTER, None, DARK_TOKENS)
    assert "#3A548C" in style


def test_light_character_bubble_uses_light_variant() -> None:
    style = bubble_style_for(MessageSource.CHARACTER, None, LIGHT_TOKENS)
    assert LIGHT_TOKENS["bubble_character_light_bg"] in style
    assert "#3A548C" not in style


def test_theme_preference_roundtrip() -> None:
    try:
        save_theme_preference("light")
        assert load_theme_preference() == "light"
        save_theme_preference("dark")
        assert load_theme_preference() == "dark"
    finally:
        # 测试结束恢复默认深色
        save_theme_preference("dark")


def test_status_color_maps_semantic_tokens() -> None:
    assert status_color("running", DARK_TOKENS) == DARK_TOKENS["accent"]
    assert status_color("succeeded", DARK_TOKENS) == DARK_TOKENS["success"]
    assert status_color("failed", DARK_TOKENS) == DARK_TOKENS["danger"]
