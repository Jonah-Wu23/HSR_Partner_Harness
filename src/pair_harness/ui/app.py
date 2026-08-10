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

    # 审批裁决桥：orchestrator 在请求批准模式下挂起等待 UI 决策
    approval_futures: list[asyncio.Future] = []

    async def approval_callback(op: PendingOperation) -> ApprovalDecision:
        future = asyncio.get_running_loop().create_future()
        approval_futures.append(future)
        window.show_approval_request(op.summary, op.command or "")
        return await future

    @asyncSlot(str)
    def decide(decision: str) -> None:
        if not approval_futures:
            return
        future = approval_futures.pop(0)
        if not future.done():
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
    for message in snapshot["messages"]:
        window.add_message(message)
    for tool_run in snapshot["tool_runs"]:
        window.update_tool_run(tool_run)

    def on_quit() -> None:
        # 窗口关闭时否决仍未裁决的审批，避免悬挂
        for future in approval_futures:
            if not future.done():
                future.set_result(ApprovalDecision.DENY)
        store.close()

    app.aboutToQuit.connect(on_quit)

    @asyncSlot(str, str)
    async def submit(target: str, text: str) -> None:
        if target == "assistant":
            outcome = await orchestrator.handle_direct_input(
                conversation_id="demo-conversation", text=text
            )
        else:
            outcome = await orchestrator.handle_character_input(
                conversation_id="demo-conversation", text=text
            )
        for message in outcome.messages:
            window.add_message(message)
        for tool_run in outcome.tool_runs:
            window.update_tool_run(tool_run)
        # 帮我审核模式的审查状态与裁决文字由事件流回放显示
        for event in outcome.engine_events:
            window.apply_engine_event(event)
        # busy 开始/复位由 orchestrator 执行生命周期回调驱动（O1.4）

    # O1.4：busy 状态由 orchestrator 执行生命周期驱动，不再用演示触发词猜测
    orchestrator.on_execution_started = lambda: window.set_busy(True)
    orchestrator.on_execution_finished = lambda: window.set_busy(False)

    window.input_submitted.connect(submit)
    window.show()
    if os.getenv("QT_QPA_PLATFORM") == "offscreen":
        QTimer.singleShot(250, app.quit)
    with loop:
        loop.run_forever()
    return 0
