"""A12：协议级审批 —— 并发裁决、重放拒绝、真实 600 秒超时。

分三个阶段：
R 并发裁决：对同一待审批同时发出 allow 与 deny 两个裁决请求，验证只有一个生效、
  另一个拿到 approval_already_resolved 且携带生效方的真实终态；随后重放同一动作，
  验证幂等（不产生第二次执行，副作用只发生一次）。
T 真实 600 秒超时：审批超时常量硬编码（application_service.py:335
  APPROVAL_TIMEOUT_S = 600.0，无可配置入口，因此不做"短超时等效"），
  按真实 600 秒挂机等待服务端产生 timeout 终态，再验证迟到裁决被拒且携带真实终态。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from ph_client import Harness, HarnessError, event_fields, now_iso
from s4common import (
    WS_URL,
    case_dir,
    load_token,
    sidecar_log_mark,
    sidecar_tail,
    write_commands,
    write_http_log,
)

CASE = "A12"
APPROVAL_TIMEOUT_S = 600.0
WORKSPACE = Path(r"E:\AI\HSR-v039-acceptance\project-alpha")


async def phase_race(out: Path, token: str, log: dict) -> None:
    """并发裁决 + 重放拒绝。"""
    session_a = Harness(WS_URL, token, frames_log=out / "ws-frames-race-a.log",
                        device_name="s4-a12-race-a")
    session_b = Harness(WS_URL, token, frames_log=out / "ws-frames-race-b.log",
                        device_name="s4-a12-race-b")
    await session_a.connect()
    await session_b.connect()
    try:
        bootstrap = await session_a.call("app.bootstrap", timeout=30)
        pending = bootstrap.get("approvals") or []
        if not pending:
            log["race"] = {"status": "no_pending_approval"}
            return
        target = pending[0]
        approval_id = target["approval_id"]
        log["race"] = {
            "approval_id": approval_id,
            "attribution": {
                "conversation_id": target.get("conversation_id"),
                "task_id": target.get("task_id"),
                "operation": target.get("operation"),
                "reason": target.get("reason"),
            },
            "pending_before": len(pending),
        }
        print(json.dumps({"phase": "R", "approval_id": approval_id,
                          "conversation_id": target.get("conversation_id"),
                          "task_id": target.get("task_id")}, ensure_ascii=False), flush=True)

        # 两个独立连接、两个相反裁决，尽量同时发出。
        req_a, sent_a = await session_a.send_async(
            "approval.resolve", {"approval_id": approval_id, "decision": "allow"})
        req_b, sent_b = await session_b.send_async(
            "approval.resolve", {"approval_id": approval_id, "decision": "deny"})
        log["race"]["concurrent_spread_ms"] = round(abs(sent_b - sent_a) * 1000, 3)

        outcomes = []
        for label, session, request_id in (("allow", session_a, req_a), ("deny", session_b, req_b)):
            try:
                result = await session.wait_response(request_id, timeout=30)
                outcomes.append({"decision": label, "accepted": True, "result": result})
            except HarnessError as exc:
                outcomes.append({"decision": label, "accepted": False,
                                 "error": {"code": exc.code, "message": exc.message,
                                           "details": exc.details}})
        log["race"]["outcomes"] = outcomes

        winners = [o for o in outcomes if o["accepted"]]
        losers = [o for o in outcomes if not o["accepted"]]
        log["race"]["winner_count"] = len(winners)
        log["race"]["loser_codes"] = [o["error"]["code"] for o in losers]
        if losers:
            details = losers[0]["error"].get("details") or {}
            log["race"]["loser_details"] = details
            log["race"]["loser_carries_winner_terminal_state"] = bool(
                details.get("decision")
            ) and details.get("decision") == (
                winners[0]["result"].get("decision") if winners else None
            )

        # 重放：与生效方相同的裁决再来一次
        replay = None
        try:
            await session_a.call(
                "approval.resolve", {"approval_id": approval_id, "decision": "allow"}, timeout=30)
            replay = {"accepted": True}
        except HarnessError as exc:
            replay = {"accepted": False, "code": exc.code, "message": exc.message,
                      "details": exc.details}
        log["race"]["replay"] = replay

        after = await session_a.call("app.bootstrap", timeout=30)
        log["race"]["pending_after"] = len(after.get("approvals") or [])
        log["race"]["conversation_still_pending"] = any(
            a.get("conversation_id") == target.get("conversation_id")
            for a in (after.get("approvals") or [])
        )
        # 副作用只发生一次：路径指向的文件要么不存在（deny 生效）要么唯一存在（allow 生效）
        paths = (target.get("operation") or {}).get("paths") or []
        log["race"]["side_effects"] = [
            {"path": p, "exists": Path(p).exists(),
             "content": Path(p).read_text(encoding="utf-8", errors="replace") if Path(p).exists() else None}
            for p in paths
        ]
    finally:
        await session_a.close()
        await session_b.close()


async def phase_timeout(out: Path, token: str, log: dict) -> None:
    """真实 600 秒超时。"""
    session = Harness(WS_URL, token, frames_log=out / "ws-frames-timeout.log",
                      events_log=out / "events-timeout.log", device_name="s4-a12-timeout")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        projects = bootstrap.get("projects") or []
        project = next(p for p in projects if p.get("name") == "project-alpha")
        project_id = project["project_id"]
        existing = next((c for p in projects for c in (p.get("conversations") or [])
                         if c.get("title") == "A12-approval-timeout"), None)
        if existing is not None:
            conversation_id = existing["conversation_id"]
        else:
            created = await session.call(
                "conversation.create",
                {"project_id": project_id, "pair_id": "phainon_ancient_machine",
                 "title": "A12-approval-timeout"}, timeout=30)
            conversation_id = created["current_conversation_id"]
        await session.call("conversation.set_mode",
                           {"conversation_id": conversation_id, "mode": "collaboration"}, timeout=30)
        await session.call(
            "chat.submit",
            {"conversation_id": conversation_id, "target": "assistant",
             "text": "请让神秘的古代机械在项目根目录新建文件 a12-timeout.md，"
                     "内容写一行：S4-A12-审批超时挂机样本。写完后回报结果。"},
            timeout=60)

        requested = await session.wait_event(
            "approval.requested", timeout=300,
            predicate=lambda e: event_fields(e).get("conversation_id") == conversation_id)
        fields = event_fields(requested)
        approval_id = fields.get("approval_id")
        anchored_at = time.monotonic()
        anchor_ts = now_iso()
        log["timeout"] = {
            "approval_id": approval_id,
            "conversation_id": conversation_id,
            "task_id": fields.get("task_id"),
            "operation": fields.get("operation"),
            "anchored_at": anchor_ts,
            "timeout_constant_s": APPROVAL_TIMEOUT_S,
            "configurable": False,
        }
        print(json.dumps({"phase": "T", "approval_id": approval_id,
                          "anchored_at": anchor_ts,
                          "waiting_s": APPROVAL_TIMEOUT_S}, ensure_ascii=False), flush=True)

        resolved = await session.wait_event(
            "approval.resolved", timeout=APPROVAL_TIMEOUT_S + 240,
            predicate=lambda e: event_fields(e).get("approval_id") == approval_id)
        resolved_fields = event_fields(resolved)
        log["timeout"]["waited_s"] = round(time.monotonic() - anchored_at, 3)
        log["timeout"]["resolved"] = {
            "decision": resolved_fields.get("decision"),
            "resolved_by": resolved_fields.get("resolved_by"),
            "actor": resolved_fields.get("actor"),
            "reason": resolved_fields.get("reason"),
            "error_code": resolved_fields.get("error_code"),
            "resolved_at": now_iso(),
        }

        late = None
        try:
            await session.call("approval.resolve",
                               {"approval_id": approval_id, "decision": "allow"}, timeout=30)
            late = {"accepted": True}
        except HarnessError as exc:
            late = {"accepted": False, "code": exc.code, "message": exc.message,
                    "details": exc.details}
        log["timeout"]["late_decision"] = late

        await asyncio.sleep(15)
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=60)
        log["timeout"]["conversation_after"] = {
            "active_task": snapshot.get("active_task"),
            "queue_items": snapshot.get("queue_items"),
            "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                          "status": m.get("status"), "text": str(m.get("text"))[:90]}
                         for m in snapshot.get("messages", [])],
        }
        after = await session.call("app.bootstrap", timeout=30)
        log["timeout"]["pending_after"] = len(after.get("approvals") or [])
    finally:
        await session.close()


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    await phase_race(out, token, log)
    await phase_timeout(out, token, log)
    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    (out / "a12-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a12.py",
        "# 本脚本挂机等待真实 600 秒审批超时；token 见 .tmp/s4-token.txt（不入库）",
    ])
    write_http_log(out / "http.log", "A12 全部业务交互走 WS 帧；无独立 HTTP 业务请求")
    print("A12 finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
