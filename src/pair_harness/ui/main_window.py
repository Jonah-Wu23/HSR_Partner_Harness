from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pair_harness.config.pairs import PairTheme
from pair_harness.core.contracts import (
    ApprovalMode,
    EngineEvent,
    EngineEventType,
    Message,
    MessageSource,
    ToolRun,
)

from .approval_bar import ApprovalBar
from .audio_controls import AudioControls
from .input_bar import InputBar
from .message_list import MessageList
from .theme import (
    apply_theme,
    load_theme_preference,
    scale_for_width,
    scaled_tokens,
    tokens_for_mode,
)
from .tool_card import ToolCard


class MainWindow(QMainWindow):
    input_submitted = pyqtSignal(str, str)
    cancel_requested = pyqtSignal()
    # O1.7：审批区按钮裁决携带 approval_id（ApprovalDecision 的枚举值字符串）
    approval_decided = pyqtSignal(str, str)
    # 输入区审批模式下拉框切换（ApprovalMode 的枚举值字符串）
    approval_mode_changed = pyqtSignal(str)
    reasoning_effort_changed = pyqtSignal(str)
    # B2.6：语音控制经窗口单向桥接到 VoiceRuntime（设计 §5.5）
    push_to_talk_pressed = pyqtSignal()
    push_to_talk_released = pyqtSignal()
    stop_speech_requested = pyqtSignal()

    def __init__(self, theme: PairTheme | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Pair Harness — 白厄与神秘的古代机械")
        self.resize(1180, 760)
        self._theme = theme
        self._theme_mode = "dark"
        # 界面缩放系数：按窗口宽度自适应（resizeEvent 驱动）
        self._scale = 1.0
        self.tool_cards: dict[str, ToolCard] = {}
        self._approval_mode = ApprovalMode.REQUEST_APPROVAL
        self._library: QWidget | None = None

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        header = QHBoxLayout()
        # 顶栏左侧：应用标题 + 当前搭档名副标题
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        self.app_title = QLabel("Pair Harness")
        self.app_title.setObjectName("appTitle")
        self.app_title.setStyleSheet("font-size:15px;font-weight:700;")
        self.pair_subtitle = QLabel("白厄与神秘的古代机械")
        self.pair_subtitle.setObjectName("pairSubtitle")
        title_box.addWidget(self.app_title)
        title_box.addWidget(self.pair_subtitle)
        header.addLayout(title_box)
        header.addSpacing(16)
        self.library_button = QPushButton("项目与聊天")
        self.library_button.setObjectName("libraryButton")
        self.library_button.setProperty("kind", "ghost")
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("modeCombo")
        self.mode_combo.addItem("聊天模式", "chat")
        self.mode_combo.addItem("协作模式", "collaboration")
        self.cancel_button = QPushButton("取消当前任务")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setProperty("kind", "danger")
        self.cancel_button.setEnabled(False)
        # 主题切换按钮：文案显示将要切换到的目标模式，初始文案由 _apply_theme 设置
        self.theme_toggle = QPushButton()
        self.theme_toggle.setObjectName("themeToggle")
        self.theme_toggle.setProperty("kind", "ghost")
        header.addWidget(self.library_button)
        header.addWidget(self.mode_combo)
        header.addStretch(1)
        header.addWidget(self.theme_toggle)
        header.addWidget(self.cancel_button)
        root.addLayout(header)

        body = QHBoxLayout()
        self.project_library = QFrame()
        self.project_library.setObjectName("projectLibrary")
        self.project_library.setMaximumWidth(240)
        self.project_library.setVisible(False)
        self.library_layout = QVBoxLayout(self.project_library)
        self.library_layout.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.project_library)
        self.pair_rail = QListWidget()
        self.pair_rail.setObjectName("pairRail")
        self.pair_rail.addItem("白厄\n古代机械")
        self.pair_rail.setCurrentRow(0)
        self.pair_rail.setMaximumWidth(132)
        body.addWidget(self.pair_rail)

        self.splitter = QSplitter()
        self.splitter.setObjectName("conversationSplitter")
        self.character_panel = self._panel("白厄", "characterPanel")
        self.character_messages = MessageList(theme=self._theme)
        self.character_panel.layout().addWidget(self.character_messages)
        self.assistant_panel = self._panel("神秘的古代机械", "assistantPanel")
        self.assistant_messages = MessageList(theme=self._theme)
        self.tool_area = QWidget()
        self.tool_area.setObjectName("toolArea")
        self.tool_layout = QVBoxLayout(self.tool_area)
        self.tool_layout.setContentsMargins(0, 0, 0, 0)
        self.assistant_panel.layout().addWidget(self.assistant_messages)
        self.assistant_panel.layout().addWidget(self.tool_area)
        self.splitter.addWidget(self.character_panel)
        self.splitter.addWidget(self.assistant_panel)
        self.splitter.setSizes([600, 500])
        body.addWidget(self.splitter, 1)
        root.addLayout(body, 1)

        self.audio_controls = AudioControls()
        root.addWidget(self.audio_controls)
        self.input_bar = InputBar()
        root.addWidget(self.input_bar)
        # 设计 §4.3：审批区位于输入区正下方，横跨窗口宽度，默认隐藏
        self.approval_bar = ApprovalBar()
        root.addWidget(self.approval_bar)
        self.setCentralWidget(central)

        self.mode_combo.currentIndexChanged.connect(self._apply_mode)
        self.input_bar.submitted.connect(self.input_submitted)
        self.input_bar.approval_mode_changed.connect(self._sync_approval_mode)
        self.input_bar.reasoning_effort_changed.connect(
            self.reasoning_effort_changed
        )
        self.approval_bar.decided.connect(self.approval_decided)
        self.library_button.clicked.connect(self._toggle_library)
        self.cancel_button.clicked.connect(self.cancel_requested)
        # B2.6：语音控件信号单向桥（app.py 里接 VoiceRuntime）
        self.input_bar.push_to_talk_pressed.connect(self.push_to_talk_pressed)
        self.input_bar.push_to_talk_released.connect(self.push_to_talk_released)
        self.audio_controls.stop_requested.connect(self.stop_speech_requested)
        self.theme_toggle.clicked.connect(self._toggle_theme)
        self._apply_mode()
        # 构造末尾应用持久化主题：全局 QSS + 子组件调色板 + 面板样式
        self._apply_theme(load_theme_preference())

    def _panel(self, title: str, object_name: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName(object_name)
        layout = QVBoxLayout(panel)
        # 面板标题：身份色点 + 名称；色点颜色在 set_palette 里按搭档主题刷新
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_row.setContentsMargins(4, 4, 4, 0)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        header_row.addWidget(dot, 0, Qt.AlignVCenter)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size:14px;font-weight:600;")
        header_row.addWidget(title_label, 1)
        layout.addLayout(header_row)
        # 挂到面板对象上，set_palette 按 object_name 判断角色/助手配色
        panel._identity_dot = dot
        panel._title_label = title_label
        return panel

    def set_palette(self, tokens: dict[str, str]) -> None:
        """按主题令牌重刷两个面板样式、身份色点与副标题颜色（供主题切换调用）。"""
        self._tokens = tokens
        for card in self.tool_cards.values():
            card.set_palette(tokens)
        for panel, kind in (
            (self.character_panel, "character"),
            (self.assistant_panel, "assistant"),
        ):
            panel.setStyleSheet(
                f"QFrame#{panel.objectName()}{{background:{tokens['panel_bg']};"
                f"border:1px solid {tokens['border']};"
                f"border-radius:{tokens['radius_panel']};}}"
            )
            # 色点取搭档主题主色；无 theme 时回退角色蓝 / 助手青铜金
            fallback = "#8AA4D4" if kind == "character" else "#B08D57"
            color = fallback
            if self._theme is not None:
                color = (
                    self._theme.character_primary
                    if kind == "character"
                    else self._theme.assistant_primary
                )
            panel._identity_dot.setStyleSheet(
                f"background:{color};border-radius:5px;"
            )
            # 面板有内联样式时全局 QWidget 颜色规则到不了子标签，标题色需显式给
            panel._title_label.setStyleSheet(
                f"font-size:{tokens['px_title']};font-weight:600;"
                f"color:{tokens['text_primary']};"
            )
        self.app_title.setStyleSheet(
            f"font-size:{tokens['px_app']};font-weight:700;"
            f"color:{tokens['text_primary']};"
        )
        self.pair_subtitle.setStyleSheet(
            f"font-size:{tokens['px_sub']};color:{tokens['text_secondary']};"
        )

    def _apply_theme(self, mode: str) -> None:
        """应用主题并记录当前 mode：全局 QSS、子组件调色板、面板样式与按钮文案。"""
        self._theme_mode = mode
        apply_theme(self, mode, self._scale)
        self.set_palette(scaled_tokens(tokens_for_mode(mode), self._scale))
        # 文案显示将要切换到的目标模式
        self.theme_toggle.setText("浅色模式" if mode == "dark" else "深色模式")

    def _toggle_theme(self) -> None:
        self._apply_theme("light" if self._theme_mode == "dark" else "dark")

    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时按比例缩放界面字号（0.05 步进，避免频繁重建）。"""
        super().resizeEvent(event)
        scale = scale_for_width(self.width())
        if scale != self._scale and hasattr(self, "theme_toggle"):
            self._scale = scale
            self._apply_theme(self._theme_mode)

    @property
    def mode(self) -> str:
        return str(self.mode_combo.currentData())

    def set_mode(self, mode: str) -> None:
        index = self.mode_combo.findData(mode)
        if index < 0:
            raise ValueError(mode)
        self.mode_combo.setCurrentIndex(index)

    def _apply_mode(self) -> None:
        collaboration = self.mode == "collaboration"
        self.assistant_panel.setVisible(collaboration)
        self.input_bar.set_collaboration_mode(collaboration)
        if collaboration:
            self.splitter.setSizes([600, 500])

    def set_busy(self, busy: bool) -> None:
        self.cancel_button.setEnabled(busy)

    def set_project_library(self, library: QWidget) -> None:
        """挂载左上角的项目与聊天库（计划 A6）。"""
        self._library = library
        self.library_layout.addWidget(library)

    def set_approval_mode(self, mode: str) -> None:
        """恢复项目保存的审批模式（打开项目时调用）。"""
        self._approval_mode = ApprovalMode(mode)
        self.input_bar.set_approval_mode(mode)

    def set_reasoning_effort(self, effort: str) -> None:
        self.input_bar.set_reasoning_effort(effort)

    def clear_conversation(self) -> None:
        """切换聊天前清空当前消息和工具卡片。"""
        self.character_messages.clear_messages()
        self.assistant_messages.clear_messages()
        for card in self.tool_cards.values():
            self.tool_layout.removeWidget(card)
            card.deleteLater()
        self.tool_cards.clear()

    def show_approval_request(
        self, approval_id: str, summary: str, reason: str
    ) -> None:
        """请求批准模式下，把一次待审批操作交给审批区展示。

        O1.7：approval_id 贯通到队列项，裁决信号按 id 返回。
        """
        self.approval_bar.enqueue_request(approval_id, summary, reason)

    def _sync_approval_mode(self, mode: str) -> None:
        self._approval_mode = ApprovalMode(mode)
        self.approval_mode_changed.emit(mode)

    def _toggle_library(self) -> None:
        if self._library is not None:
            self.project_library.setVisible(not self.project_library.isVisible())

    def add_message(self, message: Message) -> None:
        # O4.5：工具消息不再产生（O4.1 起工具走 ToolCard 渲染），
        # TOOL 来源不再有专属路由分支，一律按角色面板展示（历史兼容）。
        # 注意：use_enum_values 下 message.source 是字符串，须用 == 比较
        if message.source == MessageSource.ASSISTANT:
            self.assistant_messages.add_message(message)
        else:
            self.character_messages.add_message(message)

    def update_tool_run(self, tool_run: ToolRun) -> ToolCard:
        card = self.tool_cards.get(tool_run.tool_call_id)
        if card is None:
            card = ToolCard(tool_run)
            # 新建卡片立即套用当前主题令牌（默认是深色，浅色主题下需重刷）
            card.set_palette(self._tokens)
            self.tool_cards[tool_run.tool_call_id] = card
            self.tool_layout.addWidget(card)
        else:
            card.update_run(tool_run)
        return card

    def apply_engine_event(self, event: EngineEvent) -> None:
        # O2.1：工具卡片增量渲染对所有模式生效（流式通道 + 事后回放共用此路径）
        if event.type in (EngineEventType.TOOL_STARTED, EngineEventType.TOOL_FINISHED):
            self._apply_tool_event(event)
            return
        # 设计 §4.3：帮我审核模式只显示审查状态与最终裁决文字，无按钮；
        # 请求批准模式的交互由 ApprovalBar 与 approval_callback 桥完成，
        # 完全允许运行模式下审批区不出现。
        if self._approval_mode != ApprovalMode.REVIEW:
            return
        if event.type == EngineEventType.APPROVAL_REQUESTED:
            reason = str(event.payload.get("reason", ""))
            self.approval_bar.show_review(f"审查中… {reason}" if reason else "审查中…")
        elif event.type == EngineEventType.APPROVAL_RESOLVED:
            decision = event.payload.get("decision")
            allowed = decision == "allow"
            reason = str(event.payload.get("reason", ""))
            suggestion = str(event.payload.get("suggestion", ""))
            text = "审查结果：" + ("允许" if allowed else "否决")
            if reason:
                text += f"（{reason}）"
            if suggestion:
                text += f"；调整建议：{suggestion}"
            self.approval_bar.show_review(text)

    def _apply_tool_event(self, event: EngineEvent) -> None:
        """O2.1：由 tool 事件构造 ToolRun 并创建/更新工具卡片。

        - tool.started：以 running 状态立即出现卡片；
        - tool.finished：按事件 payload 更新状态与摘要。
        """
        payload = event.payload
        if event.type == EngineEventType.TOOL_STARTED:
            run = ToolRun(
                tool_call_id=event.tool_call_id or "",
                conversation_id=event.conversation_id,
                task_id=event.task_id,
                engine_turn_id=event.engine_turn_id,
                sequence=event.sequence,
                status="running",
                title=str(payload.get("title", "工具")),
                summary=str(payload.get("summary", "")),
                details=str(payload.get("details", "")),
            )
        else:
            run = ToolRun(
                tool_call_id=event.tool_call_id or "",
                conversation_id=event.conversation_id,
                task_id=event.task_id,
                engine_turn_id=event.engine_turn_id,
                sequence=event.sequence,
                status=str(payload.get("status", "succeeded")),  # type: ignore[arg-type]
                title=str(payload.get("title", "工具")),
                summary=str(payload.get("summary", "")),
                details=str(payload.get("details", "")),
            )
        self.update_tool_run(run)
