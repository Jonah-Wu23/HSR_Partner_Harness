"""全局视觉主题契约（ui-ux-pro-max / AI-Native 风格）。

所有 UI 组件的颜色、圆角、字体一律从这里取令牌，不在组件里散落色值。
深色为默认主题；浅色为衍生变体。角色/助手气泡在深色主题下必须保留
PairTheme 品牌色（tests/ui/test_theme_and_plain_text.py 锁定）。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PyQt5.QtCore import QSettings

from pair_harness.config.pairs import PairTheme
from pair_harness.core.contracts import MessageSource

# 下拉箭头图标（QSS image url，正斜杠路径；QtSvg 渲染）
CHEVRON_DOWN_URL = (
    Path(__file__).resolve().parents[3] / "assets" / "ui" / "chevron_down.svg"
).as_posix()

# ---------------------------------------------------------------------------
# 令牌
# ---------------------------------------------------------------------------

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif'
FONT_MONO = '"Cascadia Mono", Consolas, "Courier New", monospace'

# 字号基准（缩放系数 1.0 时的像素值）；scaled_tokens 按窗口宽度放大
_BASE_FONT_SIZES = {
    "px_body": 13,    # 正文、按钮、输入框
    "px_meta": 11,    # 气泡来源标签、思考折叠等弱化信息
    "px_title": 14,   # 面板标题
    "px_sub": 12,     # 副标题、语音状态
    "px_app": 15,     # 顶栏应用名
}

# 窗口宽度 → 缩放系数：1280 及以下为 1.0，1920 约 1.3，封顶 1.5
SCALE_BASE_WIDTH = 1280
SCALE_MAX = 1.5


def scale_for_width(width: int) -> float:
    """按窗口宽度计算界面缩放系数（只放大不缩小，0.05 步进防抖动）。"""
    if width <= SCALE_BASE_WIDTH:
        return 1.0
    raw = min(SCALE_MAX, width / SCALE_BASE_WIDTH)
    return round(raw * 20) / 20


def scaled_tokens(tokens: dict[str, str], scale: float) -> dict[str, str]:
    """返回按缩放系数调整字号后的令牌副本（原字典不被修改）。"""
    scaled = dict(tokens)
    scaled["_scale"] = str(scale)
    for key, base in _BASE_FONT_SIZES.items():
        scaled[key] = f"{round(base * scale)}px"
    return scaled

DARK_TOKENS: dict[str, str] = {
    "mode": "dark",
    # 基底
    "window_bg": "#0E1116",
    "panel_bg": "#161A21",
    "card_bg": "#1C212B",
    "input_bg": "#12161D",
    "border": "#2A303C",
    "border_strong": "#3A4250",
    # 文字
    "text_primary": "#E6E9EF",
    "text_secondary": "#9AA3B2",
    "text_muted": "#6B7686",
    # 品牌主色
    "accent": "#296CE1",
    "accent_hover": "#3D7CE8",
    "accent_pressed": "#1F5BC4",
    "accent_soft": "#1B2A45",
    "gold": "#B08D57",
    # 语义色
    "success": "#22C55E",
    "warning": "#CA8A04",
    "danger": "#DC2626",
    # 中性气泡（用户/工具/系统）
    "bubble_user_bg": "#343B4D",
    "bubble_user_border": "#4A5268",
    "bubble_user_text": "#E5E7EB",
    "bubble_tool_bg": "#17191D",
    "bubble_tool_border": "#373A40",
    "bubble_tool_text": "#D1D5DB",
    "bubble_system_bg": "#24262B",
    "bubble_system_border": "#373A40",
    "bubble_system_text": "#9CA3AF",
    # 思考折叠区
    "reasoning_bg": "#13161C",
    "reasoning_border": "#2A303C",
    "reasoning_text": "#B8BDC7",
    # 浅色派生气泡占位（深色主题不使用，保持键集合一致）
    "bubble_character_light_bg": "#E4EBF7",
    "bubble_character_light_text": "#1E3A6E",
    "bubble_character_light_border": "#8AA4D4",
    "bubble_assistant_light_bg": "#F3EAD9",
    "bubble_assistant_light_text": "#5C4526",
    "bubble_assistant_light_border": "#C5A059",
    # 圆角与字体
    "radius_panel": "12px",
    "radius_bubble": "12px",
    "radius_card": "10px",
    "radius_control": "8px",
    "font_family": FONT_FAMILY,
    "font_mono": FONT_MONO,
}

LIGHT_TOKENS: dict[str, str] = {
    "mode": "light",
    "window_bg": "#F4F6F9",
    "panel_bg": "#FFFFFF",
    "card_bg": "#FFFFFF",
    "input_bg": "#FFFFFF",
    "border": "#DFE3EA",
    "border_strong": "#C7CDD6",
    "text_primary": "#1B2431",
    "text_secondary": "#52606F",
    "text_muted": "#8492A2",
    "accent": "#296CE1",
    "accent_hover": "#3D7CE8",
    "accent_pressed": "#1F5BC4",
    "accent_soft": "#E3EDFC",
    "gold": "#8C6B3F",
    "success": "#15803D",
    "warning": "#A16207",
    "danger": "#B91C1C",
    "bubble_user_bg": "#E8EDF5",
    "bubble_user_border": "#C9D3E2",
    "bubble_user_text": "#1B2431",
    "bubble_tool_bg": "#EEF1F5",
    "bubble_tool_border": "#DFE3EA",
    "bubble_tool_text": "#52606F",
    "bubble_system_bg": "#EEF1F5",
    "bubble_system_border": "#DFE3EA",
    "bubble_system_text": "#52606F",
    "reasoning_bg": "#F0F2F6",
    "reasoning_border": "#DFE3EA",
    "reasoning_text": "#52606F",
    "bubble_character_light_bg": "#E4EBF7",
    "bubble_character_light_text": "#1E3A6E",
    "bubble_character_light_border": "#8AA4D4",
    "bubble_assistant_light_bg": "#F3EAD9",
    "bubble_assistant_light_text": "#5C4526",
    "bubble_assistant_light_border": "#C5A059",
    "radius_panel": "12px",
    "radius_bubble": "12px",
    "radius_card": "10px",
    "radius_control": "8px",
    "font_family": FONT_FAMILY,
    "font_mono": FONT_MONO,
}

# 两个字典注入未缩放的基准字号键（保持键集合一致；组件一律经 scaled_tokens 读取）
for _key, _base in _BASE_FONT_SIZES.items():
    DARK_TOKENS[_key] = f"{_base}px"
    LIGHT_TOKENS[_key] = f"{_base}px"
DARK_TOKENS["_scale"] = "1.0"
LIGHT_TOKENS["_scale"] = "1.0"


def tokens_for_mode(mode: str) -> dict[str, str]:
    return LIGHT_TOKENS if mode == "light" else DARK_TOKENS


# ---------------------------------------------------------------------------
# 主题偏好持久化
# ---------------------------------------------------------------------------


_SETTINGS_PATH: Path | None = None


def _settings_path() -> Path:
    global _SETTINGS_PATH
    if _SETTINGS_PATH is not None:
        return _SETTINGS_PATH

    candidates: list[Path] = []
    configured = os.environ.get("PAIR_HARNESS_UI_SETTINGS_FILE")
    if configured:
        candidates.append(Path(configured))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "HSRPartnerHarness" / "PairHarness.ini")
    candidates.append(Path(tempfile.gettempdir()) / "HSRPartnerHarness" / "PairHarness.ini")

    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.touch(exist_ok=True)
        except OSError:
            continue
        _SETTINGS_PATH = candidate
        break
    else:
        _SETTINGS_PATH = candidates[-1]
    return _SETTINGS_PATH


def _settings() -> QSettings:
    # Windows 注册表在受限环境下可能静默拒绝写入；使用首个可写的用户级 INI。
    return QSettings(str(_settings_path()), QSettings.IniFormat)


def load_theme_preference() -> str:
    mode = str(_settings().value("ui/theme", "dark"))
    return mode if mode in ("dark", "light") else "dark"


def save_theme_preference(mode: str) -> None:
    if mode not in ("dark", "light"):
        raise ValueError(mode)
    settings = _settings()
    settings.setValue("ui/theme", mode)
    settings.sync()


# ---------------------------------------------------------------------------
# 气泡样式
# ---------------------------------------------------------------------------

# 深色主题下角色/助手默认色（与 message_list 既有默认完全一致，测试锁定）
_DARK_CHARACTER_DEFAULT = "background:#3A548C;color:#C7D4E3;border:1px solid #8AA4D4;"
_DARK_ASSISTANT_DEFAULT = "background:#332A20;color:#F0E2C5;border:1px solid #B08D57;"


def bubble_style_for(
    source: MessageSource,
    theme: PairTheme | None,
    tokens: dict[str, str],
) -> str:
    """按消息来源 + 当前主题令牌计算气泡样式。

    深色：角色/助手继续读取 PairTheme 品牌色，与既有行为完全一致；
    浅色：改用品牌色的浅色变体，保证对比度。
    用户/工具/系统中性气泡随令牌切换。
    """
    dark = tokens["mode"] == "dark"
    if source == MessageSource.CHARACTER:
        if not dark:
            return (
                f"background:{tokens['bubble_character_light_bg']};"
                f"color:{tokens['bubble_character_light_text']};"
                f"border:1px solid {tokens['bubble_character_light_border']};"
            )
        if theme is not None:
            return (
                f"background:{theme.character_deep};color:{theme.character_text};"
                f"border:1px solid {theme.character_primary};"
            )
        return _DARK_CHARACTER_DEFAULT
    if source == MessageSource.ASSISTANT:
        if not dark:
            return (
                f"background:{tokens['bubble_assistant_light_bg']};"
                f"color:{tokens['bubble_assistant_light_text']};"
                f"border:1px solid {tokens['bubble_assistant_light_border']};"
            )
        if theme is not None:
            return (
                f"background:{theme.assistant_shadow};color:{theme.assistant_bright};"
                f"border:1px solid {theme.assistant_primary};"
            )
        return _DARK_ASSISTANT_DEFAULT
    key = {
        MessageSource.USER: "bubble_user",
        MessageSource.TOOL: "bubble_tool",
        MessageSource.SYSTEM: "bubble_system",
    }[source]
    return (
        f"background:{tokens[f'{key}_bg']};color:{tokens[f'{key}_text']};"
        f"border:1px solid {tokens[f'{key}_border']};"
    )


def status_color(status: str, tokens: dict[str, str]) -> str:
    """工具运行/审批等状态着色。"""
    if status == "running":
        return tokens["accent"]
    if status in ("succeeded", "allow", "allow_for_conversation"):
        return tokens["success"]
    if status in ("failed", "deny"):
        return tokens["danger"]
    return tokens["text_secondary"]


def fade(hex_color: str, alpha: float) -> str:
    """把 #RRGGBB 转成 rgba(r,g,b,a)，用于彩色底上的弱化标签色。"""
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------------------
# 全局样式表
# ---------------------------------------------------------------------------


def build_app_stylesheet(tokens: dict[str, str]) -> str:
    """由令牌生成窗口级 QSS（内联 setStyleSheet 仍优先于它）。"""
    t = tokens
    return f"""
QMainWindow, QDialog {{
    background: {t['window_bg']};
}}
QWidget {{
    color: {t['text_primary']};
    font-family: {t['font_family']};
    font-size: {t['px_body']};
}}
QLabel {{
    background: transparent;
}}

/* ---- 按钮 ---- */
QPushButton {{
    background: {t['card_bg']};
    border: 1px solid {t['border']};
    border-radius: {t['radius_control']};
    padding: 6px 14px;
    color: {t['text_primary']};
}}
QPushButton:hover {{
    background: {t['border']};
    border-color: {t['border_strong']};
}}
QPushButton:pressed {{
    background: {t['border_strong']};
}}
QPushButton:disabled {{
    color: {t['text_muted']};
    background: {t['panel_bg']};
    border-color: {t['border']};
}}
QPushButton:checked {{
    background: {t['accent_soft']};
    border-color: {t['accent']};
    color: {t['accent']};
}}
QPushButton[kind="primary"] {{
    background: {t['accent']};
    border-color: {t['accent']};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{
    background: {t['accent_hover']};
    border-color: {t['accent_hover']};
}}
QPushButton[kind="primary"]:pressed {{
    background: {t['accent_pressed']};
    border-color: {t['accent_pressed']};
}}
QPushButton[kind="primary"]:disabled {{
    background: {t['border']};
    border-color: {t['border']};
    color: {t['text_muted']};
}}
QPushButton[kind="ghost"] {{
    background: transparent;
    border: 1px solid {t['border']};
    color: {t['text_secondary']};
}}
QPushButton[kind="ghost"]:hover {{
    background: {t['card_bg']};
    color: {t['text_primary']};
    border-color: {t['border_strong']};
}}
QPushButton[kind="ghost"]:checked {{
    background: {t['accent_soft']};
    border-color: {t['accent']};
    color: {t['accent']};
}}
QPushButton[kind="danger"] {{
    background: transparent;
    border: 1px solid {t['danger']};
    color: {t['danger']};
}}
QPushButton[kind="danger"]:hover {{
    background: {t['danger']};
    color: #FFFFFF;
}}

/* ---- 输入框 ---- */
QLineEdit {{
    background: {t['input_bg']};
    border: 1px solid {t['border']};
    border-radius: {t['radius_control']};
    padding: 8px 12px;
    min-height: 20px;
    selection-background-color: {t['accent']};
}}
QLineEdit:focus {{
    border-color: {t['accent']};
}}

/* ---- 下拉框 ---- */
QComboBox {{
    background: {t['card_bg']};
    border: 1px solid {t['border']};
    border-radius: {t['radius_control']};
    padding: 5px 12px;
    padding-right: 30px;
    min-height: 20px;
}}
QComboBox:hover {{
    border-color: {t['border_strong']};
    background: {t['panel_bg']};
}}
QComboBox:focus {{
    border-color: {t['accent']};
}}
QComboBox::drop-down {{
    border: 0;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: url("{CHEVRON_DOWN_URL}");
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background: {t['panel_bg']};
    border: 1px solid {t['border_strong']};
    border-radius: {t['radius_control']};
    padding: 4px;
    selection-background-color: {t['accent_soft']};
    selection-color: {t['text_primary']};
    outline: 0;
}}

/* ---- 工具按钮 ---- */
QToolButton {{
    background: transparent;
    border: 0;
    padding: 2px;
    color: {t['text_secondary']};
}}
QToolButton:hover {{
    color: {t['text_primary']};
}}

/* ---- 滚动条 ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t['border_strong']};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t['text_muted']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border_strong']};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---- 分割条 ---- */
QSplitter::handle {{
    background: {t['window_bg']};
    width: 6px;
}}
QSplitter::handle:hover {{
    background: {t['accent_soft']};
}}

/* ---- 列表与树 ---- */
QListWidget, QTreeWidget {{
    background: {t['panel_bg']};
    border: 1px solid {t['border']};
    border-radius: {t['radius_card']};
    outline: 0;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 6px 8px;
    border-radius: 6px;
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background: {t['card_bg']};
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {t['accent_soft']};
    color: {t['text_primary']};
}}

/* ---- 滚动区 ---- */
QScrollArea {{
    background: transparent;
    border: 0;
}}

QToolTip {{
    background: {t['panel_bg']};
    color: {t['text_primary']};
    border: 1px solid {t['border_strong']};
    padding: 4px 8px;
}}
"""


def apply_theme(window: object, mode: str, scale: float = 1.0) -> None:
    """把主题应用到窗口：全局 QSS + 逐组件 set_palette 重刷。

    scale 为界面缩放系数（按窗口宽度计算），只放大字号令牌。
    """
    tokens = scaled_tokens(tokens_for_mode(mode), scale)
    setter = getattr(window, "setStyleSheet", None)
    if setter is not None:
        setter(build_app_stylesheet(tokens))
    for child in ("character_messages", "assistant_messages", "input_bar",
                  "audio_controls", "approval_bar"):
        target = getattr(window, child, None)
        set_palette = getattr(target, "set_palette", None)
        if callable(set_palette):
            set_palette(tokens)
    save_theme_preference(mode)
