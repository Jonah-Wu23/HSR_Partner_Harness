from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pair_harness.adapters.demo import ScriptedCodingEngine, ScriptedDialogueModel
from pair_harness.core.contracts import ApprovalMode, MessageSource, ProjectRef
from pair_harness.core.orchestrator import ConversationOrchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pair Harness local demo")
    parser.add_argument("--demo", action="store_true", help="run predictable local adapters")
    parser.add_argument("--project", default=".", help="project folder")
    parser.add_argument("--message", default="请让古代机械创建 hello.txt")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.demo:
        raise SystemExit("计划 A 仅支持 --demo；真实后端属于计划 B。")
    return asyncio.run(run_demo(Path(args.project), args.message))


if __name__ == "__main__":
    raise SystemExit(main())

