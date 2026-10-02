from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.app_paths import AppPaths
from pair_harness.config.pairs import load_pair_config, load_prompt
from pair_harness.core.context import ExecutionContext
from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    MessageSource,
    PendingOperation,
    ProjectRef,
)
from pair_harness.core.orchestrator import ApprovalCallback, ConversationOrchestrator
from pair_harness.desktop_backend.engine_factory import build_coding_engine
from pair_harness.settings import Settings
from pair_harness.storage.sqlite_store import SQLiteStore

DEFAULT_ACCOUNT_ID = "default-local"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pair Harness local demo")
    parser.add_argument("--demo", action="store_true", help="run predictable local adapters")
    parser.add_argument("--real", action="store_true", help="run live dialogue API + reasonix acp")
    parser.add_argument("--pair", default="phainon_ancient_machine", help="pair id (--real)")
    parser.add_argument("--project", default=".", help="project folder")
    parser.add_argument("--message", default="请让古代机械创建 hello.txt，内容为 hello")
    parser.add_argument(
        "--approval-mode",
        choices=["full-auto", "request-approval", "review"],
        default="request-approval",
        help="审批模式（--real；默认 request-approval）",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="request-approval 模式下自动允许全部审批（联调冒烟用）",
    )
    parser.add_argument(
        "--conversation",
        default="cli-smoke",
        help="会话 id（--real；同一 id 二次运行恢复旧聊天与编程线程）",
    )
    parser.add_argument("--data-dir", type=Path, help="状态库目录（默认 %LOCALAPPDATA%/PairHarness）")
    return parser


def _console_approval(approve: bool) -> ApprovalCallback:
    """按 ``--approve`` 裁决全部审批请求，并把每次裁决打印到终端。"""

    async def approval_callback(
        op: PendingOperation,
        approval_id: str,
        reason: str,
        conversation_id: str,
        task_id: str,
    ) -> ApprovalDecision:
        print(
            f"[审批] {approval_id} {op.summary}（{reason}）"
            f"→ {'允许' if approve else '拒绝'}"
        )
        return ApprovalDecision.ALLOW if approve else ApprovalDecision.DENY

    return approval_callback


async def run_demo(project_path: Path, text: str, approve: bool) -> int:
    project_path = project_path.resolve()
    orchestrator = ConversationOrchestrator(
        dialogue_model=ScriptedDialogueModel(),
        coding_engine=ScriptedCodingEngine(),
        approval_callback=_console_approval(approve),
    )
    context = ExecutionContext(
        account_id=DEFAULT_ACCOUNT_ID,
        project=ProjectRef(
            project_id="demo-project",
            name=project_path.name,
            root_path=str(project_path),
        ),
        conversation_id="demo-conversation",
        pair_id="phainon_ancient_machine",
        conversation_mode="collaboration",
        approval_mode=ApprovalMode.FULL_AUTO,
        assistant_instructions="",
    )
    outcome = await orchestrator.handle_character_input(
        conversation_id=context.conversation_id,
        text=text,
        context=context,
    )
    for message in outcome.messages[:2]:
        print(f"{message.source} → {message.text}")
    for event in outcome.engine_events:
        if event.type == "tool.finished":
            print(f"tool → {event.payload.get('summary', '')}")
    for message in outcome.messages[2:]:
        if message.source == MessageSource.ASSISTANT:
            print(f"assistant → {message.text}")
    for message in outcome.messages[2:]:
        if message.source == MessageSource.CHARACTER:
            print(f"character → {message.text}")
    print("说明：未执行真实文件工具。")
    return 0


async def run_real(
    *,
    project_path: Path,
    pair_id: str,
    text: str,
    approval_mode: ApprovalMode,
    approve: bool,
    conversation_id: str,
    data_dir: Path | None,
) -> int:
    """真实后端单轮冒烟。

    - 角色和助手共用同一供应商配置（任意 OpenAI Chat Completions 兼容端点）；
    - 编程引擎是 Reasonix ACP，端点经 ``PAIR_HARNESS_DIALOGUE_BASE_URL``
      写入账号私有的 Reasonix 配置；
    - 状态库持久化：同一 ``--conversation`` 二次运行恢复旧聊天与 ACP 会话，
      新会话 id 另开会话；
    - 审批模式随执行上下文交给编排器裁决，三种模式逐一可验。
    """
    project_path = project_path.resolve()
    settings = Settings.from_environment()
    missing = [
        name
        for name, value in (
            ("PAIR_HARNESS_DIALOGUE_BASE_URL", settings.dialogue_base_url),
            ("PAIR_HARNESS_DIALOGUE_API_KEY", settings.dialogue_api_key),
            ("PAIR_HARNESS_DIALOGUE_MODEL", settings.dialogue_model),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"--real 缺少环境变量: {', '.join(missing)}（.env 或进程环境）")

    paths = AppPaths(Path(data_dir)).ensure() if data_dir else AppPaths.default().ensure()
    store = SQLiteStore(paths.database)
    project_record = store.find_project_by_root_path(str(project_path))
    if project_record is None:
        project_record = store.create_project(
            name=project_path.name,
            root_path=str(project_path),
            approval_mode=approval_mode.value,
        )
    else:
        store.update_project_approval_mode(project_record.project_id, approval_mode.value)
        project_record = store.get_project(project_record.project_id)
    stored_conversation_id = f"{project_record.project_id}:{conversation_id}"
    pair_config = load_pair_config(pair_id)
    assistant_instructions = load_prompt(pair_config.assistant.prompt)

    dialogue = OpenAICompatibleDialogueModel(
        base_url=settings.dialogue_base_url,
        api_key=settings.dialogue_api_key,
        model=settings.dialogue_model,
        temperature=1.0,
    )
    engine = build_coding_engine(
        codex_auth=CodexAuthService(paths.database.parent, DEFAULT_ACCOUNT_ID),
        model=settings.dialogue_model,
        base_url=settings.dialogue_base_url,
        api_key=settings.dialogue_api_key,
    )
    reviewer = DialogueModelReviewer(dialogue) if approval_mode == ApprovalMode.REVIEW else None
    # CLI 单账号运行：归属当前或默认本地账号
    account_id = store.get_app_state("current_account_id") or DEFAULT_ACCOUNT_ID
    context = ExecutionContext(
        account_id=account_id,
        project=ProjectRef(
            project_id=project_record.project_id,
            name=project_record.name,
            root_path=project_record.root_path,
        ),
        conversation_id=stored_conversation_id,
        pair_id=pair_id,
        conversation_mode="collaboration",
        approval_mode=approval_mode,
        assistant_instructions=assistant_instructions,
    )
    try:
        store.create_conversation(
            conversation_id=stored_conversation_id,
            project_id=project_record.project_id,
            pair_id=pair_id,
            title="CLI 真实联调",
            account_id=account_id,
        )
        orchestrator = ConversationOrchestrator(
            dialogue_model=dialogue,
            coding_engine=engine,
            store=store,
            reviewer=reviewer,
            approval_callback=_console_approval(approve),
        )
        snapshot = store.load_conversation(stored_conversation_id)
        if snapshot.messages:
            orchestrator.restore_conversation(snapshot)
            print(
                f"[会话] 恢复旧聊天 {conversation_id}"
                f"（{len(snapshot.messages)} 条消息）"
            )

        outcome = await orchestrator.handle_character_input(
            conversation_id=stored_conversation_id, text=text, context=context
        )
        for message in outcome.messages:
            if message.source in (MessageSource.USER, MessageSource.CHARACTER, MessageSource.ASSISTANT):
                print(f"{message.source} → {message.text}")
        for event in outcome.engine_events:
            if event.type == "tool.finished":
                print(f"tool → {event.payload.get('status', '')} {event.payload.get('summary', '')}")
        receipt = outcome.receipt
        if receipt is not None:
            print(f"receipt → {receipt.status} 错误={len(receipt.errors)}")
            for error in receipt.errors:
                print(f"  error → {error}")
        return 0 if receipt is not None and receipt.status == "completed" else 1
    finally:
        await engine.aclose()
        await dialogue.aclose()
        store.close()


def main(argv: list[str] | None = None) -> int:
    _configure_stdio_utf8()
    args = build_parser().parse_args(argv)
    if args.demo:
        return asyncio.run(run_demo(Path(args.project), args.message, args.approve))
    if args.real:
        # .env 只在仓库内真实联调时使用，已设置的进程环境变量优先。
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", encoding="utf-8-sig")
        return asyncio.run(
            run_real(
                project_path=Path(args.project),
                pair_id=args.pair,
                text=args.message,
                approval_mode=ApprovalMode(args.approval_mode.replace("-", "_")),
                approve=args.approve,
                conversation_id=args.conversation,
                data_dir=args.data_dir,
            )
        )
    raise SystemExit("需要 --demo 或 --real")


def _configure_stdio_utf8() -> None:
    """让 CLI 在 Windows GBK 与系统 UTF-8 模式下都使用稳定的 UTF-8 I/O。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
