from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from qasync import QEventLoop, asyncSlot

from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.app_paths import AppPaths
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    PendingOperation,
    ProjectRef,
)
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.storage.sqlite_store import SQLiteStore
from pair_harness.ui.project_library import ProjectLibrary

from .main_window import MainWindow
from .qt_bridge import OrchestratorBridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pair Harness desktop app")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.demo:
        raise SystemExit("计划 A 仅支持 --demo；真实后端属于计划 B。")
    app = QApplication.instance() or QApplication([sys.argv[0]])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainWindow()
    paths = AppPaths(args.data_dir) if args.data_dir else AppPaths.default()
    store = SQLiteStore(paths.ensure().database)
    store.create_project(
        project_id="demo-project",
        name="Demo",
        root_path=str(Path.cwd()),
    )
    store.create_conversation(
        conversation_id="demo-conversation",
        project_id="demo-project",
        pair_id="phainon_ancient_machine",
        title="白厄与古代机械",
    )
    # 打开项目时恢复上次选择的审批模式（计划 A6）
    project_record = store.get_project("demo-project")
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
        pair_id="phainon_ancient_machine",
        project=ProjectRef(project_id="demo-project", name="Demo", root_path=str(Path.cwd())),
        dialogue_model=ScriptedDialogueModel(),
        coding_engine=ScriptedCodingEngine(),
        store=store,
        approval_mode=ApprovalMode(project_record.approval_mode),
        approval_callback=approval_callback,
    )

    @asyncSlot(str)
    def approval_mode_selected(mode: str) -> None:
        # 计划 A5：切换后立即写入项目设置，并同步编排器
        store.update_project_approval_mode("demo-project", mode)
        orchestrator.set_approval_mode(ApprovalMode(mode))

    window.approval_mode_changed.connect(approval_mode_selected)

    # 挂载项目与聊天库（计划 A6 第 4 步）
    window.set_project_library(ProjectLibrary(store))
    snapshot = store.load_conversation("demo-conversation")
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
                conversation_id="demo-conversation", text=text
            )
        else:
            await orchestrator.handle_character_input(
                conversation_id="demo-conversation", text=text
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
    window.show()
    if os.getenv("QT_QPA_PLATFORM") == "offscreen":
        QTimer.singleShot(250, app.quit)
    with loop:
        loop.run_forever()
    return 0
