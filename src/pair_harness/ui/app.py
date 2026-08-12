from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QFileDialog
from qasync import QEventLoop, asyncSlot

from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.app_paths import AppPaths
from pair_harness.cli import load_dotenv
from pair_harness.config.pairs import PairConfig, load_pair_config, load_prompt
from pair_harness.config.providers import load_reasoning_preset
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    PendingOperation,
    ProjectRef,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.voice_runtime import VoiceRuntime
from pair_harness.settings import Settings
from pair_harness.storage.sqlite_store import SQLiteStore
from pair_harness.ui.project_library import ProjectLibrary

from .main_window import MainWindow
from .qt_bridge import OrchestratorBridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pair Harness desktop app")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--real", action="store_true", help="真实后端：DeepSeek 对话 + codex app-server")
    parser.add_argument(
        "--real-voice",
        action="store_true",
        help="真实语音链路：DashScope ASR/TTS + 本地 VAD（--real 隐含开启）",
    )
    parser.add_argument("--pair", default="phainon_ancient_machine")
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--data-dir", type=Path)
    return parser


def _get_or_create_project(
    store: SQLiteStore, root_path: Path, *, reasoning_effort: str = "low"
):
    root_path = root_path.resolve()
    existing = store.find_project_by_root_path(str(root_path))
    if existing is not None:
        return existing
    return store.create_project(
        project_id=str(uuid4()),
        name=root_path.name or str(root_path),
        root_path=str(root_path),
        reasoning_effort=reasoning_effort,
    )


def _get_or_create_conversation(
    store: SQLiteStore, *, project_id: str, pair_id: str
):
    for conversation in store.list_conversations(project_id):
        if conversation.pair_id == pair_id:
            return conversation
    return store.create_conversation(
        project_id=project_id,
        pair_id=pair_id,
        title="新聊天",
    )


async def _start_voice_runtime(runtime: VoiceRuntime) -> None:
    """在 qasync 事件循环开始运行后启动采集与播放任务。"""
    await runtime.start_listening()
    runtime.start_playback()


def _schedule_voice_runtime_start(runtime: VoiceRuntime) -> asyncio.Task[None]:
    """允许桌面应用在事件循环运行前安排语音运行时启动。"""
    return asyncio.ensure_future(_start_voice_runtime(runtime))


def wire_real_voice(
    *,
    settings: Settings,
    window: MainWindow,
    orchestrator: ConversationOrchestrator,
    pair_config: PairConfig,
    conversation_id: str,
) -> VoiceRuntime:
    """B2.6：``--real-voice`` 装配（设计 §5.5）。

    真实三件套（Silero VAD / Qwen 流式 ASR / Qwen 流式 TTS）替换 demo
    音频适配器，创建 VoiceRuntime 并接线：消息监听挂 TTS 下行、
    VAD/PTT/停止信号桥接、回调驱动状态条与输入区回显。
    本地 VAD 不可用（缺模型或 onnxruntime）时自动退回按键说话；
    语音失败经 on_error 显示在状态条（静音，不阻塞会话）。
    """
    # 语音适配器依赖较重，保持惰性导入，不拖累无语音环境
    from pair_harness.adapters.audio.qwen_asr import QwenStreamingRecognizer
    from pair_harness.adapters.audio.qwen_tts import QwenSpeechSynthesizer
    from pair_harness.adapters.audio.silero_vad import (
        SileroVoiceActivityDetector,
        VadUnavailableError,
    )
    from pair_harness.adapters.audio.sounddevice_io import AudioPlayer, MicrophoneCapture
    from pair_harness.core.audio import SpeechQueue

    if not settings.dashscope_api_key:
        raise SystemExit("--real-voice 缺少 DASHSCOPE_API_KEY（.env 或进程环境）")
    model_path = (
        Path(__file__).resolve().parents[3] / "assets" / "models" / "silero_vad_v5.onnx"
    )
    try:
        vad: SileroVoiceActivityDetector | None = SileroVoiceActivityDetector(model_path)
    except VadUnavailableError:
        vad = None

    def apply_vad_state(state: str) -> None:
        # playing 同时启用停止按钮（AudioControls.set_playing），
        # 其余状态只改状态条文案
        window.audio_controls.set_vad_state(state)
        window.audio_controls.set_playing(state == "playing")

    runtime = VoiceRuntime(
        orchestrator=orchestrator,
        recognizer=QwenStreamingRecognizer(
            api_key=settings.dashscope_api_key,
            ws_url=settings.resolved_ws_url,
            model=settings.qwen_asr_model,
        ),
        synthesizer=QwenSpeechSynthesizer(
            api_key=settings.dashscope_api_key,
            ws_url=settings.resolved_ws_url,
            model=settings.qwen_tts_model,
        ),
        vad=vad,
        capture_factory=lambda: MicrophoneCapture(block_size=640),
        player=AudioPlayer(sample_rate=24_000),
        queue=SpeechQueue(),
        pair_config=pair_config,
        conversation_id=conversation_id,
        on_vad_state=apply_vad_state,
        on_asr_partial=window.input_bar.set_asr_interim,
        on_error=lambda message: window.audio_controls.vad_label.setText(message),
    )
    orchestrator.add_message_listener(runtime.on_message)
    _schedule_voice_runtime_start(runtime)

    @asyncSlot()
    async def ptt_start() -> None:
        await runtime.push_to_talk_start(target=window.input_bar.target)

    @asyncSlot()
    async def ptt_stop() -> None:
        await runtime.push_to_talk_stop()

    window.push_to_talk_pressed.connect(ptt_start)
    window.push_to_talk_released.connect(ptt_stop)
    window.stop_speech_requested.connect(runtime.stop_speaking)
    return runtime


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.demo or args.real):
        raise SystemExit("需要 --demo 或 --real")
    real_voice = args.real_voice or args.real  # B1 --real 隐含 --real-voice
    if args.real or real_voice:
        # B1：真实后端 —— .env 只在此处显式加载，密钥不进代码与配置
        load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    settings = Settings.from_environment() if (args.real or real_voice) else None
    app = QApplication.instance() or QApplication([sys.argv[0]])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    # O4.5：气泡颜色读取搭档主题（B3 前置）；配置缺失时抛 PairConfigError
    pair_config = load_pair_config(args.pair)
    window = MainWindow(theme=pair_config.theme)
    paths = AppPaths(args.data_dir) if args.data_dir else AppPaths.default()
    store = SQLiteStore(paths.ensure().database)
    project_record = _get_or_create_project(store, args.project)
    conversation_record = _get_or_create_conversation(
        store, project_id=project_record.project_id, pair_id=args.pair
    )
    assistant_instructions = load_prompt(pair_config.assistant.prompt)

    if args.real:
        missing = [
            name
            for name, value in (
                ("PAIR_HARNESS_DIALOGUE_BASE_URL", settings.dialogue_base_url if settings else None),
                ("PAIR_HARNESS_DIALOGUE_API_KEY", settings.dialogue_api_key if settings else None),
                ("PAIR_HARNESS_DIALOGUE_MODEL", settings.dialogue_model if settings else None),
            )
            if not value
        ]
        if missing:
            raise SystemExit(f"--real 缺少环境变量: {', '.join(missing)}（.env 或进程环境）")
        assert settings is not None and settings.dialogue_base_url and settings.dialogue_api_key and settings.dialogue_model
        preset = load_reasoning_preset(settings.dialogue_base_url, settings.dialogue_model)
        dialogue_model = OpenAICompatibleDialogueModel(
            base_url=settings.dialogue_base_url,
            api_key=settings.dialogue_api_key,
            model=settings.dialogue_model,
            thinking=preset.default_thinking,
            reasoning_effort=(
                None
                if project_record.reasoning_effort == "auto"
                else project_record.reasoning_effort
            ),
            temperature=1.0,
        )
        coding_engine = CodexAppServerEngine(JsonlProcessTransport(settings.codex_bin))
    else:
        dialogue_model = ScriptedDialogueModel()
        coding_engine = ScriptedCodingEngine()

    current = {
        "project": project_record,
        "conversation_id": conversation_record.conversation_id,
    }
    window.set_approval_mode(project_record.approval_mode)
    window.set_reasoning_effort(project_record.reasoning_effort)

    # 审批裁决桥：orchestrator 在请求批准模式下挂起等待 UI 决策。
    # O1.7：按 approval_id 对应 future，不再依赖 FIFO 顺序巧合。
    approval_futures: dict[str, asyncio.Future] = {}

    async def approval_callback(
        op: PendingOperation, approval_id: str, reason: str
    ) -> ApprovalDecision:
        future = asyncio.get_running_loop().create_future()
        approval_futures[approval_id] = future
        # O1.7：展示真实理由（风险标签或“需要用户审批”），不再用命令文本冒充
        window.show_approval_request(approval_id, op.summary, reason)
        return await future

    @asyncSlot(str, str)
    def decide(approval_id: str, decision: str) -> None:
        future = approval_futures.pop(approval_id, None)
        if future is not None and not future.done():
            future.set_result(ApprovalDecision(decision))

    window.approval_decided.connect(decide)

    orchestrator = ConversationOrchestrator(
        pair_id=args.pair,
        project=ProjectRef(
            project_id=project_record.project_id,
            name=project_record.name,
            root_path=project_record.root_path,
        ),
        dialogue_model=dialogue_model,
        coding_engine=coding_engine,
        store=store,
        approval_mode=ApprovalMode(project_record.approval_mode),
        approval_callback=approval_callback,
        # B1：帮我审核模式下审查智能体复用真实对话模型
        reviewer=DialogueModelReviewer(dialogue_model) if args.real else None,
        assistant_instructions=assistant_instructions,
    )

    @asyncSlot(str)
    def approval_mode_selected(mode: str) -> None:
        # 计划 A5：切换后立即写入项目设置，并同步编排器
        project_id = current["project"].project_id
        store.update_project_approval_mode(project_id, mode)
        current["project"] = store.get_project(project_id)
        orchestrator.set_approval_mode(
            ApprovalMode(mode), conversation_id=current["conversation_id"]
        )

    window.approval_mode_changed.connect(approval_mode_selected)

    @asyncSlot(str)
    def reasoning_effort_selected(effort: str) -> None:
        project_id = current["project"].project_id
        store.update_project_reasoning_effort(project_id, effort)
        current["project"] = store.get_project(project_id)
        if isinstance(dialogue_model, OpenAICompatibleDialogueModel):
            dialogue_model.reasoning_effort = None if effort == "auto" else effort

    window.reasoning_effort_changed.connect(reasoning_effort_selected)

    bridge = OrchestratorBridge()
    bridge.message_ready.connect(window.add_message)
    bridge.tool_run_ready.connect(window.update_tool_run)
    bridge.engine_event_ready.connect(window.apply_engine_event)
    bridge.busy_changed.connect(window.set_busy)

    def emit_current_message(message) -> None:
        if message.conversation_id == current["conversation_id"]:
            bridge.message_ready.emit(message)

    def emit_current_event(event) -> None:
        if event.conversation_id == current["conversation_id"]:
            bridge.engine_event_ready.emit(event)

    orchestrator.on_message = emit_current_message
    orchestrator.on_engine_event = emit_current_event
    orchestrator.on_execution_started = lambda: bridge.busy_changed.emit(True)
    orchestrator.on_execution_finished = lambda: bridge.busy_changed.emit(False)

    voice_runtime: VoiceRuntime | None = None
    project_library = ProjectLibrary(store)
    window.set_project_library(project_library)

    def switch_conversation(conversation_id: str) -> None:
        conversation = store.get_conversation(conversation_id)
        if conversation.project_id is None:
            return
        project = store.get_project(conversation.project_id)
        selected_pair = load_pair_config(conversation.pair_id)
        selected_assistant_prompt = load_prompt(selected_pair.assistant.prompt)
        old_conversation_id = current["conversation_id"]
        if old_conversation_id != conversation_id:
            orchestrator.close_conversation(old_conversation_id)
        current["project"] = project
        current["conversation_id"] = conversation_id
        orchestrator.select_context(
            project=ProjectRef(
                project_id=project.project_id,
                name=project.name,
                root_path=project.root_path,
            ),
            pair_id=conversation.pair_id,
            conversation_id=conversation_id,
            approval_mode=ApprovalMode(project.approval_mode),
            assistant_instructions=selected_assistant_prompt,
        )
        if isinstance(dialogue_model, OpenAICompatibleDialogueModel):
            dialogue_model.reasoning_effort = (
                None if project.reasoning_effort == "auto" else project.reasoning_effort
            )
        window.clear_conversation()
        window.set_approval_mode(project.approval_mode)
        window.set_reasoning_effort(project.reasoning_effort)
        window.set_mode(conversation.last_mode)
        snapshot = store.load_conversation(conversation_id)
        orchestrator.restore_conversation(snapshot)
        for message in snapshot["messages"]:
            window.add_message(message)
        for tool_run in snapshot["tool_runs"]:
            window.update_tool_run(tool_run)
        if voice_runtime is not None:
            voice_runtime.set_context(conversation_id, selected_pair)

    def create_project() -> None:
        selected = QFileDialog.getExistingDirectory(window, "选择项目文件夹")
        if not selected:
            return
        project = _get_or_create_project(store, Path(selected))
        conversation = _get_or_create_conversation(
            store, project_id=project.project_id, pair_id=args.pair
        )
        project_library.refresh()
        switch_conversation(conversation.conversation_id)

    def create_conversation(project_id: str) -> None:
        project = store.get_project(project_id)
        conversation = store.create_conversation(
            project_id=project.project_id,
            pair_id=args.pair,
            title="新聊天",
        )
        project_library.refresh()
        switch_conversation(conversation.conversation_id)

    project_library.conversation_selected.connect(switch_conversation)
    project_library.project_create_requested.connect(create_project)
    project_library.conversation_create_requested.connect(create_conversation)
    switch_conversation(conversation_record.conversation_id)

    def on_quit() -> None:
        # 窗口关闭时否决仍未裁决的审批，避免悬挂
        for future in approval_futures.values():
            if not future.done():
                future.set_result(ApprovalDecision.DENY)

    app.aboutToQuit.connect(on_quit)

    @asyncSlot(str, str)
    async def submit(target: str, text: str) -> None:
        # O2.1：消息、工具事件与审批展示已由流式回调实时到达界面，
        # ConversationOutcome 仅保留为最终汇总，不再事后回放。
        conversation_id = current["conversation_id"]
        try:
            if target == "assistant":
                await orchestrator.handle_direct_input(
                    conversation_id=conversation_id, text=text
                )
            else:
                await orchestrator.handle_character_input(
                    conversation_id=conversation_id, text=text
                )
        except Exception as exc:
            orchestrator.report_system_status(
                conversation_id, f"请求失败：{exc}"
            )

    window.input_submitted.connect(submit)

    @asyncSlot()
    async def cancel_task() -> None:
        # O2.3：取消按钮接通编排器取消入口；无活动任务时 cancel_active_task
        # 返回 False，由 set_busy 的按钮禁用兜底。
        try:
            await orchestrator.cancel_active_task()
        except Exception as exc:
            orchestrator.report_system_status(
                current["conversation_id"], f"取消失败：{exc}"
            )

    window.cancel_requested.connect(cancel_task)

    if real_voice:
        assert settings is not None
        voice_runtime = wire_real_voice(
            settings=settings,
            window=window,
            orchestrator=orchestrator,
            pair_config=pair_config,
            conversation_id=current["conversation_id"],
        )
    window.show()
    if os.getenv("QT_QPA_PLATFORM") == "offscreen":
        QTimer.singleShot(250, app.quit)
    with loop:
        try:
            loop.run_forever()
        finally:
            if voice_runtime is not None:
                loop.run_until_complete(voice_runtime.shutdown())
            if isinstance(dialogue_model, OpenAICompatibleDialogueModel):
                loop.run_until_complete(dialogue_model.aclose())
            if isinstance(coding_engine, CodexAppServerEngine):
                loop.run_until_complete(coding_engine.transport.close())
            store.close()
    return 0
