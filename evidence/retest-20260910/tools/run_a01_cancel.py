"""A01 补充：协作会话的取消与审批归属（协议级）。

上一轮 A01 的四会话并发/排队/归属已取证；本脚本补齐：
- 在新会话提交真实委派任务，捕获 approval.requested 的归属字段；
- 任务挂起在审批上时调用 task.cancel；
- 验证取消后：待审批双端移除、任务进入取消终态、被取消的工作没有产生副作用。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ph_client import Harness, event_fields, now_iso
from s4common import (
    WS_URL,
    case_dir,
    load_token,
    sidecar_log_mark,
    sidecar_tail,
    write_commands,
    write_http_log,
)

CASE = "A01"
WORKSPACE = Path(r"E:\AI\HSR-v039-acceptance\project-alpha")
TARGET_FILE = WORKSPACE / "a01-cancel.md"


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}

    session = Harness(WS_URL, token, frames_log=out / "ws-frames-cancel.log",
                      events_log=out / "events-cancel.log", device_name="s4-a01-cancel")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next(p for p in (bootstrap.get("projects") or [])
                       if p.get("name") == "project-alpha")
        created = await session.call(
            "conversation.create",
            {"project_id": project["project_id"], "pair_id": "march7_fourth_mirror",
             "title": "A01-cancel"}, timeout=30)
        conversation_id = created["current_conversation_id"]
        log["conversation_id"] = conversation_id
        await session.call("conversation.set_mode",
                           {"conversation_id": conversation_id, "mode": "collaboration"},
                           timeout=30)
        # 取消前确认目标文件不存在，便于判定"取消后无副作用"
        log["target_file_exists_before"] = TARGET_FILE.exists()

        submitted = await session.call(
            "chat.submit",
            {"conversation_id": conversation_id, "target": "assistant",
             "text": "请让第四面镜在项目根目录新建文件 a01-cancel.md，"
                     "内容写一行：S4-A01-取消样本。写完回报执行结果。"},
            timeout=60)
        log["submit_message_id"] = submitted.get("message_id") if isinstance(submitted, dict) else None
        print(json.dumps({"submitted": log["submit_message_id"]}, ensure_ascii=False), flush=True)

        requested = await session.wait_event(
            "approval.requested", timeout=300,
            predicate=lambda e: event_fields(e).get("conversation_id") == conversation_id)
        fields = event_fields(requested)
        approval_id = fields.get("approval_id")
        log["approval_requested"] = {
            "approval_id": approval_id,
            "conversation_id": fields.get("conversation_id"),
            "task_id": fields.get("task_id"),
            "operation": fields.get("operation"),
            "reason": fields.get("reason"),
            "at": now_iso(),
        }
        print(json.dumps(log["approval_requested"], ensure_ascii=False), flush=True)

        # 取消时审批仍挂起：验证取消是否同时回收待审批
        cancel_result = await session.call("task.cancel",
                                           {"conversation_id": conversation_id}, timeout=60)
        log["cancel_result"] = cancel_result
        log["cancel_at"] = now_iso()

        await session.wait_event(
            "approval.resolved", timeout=90,
            predicate=lambda e: event_fields(e).get("approval_id") == approval_id)
        resolved = [e for e in session.events_named("approval.resolved")
                    if event_fields(e).get("approval_id") == approval_id]
        log["approval_resolved_after_cancel"] = [
            {k: event_fields(e).get(k) for k in
             ("approval_id", "decision", "resolved_by", "actor", "reason", "error_code")}
            for e in resolved
        ]

        await asyncio.sleep(8)
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=60)
        log["conversation_after_cancel"] = {
            "active_task": snapshot.get("active_task"),
            "queue_items": snapshot.get("queue_items"),
            "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                          "status": m.get("status"), "text": str(m.get("text"))[:120]}
                         for m in snapshot.get("messages", [])],
            "tool_runs": [{"tool_call_id": t.get("tool_call_id"), "status": t.get("status")}
                          for t in snapshot.get("tool_runs", [])],
        }
        after = await session.call("app.bootstrap", timeout=30)
        log["pending_approvals_after_cancel"] = after.get("approvals")
        log["active_tasks_after_cancel"] = after.get("active_tasks")
        log["target_file_exists_after"] = TARGET_FILE.exists()
        print(json.dumps({"after_cancel": {
            "active_task": log["conversation_after_cancel"]["active_task"],
            "pending": log["pending_approvals_after_cancel"],
            "file_exists": log["target_file_exists_after"]}}, ensure_ascii=False), flush=True)
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar-cancel.log")
    (out / "a01-cancel.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands-cancel.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a01_cancel.py",
    ])
    write_http_log(out / "http-cancel.log", "A01 取消用例：全部交互走 WS 帧")
    print("A01 cancel finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
