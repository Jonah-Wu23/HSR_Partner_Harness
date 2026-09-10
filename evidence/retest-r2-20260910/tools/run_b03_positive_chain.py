"""B-03 正向：Chat Completions 端点上跑通真实委派全链路（S4-R2 真机复测）。

复测计划 §5 的复测轨正向断言：
  角色自然语言 → 结构化委派 → 多轮工具 → 真实审批 → 文件落盘 → 助手结果摘要 → 角色终局回复，
并断言全链路成功后不出现终态错误（覆盖 V039-S4-009）。

S4-R2 改动了引擎装配（删除 Responses 校验、只保留 reasonix acp），因此这条
真实链路必须在真机上重跑，不得用 S4-R1 的结果替代。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ph_client import Harness, HarnessError, event_fields, now_iso
from r2common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell, build_block,
)

CASE = "B-03-positive"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\r2-chain-project"
PAIR_A = "phainon_ancient_machine"
TARGET_FILE = "r2-b03-chain.md"
TARGET_CONTENT = "S4-R2 B-03 正向：由助手在真实委派中创建。"


async def safe(session: Harness, method: str, params: dict, timeout: float = 60.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:300],
                "details": exc.details}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout"}


async def resolve_all_approvals(session: Harness, conversation_id: str,
                                deadline_seconds: float) -> list[dict]:
    handled: list[dict] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    while loop.time() < deadline:
        pending = [
            event_fields(e) for e in session.events
            if e.get("event") == "approval.requested"
            and event_fields(e).get("conversation_id") == conversation_id
            and event_fields(e).get("approval_id") not in {h["approval_id"] for h in handled}
        ]
        if pending:
            for item in pending:
                approval_id = item.get("approval_id")
                resolved = await safe(session, "approval.resolve",
                                      {"approval_id": approval_id, "decision": "allow"})
                handled.append({"approval_id": approval_id,
                                "command": item.get("command") or item.get("summary"),
                                "resolve": resolved})
                print(f"approved {approval_id}", flush=True)
            continue
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        if (not snapshot.get("active_task") and not snapshot.get("queue_items")
                and handled):
            await asyncio.sleep(3.0)
            snapshot = await session.call("conversation.open",
                                          {"conversation_id": conversation_id}, timeout=30)
            if not snapshot.get("active_task") and not snapshot.get("queue_items"):
                return handled
        await asyncio.sleep(2.0)
    return handled


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="r2-chain")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        log["account"] = bootstrap.get("current_account_id")
        log["config"] = await safe(session, "config.get", {})
        project = next((p for p in (bootstrap.get("projects") or [])
                        if p.get("root_path", "").endswith("r2-chain-project")), None)
        if project is None:
            created = await session.call("project.create", {
                "root_path": PROJECT_ROOT, "name": "r2-chain-project", "pair_id": PAIR_A},
                timeout=30)
            project = next(p for p in created["projects"]
                           if p.get("name") == "r2-chain-project")
        project_id = project["project_id"]
        Path(PROJECT_ROOT).mkdir(parents=True, exist_ok=True)
        target = Path(PROJECT_ROOT) / TARGET_FILE
        if target.exists():
            target.unlink()

        conversation = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A,
            "title": "R2-B03-positive"}, timeout=30)
        conversation_id = conversation["current_conversation_id"]
        log["conversation_id"] = conversation_id

        await session.call("conversation.set_mode",
                           {"conversation_id": conversation_id, "mode": "collaboration"},
                           timeout=30)
        log["submit"] = await safe(session, "chat.submit", {
            "conversation_id": conversation_id, "target": "assistant",
            "text": (f"请让助手在项目根目录创建文件 {TARGET_FILE}，"
                     f"内容写一行：{TARGET_CONTENT}。创建后回读校验并把结果告诉角色。")},
            timeout=60)
        log["approvals"] = await resolve_all_approvals(session, conversation_id, 420.0)

        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=60)
        messages = [
            {"source": m.get("source"), "kind": m.get("kind"), "status": m.get("status"),
             "chars": len(str(m.get("text") or "")), "text": str(m.get("text") or "")[:200]}
            for m in snapshot.get("messages", [])
        ]
        tool_runs = [
            {"tool_call_id": t.get("tool_call_id"), "status": t.get("status"),
             "tool_name": t.get("tool_name") or t.get("name")}
            for t in snapshot.get("tool_runs", [])
        ]
        log["timeline"] = {
            "sources": sorted({str(m["source"]) for m in messages}),
            "kinds": sorted({str(m["kind"]) for m in messages}),
            "messages": messages,
            "tool_runs": tool_runs,
            "tool_run_count": len(tool_runs),
        }
        log["terminal_state"] = {
            "failed_messages": [m for m in messages if m["status"] == "failed"],
            "failure_notices": [m["text"] for m in messages
                                if m["source"] == "system" and "失败" in m["text"]],
            "active_task": bool(snapshot.get("active_task")),
            "queue_items": len(snapshot.get("queue_items") or []),
        }
        log["file_check"] = {
            "path": str(target),
            "exists": target.exists(),
            "bytes": target.stat().st_size if target.exists() else None,
            "content": target.read_text(encoding="utf-8")[:200] if target.exists() else None,
        }
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        write_info_log(CASE, (out / "sidecar.log").read_text(
            encoding="utf-8").splitlines())
    except OSError:
        pass
    (out / "chain-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "B-03 正向：真实委派全链路走 WS 帧")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-r2-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_b03_positive_chain.py",
    ])
    r = result_shell(CASE, title="B-03 正向：Chat Completions 端点真实委派全链路")
    r["build"] = build_block()
    r["actual"] = json.dumps(log, ensure_ascii=False)[:20000]
    r["timestamps"]["finished_at"] = now_iso()
    r["evidence"] = ["chain-run.json", "ws-frames.log", "events.log",
                     "sidecar.log", "sidecar-info.log"]
    save_result(CASE, r)
    print(json.dumps({
        "conversation_id": log.get("conversation_id"),
        "approvals": log.get("approvals"),
        "timeline_sources": log["timeline"]["sources"],
        "timeline_kinds": log["timeline"]["kinds"],
        "tool_run_count": log["timeline"]["tool_run_count"],
        "terminal_state": log["terminal_state"],
        "file_check": log["file_check"],
    }, ensure_ascii=False, indent=2)[:8000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
