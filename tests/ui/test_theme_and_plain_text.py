"""O4.5：气泡富文本转义与主题读取。

- QLabel 默认 AutoText 会把含 <...> 的消息当富文本渲染，统一改 PlainText；
- 角色/助手气泡颜色改读 PairConfig.theme（B3 前置），theme 缺省回退默认色。
"""

from PyQt5.QtCore import Qt

from pair_harness.config.pairs import PairTheme
from pair_harness.core.contracts import Message, MessageKind, MessageSource
from pair_harness.ui.main_window import MainWindow
from pair_harness.ui.message_list import MessageBubble, MessageList, bubble_style
from pair_harness.ui.tool_card import ToolCard

from pair_harness.core.contracts import ToolRun


def theme() -> PairTheme:
    return PairTheme(
        character_text="#C7D4E3",
        character_primary="#8AA4D4",
        character_deep="#3A548C",
        character_active="#296CE1",
        assistant_primary="#B08D57",
        assistant_bright="#C5A059",
        assistant_shadow="#8C6B3F",
    )


def message(source: MessageSource, text: str, *, reasoning: str = "") -> Message:
    return Message(
        conversation_id="c",
        pair_id="phainon_ancient_machine",
        source=source,
        kind=MessageKind.CHARACTER_SPEECH
        if source is MessageSource.CHARACTER
        else MessageKind.ASSISTANT_NATURAL_LANGUAGE,
        text=text,
        payload={"reasoning": reasoning} if reasoning else {},
    )


def test_message_bubble_renders_html_as_plain_text(qtbot) -> None:
    """O4.5：助手输出含 <...> 时按纯文本显示，不被当富文本解析。"""
    bubble = MessageBubble(
        message(MessageSource.ASSISTANT, "创建了 <hello.txt> 与 <b>未加粗</b>"),
        theme=theme(),
    )
    qtbot.addWidget(bubble)

    assert bubble.text_label.textFormat() == Qt.PlainText
    assert bubble.text_label.text() == "创建了 <hello.txt> 与 <b>未加粗</b>"


def test_character_bubble_colors_read_pair_theme(qtbot) -> None:
    """O4.5：角色气泡读取 theme 三色（深层背景/浅色文字/主色边框）。"""
    bubble = MessageBubble(message(MessageSource.CHARACTER, "我在。"), theme=theme())
    qtbot.addWidget(bubble)

    assert "#3A548C" in bubble.styleSheet()
    assert "#C7D4E3" in bubble.styleSheet()
    assert "#8AA4D4" in bubble.styleSheet()


def test_assistant_bubble_colors_read_pair_theme(qtbot) -> None:
    """O4.5：助手气泡读取 theme 三色（阴影背景/亮色文字/主色边框）。"""
    bubble = MessageBubble(message(MessageSource.ASSISTANT, "正在执行。"), theme=theme())
    qtbot.addWidget(bubble)

    assert "#8C6B3F" in bubble.styleSheet()
    assert "#C5A059" in bubble.styleSheet()
    assert "#B08D57" in bubble.styleSheet()


def test_bubble_falls_back_to_default_colors_without_theme(qtbot) -> None:
    """theme 缺省时回退内置默认色，未配置场景行为不变。"""
    bubble = MessageBubble(message(MessageSource.CHARACTER, "我在。"))
    qtbot.addWidget(bubble)

    assert bubble_style(MessageSource.CHARACTER, None) in bubble.styleSheet()
    assert "#3A548C" in bubble.styleSheet()


def test_neutral_sources_ignore_theme(qtbot) -> None:
    """用户/系统消息保持中性固定样式，不随 theme 变化（设计 §4.5）。"""
    user = MessageBubble(message(MessageSource.USER, "你好"), theme=theme())
    system = MessageBubble(message(MessageSource.SYSTEM, "状态"), theme=theme())
    qtbot.addWidget(user)
    qtbot.addWidget(system)

    assert bubble_style(MessageSource.USER, theme()) == bubble_style(MessageSource.USER, None)
    assert bubble_style(MessageSource.SYSTEM, theme()) == bubble_style(MessageSource.SYSTEM, None)
    assert "#8AA4D4" not in user.styleSheet()


def test_message_list_propagates_theme(qtbot) -> None:
    """MainWindow 传入 theme 后，add_message 的气泡读取该主题。"""
    window = MainWindow(theme=theme())
    qtbot.addWidget(window)

    window.add_message(message(MessageSource.CHARACTER, "我在。"))
    window.add_message(message(MessageSource.ASSISTANT, "正在执行。"))

    assert "#3A548C" in window.character_messages.bubbles[-1].styleSheet()
    assert "#8C6B3F" in window.assistant_messages.bubbles[-1].styleSheet()


def test_reasoning_is_per_message_collapsed_and_toggleable(qtbot) -> None:
    """聊天角色、协作角色与助手均逐条折叠；无思考消息不显示控件。"""
    window = MainWindow(theme=theme())
    qtbot.addWidget(window)

    window.set_mode("chat")
    window.add_message(message(MessageSource.CHARACTER, "聊天正文", reasoning="聊天思考"))
    chat_bubble = window.character_messages.bubbles[-1]
    assert chat_bubble.reasoning_toggle is not None
    assert chat_bubble.reasoning_label is not None
    assert chat_bubble.final_label is not None
    assert chat_bubble.reasoning_label.isHidden()
    chat_bubble.reasoning_toggle.click()
    assert not chat_bubble.reasoning_label.isHidden()
    assert chat_bubble.reasoning_label.text() == "聊天思考"
    chat_bubble.reasoning_toggle.click()
    assert chat_bubble.reasoning_label.isHidden()

    window.set_mode("collaboration")
    window.add_message(message(MessageSource.CHARACTER, "协作角色正文", reasoning="角色思考"))
    window.add_message(message(MessageSource.ASSISTANT, "助手正文", reasoning="助手思考"))
    role_bubble = window.character_messages.bubbles[-1]
    assistant_bubble = window.assistant_messages.bubbles[-1]
    for bubble, expected in ((role_bubble, "角色思考"), (assistant_bubble, "助手思考")):
        assert bubble.reasoning_toggle is not None
        assert bubble.reasoning_label is not None
        assert bubble.reasoning_label.isHidden()
        bubble.reasoning_toggle.click()
        assert not bubble.reasoning_label.isHidden()
        assert bubble.reasoning_label.text() == expected
        bubble.reasoning_toggle.click()
        assert bubble.reasoning_label.isHidden()

    plain = MessageBubble(message(MessageSource.CHARACTER, "没有思考"), theme=theme())
    qtbot.addWidget(plain)
    assert plain.reasoning_toggle is None
    assert plain.reasoning_label is None
    assert plain.final_label is None


def test_tool_card_uses_qt_enum_values(qtbot) -> None:
    """O4.5：setToolButtonStyle/setArrowType 使用 Qt 枚举而非魔法数字。"""
    run = ToolRun(
        tool_call_id="tool-1",
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn",
        sequence=1,
        status="running",
        title="pytest",
        summary="starting",
        details="full output",
    )
    card = ToolCard(run)
    qtbot.addWidget(card)

    assert card.toggle.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    assert card.toggle.arrowType() == Qt.UpArrow
    card.toggle.click()
    assert card.toggle.arrowType() == Qt.DownArrow


def test_tool_card_renders_details_as_plain_text(qtbot) -> None:
    """O4.5：工具卡片的摘要/详情含 <...> 时按纯文本显示。"""
    run = ToolRun(
        tool_call_id="tool-1",
        conversation_id="c",
        task_id="t",
        engine_turn_id="turn",
        sequence=1,
        status="running",
        title="pytest",
        summary="写入 <config.toml>",
        details="<b>未加粗</b> 的完整输出",
    )
    card = ToolCard(run)
    qtbot.addWidget(card)

    assert card.summary_label.textFormat() == Qt.PlainText
    assert card.details_label.textFormat() == Qt.PlainText
    assert card.summary_label.text() == "写入 <config.toml>"
    assert card.details_label.text() == "<b>未加粗</b> 的完整输出"
