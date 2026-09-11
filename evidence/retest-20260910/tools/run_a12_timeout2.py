"""A12 超时阶段：在干净会话上挂机等待真实 600 秒审批超时。

审批超时常量 `application_service.py:335 APPROVAL_TIMEOUT_S = 600.0` 硬编码、
无可配置入口，因此不存在"短超时等效"路径，只能按真实 600 秒验证。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from ph_client import Harness, HarnessError, event_fields, now_iso
from s4common import (
    WS_URL,
    case_dir,
    load_token,
    sidecar_log_mark,
    sidecar_tail,
    write_commands,
)

CASE = "A12"
APPROVAL_TIMEOUT_S = 600.0


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso(), "phase": "timeout-real-600s"}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames-timeout2.log",
                      events_log=out / "events-timeout2.log", device_name="s4-a12-timeout2")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next(p for p in (bootstrap.get("projects") or [])
                       if p.get("name") == "project-alpha")
        created = await session.call(
            "conversation.create",
            {"project_id": project["project_id"], "pair_id": "phainon_ancient_machine",
             "title": "A12-timeout-2"}, timeout=30)
        conversation_id = created["current_conversation_id"]
        log["conversation_id"] = conversation_id
        await session.call("conversation.set_mode",
                           {"conversation_id": conversation_id, "mode": "collaboration"},
                           timeout=30)
        await session.call(
            "chat.submit",
            {"conversation_id": conversation_id, "target": "assistant",
             "text": "请让神秘的古代机械在项目根目录新建文件 a12-timeout-2.md，"
                     "内容写一行：S4-A12-超时挂机样本。写完后回报结果。"},
            timeout=60)

        requested = await session.wait_event(
            "approval.requested", timeout=300,
            predicate=lambda e: event_fields(e).get("conversation_id") == conversation_id)
        fields = event_fields(requested)
        approval_id = fields.get("approval_id")
        anchor_mono = time.monotonic()
        log["approval_requested"] = {
            "approval_id": approval_id, "conversation_id": conversation_id,
            "task_id": fields.get("task_id"), "operation": fields.get("operation"),
            "reason": fields.get("reason"), "at": now_iso(),
            "timeout_constant_s": APPROVAL_TIMEOUT_S, "configurable": False,
        }
        print(json.dumps({"anchored_at": log["approval_requested"]["at"],
                          "approval_id": approval_id,
                          "waiting_s": APPROVAL_TIMEOUT_S}, ensure_ascii=False), flush=True)

        resolved = await session.wait_event(
            "approval.resolved", timeout=APPROVAL_TIMEOUT_S + 240,
            predicate=lambda e: event_fields(e).get("approval_id") == approval_id)
        rf = event_fields(resolved)
        log["approval_resolved"] = {
            "decision": rf.get("decision"), "resolved_by": rf.get("resolved_by"),
            "actor": rf.get("actor"), "reason": rf.get("reason"),
            "error_code": rf.get("error_code"), "at": now_iso(),
            "waited_s": round(time.monotonic() - anchor_mono, 3),
        }
        print(json.dumps(log["approval_resolved"], ensure_ascii=False), flush=True)

        late = None
        try:
            await session.call("approval.resolve",
                               {"approval_id": approval_id, "decision": "allow"}, timeout=30)
            late = {"accepted": True}
        except HarnessError as exc:
            late = {"accepted": False, "code": exc.code, "message": exc.message,
                    "details": exc.details}
        log["late_decision"] = late

        await asyncio.sleep(15)
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=60)
        log["conversation_after"] = {
            "active_task": snapshot.get("active_task"),
            "queue_items": snapshot.get("queue_items"),
            "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                          "status": m.get("status"), "text": str(m.get("text"))[:120]}
                         for m in snapshot.get("messages", [])],
        }
        after = await session.call("app.bootstrap", timeout=30)
        log["pending_after"] = after.get("approvals")
        log["active_tasks_after"] = after.get("active_tasks")
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar-timeout2.log")
    (out / "a12-timeout.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands-timeout.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a12_timeout2.py",
        "# 真实等待 600 秒；期间不做任何裁决",
    ])
    print("A12 timeout measurement finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
