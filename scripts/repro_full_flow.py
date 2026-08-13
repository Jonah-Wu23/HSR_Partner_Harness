"""完整端到端复现：真实后端 + DeepSeek 引擎。

用户消息 → 角色回复（含委派）→ 古代机器（reasonix acp）执行 → 角色汇报结果。
同时验证标题自动生成（首轮后 conversation.title != 新聊天）。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pair_harness.cli import load_dotenv  # noqa: E402


async def main() -> None:
    load_dotenv(ROOT / ".env")
    db = Path(tempfile.mkdtemp(prefix="ph-flow-")) / "flow.db"
    from pair_harness.desktop_backend.application_service import build_configured_service
    from pair_harness.desktop_backend.commands import DesktopCommand

    def event_sink(message) -> None:
        import json as _json
        event = message if isinstance(message, dict) else _json.loads(message)
        kind = event.get("event")
        if kind in (
            "turn.started", "turn.status_changed", "message.created", "task.busy_changed",
            "error.reported", "tool_run.upserted", "conversation.changed",
        ):
            payload = event.get("payload", {})
            summary = (
                payload.get("status")
                or (payload.get("turn") or {}).get("status")
                or (payload.get("message") or {}).get("text")
                or (payload.get("tool_run") or {}).get("title")
                or (payload.get("conversation") or {}).get("title")
                or payload.get("message")
                or ""
            )
            print(f"[evt] {kind} seq={event.get('sequence')} {_json.dumps(str(summary)[:70], ensure_ascii=True)}")

    service = build_configured_service(
        database=db,
        project_root=ROOT,
        pair_id="phainon_ancient_machine",
        demo=False,
        event_sink=event_sink,
    )
    # 切到 DeepSeek 引擎（账号配置为空时默认 codex；此处直接注入 deepseek）
    from pair_harness.desktop_backend.engine_factory import build_coding_engine
    from pair_harness.core.contracts import ApprovalMode
    import os

    service.coding_engine = build_coding_engine(
        engine_choice="deepseek",
        codex_auth=service.codex_auth,
        model=os.getenv("PAIR_HARNESS_DIALOGUE_MODEL"),
        base_url=os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL"),
        api_key=os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY"),
    )
    service.orchestrator.coding_engine = service.coding_engine

    def cmd(method: str, **params) -> DesktopCommand:
        return DesktopCommand(request_id="r1", method=method, params=params)

    await service.handle_command(cmd("chat.submit", conversation_id=service.current_conversation_id,
                                    target="character", text="介绍一下这个项目，不用动手改东西"))

    for _ in range(240):
        if not service._turn_tasks:
            break
        await asyncio.sleep(1)
    await asyncio.sleep(2)  # 标题生成收尾
    for task in tuple(service._turn_tasks):
        if task.done() and task.exception() is not None:
            print("TURN TASK EXCEPTION:", repr(task.exception())[:300])

    snapshot = service.store.load_conversation(service.current_conversation_id)
    conv = service.store.get_conversation(service.current_conversation_id)
    print("title:", json.dumps(conv.title, ensure_ascii=True))
    print("messages:", len(snapshot["messages"]))
    for m in snapshot["messages"]:
        kind = f"{m.source}:{m.kind}"
        print(f"  - {kind} | {json.dumps(m.text[:80], ensure_ascii=True)}")
    runs = service.store.load_conversation(service.current_conversation_id)["tool_runs"]
    for run in runs:
        if run.status != "succeeded":
            print(f"  ! tool {run.title} status={run.status} error={json.dumps(str(run.details)[:150], ensure_ascii=True)}")
    print("turns:", service._conversation_turns_payload(service.current_conversation_id))
    await service.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
