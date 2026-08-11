from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from qasync import QEventLoop, asyncSlot

from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.app_paths import AppPaths
from pair_harness.cli import load_dotenv
from pair_harness.config.pairs import PairConfig, load_pair_config
from pair_harness.config.providers import load_reasoning_preset
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    PendingOperation,
    ProjectRef,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
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
    parser.add_argument("--data-dir", type=Path)
    return parser


def wire_real_voice(
    *,
    settings: Settings,
    window: MainWindow,
    orchestrator: ConversationOrchestrator,
    pair_config: PairConfig,
    conversation_id: str,
) -> None:
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
    from pair_harness.core.voice_runtime import VoiceRuntime

    if not settings.dashscope_api_key:
        raise SystemExit("--real-voice 缺少 DASHSCOPE_API_KEY（.env 或进程环境）")
    model_path = (
        Path(__file__).resolve().parents[2] / "assets" / "models" / "silero_vad_v5.onnx"
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
    asyncio.ensure_future(runtime.start_listening())
    asyncio.ensure_future(runtime.run_playback_loop())

    @asyncSlot()
    async def ptt_start() -> None:
        await runtime.push_to_talk_start(target=window.input_bar.target)

    @asyncSlot()
    async def ptt_stop() -> None:
        await runtime.push_to_talk_stop()

    window.push_to_talk_pressed.connect(ptt_start)
    window.push_to_talk_released.connect(ptt_stop)
    window.stop_speech_requested.connect(runtime.stop_speaking)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.demo or args.real):
        raise SystemExit("需要 --demo 或 --real")
    real_voice = args.real_voice or args.real  # B1 --real 隐含 --real-voice
    if args.real or real_voice:
        # B1：真实后端 —— .env 只在此处显式加载，密钥不进代码与配置
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_environment() if (args.real or real_voice) else None
    app = QApplication.instance() or QApplication([sys.argv[0]])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    # O4.5：气泡颜色读取搭档主题（B3 前置）；配置缺失时抛 PairConfigError
    pair_config = load_pair_config(args.pair)
    window = MainWindow(theme=pair_config.theme)
    paths = AppPaths(args.data_dir) if args.data_dir else AppPaths.default()
    store = SQLiteStore(paths.ensure().database)

    if args.real:
        project_id = f"real-{args.pair}"
        conversation_id = "real-conversation"
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
            reasoning_effort="max",
            temperature=1.0,
        )
        coding_engine = CodexAppServerEngine(JsonlProcessTransport(settings.codex_bin))
    else:
        project_id = "demo-project"
        conversation_id = "demo-conversation"
        dialogue_model = ScriptedDialogueModel()
        coding_engine = ScriptedCodingEngine()

    store.create_project(
        project_id=project_id,
        name=pair_config.character.name,
        root_path=str(Path.cwd()),
    )
    store.create_conversation(
        conversation_id=conversation_id,
        project_id=project_id,
        pair_id=args.pair,
        title="白厄与古代机械",
    )
    # 打开项目时恢复上次选择的审批模式（计划 A6）
    project_record = store.get_project(project_id)
    window.set_approval_mode(project_record.approval_mode)

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
        project=ProjectRef(project_id=project_id, name=pair_config.character.name, root_path=str(Path.cwd())),
        dialogue_model=dialogue_model,
        coding_engine=coding_engine,
        store=store,
        approval_mode=ApprovalMode(project_record.approval_mode),
        approval_callback=approval_callback,
        # B1：帮我审核模式下审查智能体复用真实对话模型
        reviewer=DialogueModelReviewer(dialogue_model) if args.real else None,
    )

    @asyncSlot(str)
    def approval_mode_selected(mode: str) -> None:
        # 计划 A5：切换后立即写入项目设置，并同步编排器
        store.update_project_approval_mode(project_id, mode)
        orchestrator.set_approval_mode(ApprovalMode(mode))

    window.approval_mode_changed.connect(approval_mode_selected)

    # 挂载项目与聊天库（计划 A6 第 4 步）
    window.set_project_library(ProjectLibrary(store))
    snapshot = store.load_conversation(conversation_id)
    # O2.2：恢复旧聊天时回填编排器的消息历史与会话引用，
    # 角色不失忆，Codex 可 thread/resume 而非重新 thread/start
    orchestrator.restore_conversation(snapshot)
    for message in snapshot["messages"]:
        window.add_message(message)
    for tool_run in snapshot["tool_runs"]:
        window.update_tool_run(tool_run)

    def on_quit() -> None:
        # 窗口关闭时否决仍未裁决的审批，避免悬挂
        for future in approval_futures.values():
            if not future.done():
                future.set_result(ApprovalDecision.DENY)
        store.close()

    app.aboutToQuit.connect(on_quit)

    @asyncSlot(str, str)
    async def submit(target: str, text: str) -> None:
        # O2.1：消息、工具事件与审批展示已由流式回调实时到达界面，
        # ConversationOutcome 仅保留为最终汇总，不再事后回放。
        if target == "assistant":
            await orchestrator.handle_direct_input(
                conversation_id=conversation_id, text=text
            )
        else:
            await orchestrator.handle_character_input(
                conversation_id=conversation_id, text=text
            )

    # O2.1：流式事件通道——orchestrator 产生消息/事件即推送，UI 增量渲染
    bridge = OrchestratorBridge()
    bridge.message_ready.connect(window.add_message)
    bridge.tool_run_ready.connect(window.update_tool_run)
    bridge.engine_event_ready.connect(window.apply_engine_event)
    bridge.busy_changed.connect(window.set_busy)
    orchestrator.on_message = bridge.message_ready.emit
    orchestrator.on_engine_event = bridge.engine_event_ready.emit
    # busy 开始/复位由 orchestrator 执行生命周期回调驱动（O1.4 + O2.1 桥接）
    orchestrator.on_execution_started = lambda: bridge.busy_changed.emit(True)
    orchestrator.on_execution_finished = lambda: bridge.busy_changed.emit(False)

    window.input_submitted.connect(submit)

    @asyncSlot()
    async def cancel_task() -> None:
        # O2.3：取消按钮接通编排器取消入口；无活动任务时 cancel_active_task
        # 返回 False，由 set_busy 的按钮禁用兜底。
        await orchestrator.cancel_active_task()

    window.cancel_requested.connect(cancel_task)

    if real_voice:
        assert settings is not None
        wire_real_voice(
            settings=settings,
            window=window,
            orchestrator=orchestrator,
            pair_config=pair_config,
            conversation_id=conversation_id,
        )
    window.show()
    if os.getenv("QT_QPA_PLATFORM") == "offscreen":
        QTimer.singleShot(250, app.quit)
    with loop:
        loop.run_forever()
    return 0
