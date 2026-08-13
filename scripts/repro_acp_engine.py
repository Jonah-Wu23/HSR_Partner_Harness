"""ACP 引擎集成测试：复刻 engine_factory 的 reasonix acp 子进程链路。

验证 WinError 2 修复：initialize → session/new → 短 session/prompt 走通
DeepSeek 编程助手的 ACP v1 会话（真实 API 调用，指令极短）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pair_harness.cli import load_dotenv  # noqa: E402
from pair_harness.desktop_backend.engine_factory import (  # noqa: E402
    build_coding_engine,
    resolve_reasonix_executable,
)
from pair_harness.core.contracts import (  # noqa: E402
    ApprovalMode,
    EngineEventType,
    ProjectRef,
    TaskRequest,
    TaskStatus,
    utc_now,
)
from pair_harness.adapters.codex.auth import CodexAuthService  # noqa: E402


async def main() -> None:
    load_dotenv(ROOT / ".env")
    import os

    executable = resolve_reasonix_executable()
    print(f"reasonix executable: {executable}")
    auth = CodexAuthService(Path(os.getenv("TEMP", "/tmp")) / "ph-acp-test", "default-local")
    engine = build_coding_engine(
        engine_choice="deepseek",
        codex_auth=auth,
        model=os.getenv("PAIR_HARNESS_DIALOGUE_MODEL"),
        base_url=os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL"),
        api_key=os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY"),
    )
    project = ProjectRef(
        project_id="repro",
        name="HSR Partner Harness",
        root_path=str(ROOT),
    )
    session = await engine.open_session(
        project,
        approval_policy="untrusted",
        sandbox="read-only",
    )
    print(f"session: {session.engine_type} {session.opaque_ref[:24]}…")
    request = TaskRequest(
        conversation_id="repro",
        task_id=f"task-{utc_now().strftime('%H%M%S')}",
        origin_message_id="msg-repro",
        instructions="列出当前目录顶层文件，只要一行摘要，不要修改任何文件。",
    )
    count = 0
    async for event in engine.run_turn(session, request):
        count += 1
        if event.type in (EngineEventType.ASSISTANT_DELTA, EngineEventType.TOOL_STARTED):
            print(f"[{event.type}] {str(event.payload.get('text') or event.payload.get('title'))[:60]}")
        if event.type in (EngineEventType.TURN_COMPLETED, EngineEventType.TURN_FAILED):
            print(f"[final] {event.type} payload={event.payload}")
    print(f"total events: {count}")
    await engine.transport.close()


if __name__ == "__main__":
    asyncio.run(main())
