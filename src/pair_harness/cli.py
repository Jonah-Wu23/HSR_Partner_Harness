from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import JsonlProcessTransport
from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.adapters.reviewer import DialogueModelReviewer
from pair_harness.app_paths import AppPaths
from pair_harness.config.pairs import load_pair_config, load_prompt
from pair_harness.config.providers import load_reasoning_preset
from pair_harness.core.contracts import ApprovalDecision, ApprovalMode, MessageSource, ProjectRef
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.settings import Settings
from pair_harness.storage.sqlite_store import SQLiteStore


def load_dotenv(path: Path) -> None:
    """把仓库根 ``.env`` 的 KEY=VALUE 行载入进程环境（不覆盖已存在的值）。

    B1：``.env`` 不参与打包分发，也不会被自动加载；真实联调与运行时
    从这里读取密钥，已显式设置的环境变量优先。
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pair Harness local demo")
    parser.add_argument("--demo", action="store_true", help="run predictable local adapters")
    parser.add_argument("--real", action="store_true", help="run live dialogue API + codex app-server")
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


async def run_demo(project_path: Path, text: str) -> int:
    project_path = project_path.resolve()
    project = ProjectRef(
        project_id="demo-project",
        name=project_path.name,
        root_path=str(project_path),
    )
    orchestrator = ConversationOrchestrator(
        pair_id="phainon_ancient_machine",
        project=project,
        dialogue_model=ScriptedDialogueModel(),
        coding_engine=ScriptedCodingEngine(),
        approval_mode=ApprovalMode.FULL_AUTO,
    )
    outcome = await orchestrator.handle_character_input(
        conversation_id="demo-conversation",
        text=text,
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
    """B1：真实后端单轮冒烟。

    - 对话模型走 DeepSeek（或任意 OpenAI 兼容端点，三个环境变量切换）；
    - 编程引擎走 codex app-server（``PAIR_HARNESS_CODEX_BIN``）；
    - 状态库持久化：同一 ``--conversation`` 二次运行恢复旧聊天与编程线程
      （thread/resume），新会话 id 另开新线程（不继承旧会话）；
    - 审批策略按 ``_engine_policy`` 映射（§14.6），三种模式逐一可验。
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
    assert settings.dialogue_base_url and settings.dialogue_api_key and settings.dialogue_model

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

    preset = load_reasoning_preset(settings.dialogue_base_url, settings.dialogue_model)
    dialogue = OpenAICompatibleDialogueModel(
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
    transport = JsonlProcessTransport(settings.codex_bin)
    engine = CodexAppServerEngine(transport)
    reviewer = DialogueModelReviewer(dialogue) if approval_mode == ApprovalMode.REVIEW else None

    async def approval_callback(op, approval_id: str, reason: str) -> ApprovalDecision:
        print(f"[审批] {approval_id} {op.summary}（{reason}）→ {'允许' if approve else '拒绝'}")
        return ApprovalDecision.ALLOW if approve else ApprovalDecision.DENY

    project = ProjectRef(
        project_id=project_record.project_id,
        name=project_record.name,
        root_path=project_record.root_path,
    )
    try:
        store.create_conversation(
            conversation_id=stored_conversation_id,
            project_id=project.project_id,
            pair_id=pair_id,
            title="CLI 真实联调",
        )
        orchestrator = ConversationOrchestrator(
            pair_id=pair_id,
            project=project,
            dialogue_model=dialogue,
            coding_engine=engine,
            store=store,
            approval_mode=approval_mode,
            reviewer=reviewer,
            approval_callback=approval_callback,
            assistant_instructions=assistant_instructions,
        )
        snapshot = store.load_conversation(stored_conversation_id)
        if snapshot["messages"]:
            orchestrator.restore_conversation(snapshot)
            print(
                f"[会话] 恢复旧聊天 {conversation_id}"
                f"（{len(snapshot['messages'])} 条消息）"
            )

        outcome = await orchestrator.handle_character_input(
            conversation_id=stored_conversation_id, text=text
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
        await transport.close()
        await dialogue.aclose()
        store.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.demo:
        return asyncio.run(run_demo(Path(args.project), args.message))
    if args.real:
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
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


if __name__ == "__main__":
    raise SystemExit(main())
