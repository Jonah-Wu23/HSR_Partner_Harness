"""A02：压缩触发、真实摘要、保留最近 12 条与原文永久保存（协议级）。

阶段 1（字节阈值）：夹具 fix-a（402,315 B）作为一条消息正文提交，
  单条即超 256 KiB，直接触发正文阈值。
阶段 2（条数阈值）：夹具 fix-b2（80 条 × 约 1 KB，合计 77,246 B < 256 KiB），
  前 79 条提交后立即取消（不产生 79 轮真实模型往返），第 80 条走真实模型完整回合，
  由真实回合的消息落库触发"条数 ≥ 80"。
阶段 3（重启恢复）：见 run_a02_restart.py，需真实重启候选后再核对。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
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

CASE = "A02"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


async def wait_event_fields(session: Harness, name: str, predicate, timeout: float) -> dict:
    try:
        envelope = await session.wait_event(name, timeout=timeout, predicate=predicate)
        return event_fields(envelope)
    except asyncio.TimeoutError:
        return {"__timeout__": name}


async def wait_idle(session: Harness, conversation_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    snapshot: dict = {}
    while time.monotonic() < deadline:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        if not snapshot.get("active_task") and not snapshot.get("queue_items"):
            return snapshot
        await asyncio.sleep(0.5)
    return snapshot


async def safe_call(session: Harness, method: str, params: dict, timeout: float = 35.0) -> dict:
    """只读命令容错：服务端不回响应（响应体不可序列化）时如实记录，不当作成功。"""
    try:
        result = await session.call(method, params, timeout=timeout)
        return {"ok": True, "result": result}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout",
                "note": f"{method} 无响应：疑似响应体不可序列化（见 sidecar.log 的 ProtocolError）"}
    except Exception as exc:  # noqa: BLE001 - 协议错误如实记录
        return {"ok": False, "code": type(exc).__name__, "message": str(exc)}


async def create_conversation(session: Harness, project_id: str, pair_id: str, title: str) -> str:
    created = await session.call(
        "conversation.create",
        {"project_id": project_id, "pair_id": pair_id, "title": title}, timeout=30)
    return created["current_conversation_id"]


async def phase_bytes(session: Harness, project_id: str, log: dict) -> str:
    text = (FIXTURES / "fix-a-single-msg.txt").read_text(encoding="utf-8")
    conversation_id = await create_conversation(
        session, project_id, "phainon_ancient_machine", "A02-bytes")
    log["phase_bytes"] = {
        "conversation_id": conversation_id,
        "fixture": "fix-a-single-msg.txt",
        "fixture_bytes": len(text.encode("utf-8")),
        "submit_at": now_iso(),
    }
    await session.call(
        "chat.submit",
        {"conversation_id": conversation_id, "target": "character", "text": text},
        timeout=90)
    started = await wait_event_fields(
        session, "summary.started",
        lambda e: event_fields(e).get("conversation_id") == conversation_id, 300)
    log["phase_bytes"]["summary_started"] = started
    completed = await wait_event_fields(
        session, "summary.completed",
        lambda e: event_fields(e).get("conversation_id") == conversation_id, 600)
    if "__timeout__" in completed:
        completed = await wait_event_fields(
            session, "summary.failed",
            lambda e: event_fields(e).get("conversation_id") == conversation_id, 60)
    log["phase_bytes"]["summary_terminal"] = completed
    log["phase_bytes"]["summary_get"] = await safe_call(
        session, "summary.get", {"conversation_id": conversation_id})
    snapshot = await session.call("conversation.open",
                                  {"conversation_id": conversation_id}, timeout=60)
    user_texts = [str(m.get("text", "")) for m in snapshot.get("messages", [])
                  if m.get("source") == "user"]
    log["phase_bytes"]["conversation_after"] = {
        "message_count": len(snapshot.get("messages", [])),
        "user_message_count": len(user_texts),
        "original_text_lengths": [len(t) for t in user_texts],
        "original_text_preserved": any(len(t) == len(text) for t in user_texts),
        "character_finals": [m.get("text") for m in snapshot.get("messages", [])
                             if m.get("source") == "character" and m.get("status") == "done"],
    }
    print("phase_bytes summary:", json.dumps(
        {k: log["phase_bytes"][k] for k in ("summary_started", "summary_terminal")},
        ensure_ascii=False)[:800], flush=True)
    return conversation_id


async def phase_count(session: Harness, project_id: str, log: dict) -> str:
    payload = json.loads((FIXTURES / "fix-b2-count-only.json").read_text(encoding="utf-8"))
    messages = payload["sets"]["chat1"]
    conversation_id = await create_conversation(
        session, project_id, "phainon_ancient_machine", "A02-count")
    log["phase_count"] = {
        "conversation_id": conversation_id,
        "fixture": "fix-b2-count-only.json",
        "fixture_messages": len(messages),
        "fixture_total_bytes": payload["total_bytes"],
        "submit_plan": "前 79 条提交后立即 task.cancel；第 80 条走真实模型完整回合",
        "submits": [],
    }
    for index, message in enumerate(messages):
        last = index == len(messages) - 1
        submitted = await session.call(
            "chat.submit",
            {"conversation_id": conversation_id, "target": "character", "text": message},
            timeout=60)
        record = {"index": index, "at": now_iso(),
                  "message_id": submitted.get("message_id") if isinstance(submitted, dict) else None,
                  "real_turn": last}
        if not last:
            try:
                await session.call("task.cancel",
                                   {"conversation_id": conversation_id}, timeout=60)
                await wait_idle(session, conversation_id, timeout=45)
                record["cancelled"] = True
            except Exception as exc:  # noqa: BLE001 - 取消失败如实记录
                record["cancelled"] = False
                record["cancel_error"] = f"{type(exc).__name__}: {exc}"
        log["phase_count"]["submits"].append(record)
        if index % 10 == 0 or last:
            print(f"submitted {index + 1}/{len(messages)} last={last}", flush=True)
        if not last:
            await asyncio.sleep(0.1)

    started = await wait_event_fields(
        session, "summary.started",
        lambda e: event_fields(e).get("conversation_id") == conversation_id, 300)
    log["phase_count"]["summary_started"] = started
    completed = await wait_event_fields(
        session, "summary.completed",
        lambda e: event_fields(e).get("conversation_id") == conversation_id, 600)
    if "__timeout__" in completed:
        completed = await wait_event_fields(
            session, "summary.failed",
            lambda e: event_fields(e).get("conversation_id") == conversation_id, 60)
    log["phase_count"]["summary_terminal"] = completed
    log["phase_count"]["summary_get"] = await safe_call(
        session, "summary.get", {"conversation_id": conversation_id})
    snapshot = await session.call("conversation.open",
                                  {"conversation_id": conversation_id}, timeout=60)
    texts = [str(m.get("text", "")) for m in snapshot.get("messages", [])]
    log["phase_count"]["conversation_after"] = {
        "message_count": len(snapshot.get("messages", [])),
        "fixture_messages_present": sum(1 for t in texts if t.startswith("FIXTURE-PINOCONY-SMALL")),
        "character_finals": [m.get("text") for m in snapshot.get("messages", [])
                             if m.get("source") == "character" and m.get("status") == "done"],
    }
    print("phase_count summary:", json.dumps(
        {k: log["phase_count"][k] for k in ("summary_started", "summary_terminal")},
        ensure_ascii=False)[:800], flush=True)
    return conversation_id


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="s4-a02")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next(p for p in (bootstrap.get("projects") or [])
                       if p.get("name") == "project-alpha")
        log["bytes_conversation"] = await phase_bytes(session, project["project_id"], log)
        log["count_conversation"] = await phase_count(session, project["project_id"], log)
    finally:
        await session.close()
    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    (out / "a02-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a02.py",
    ])
    write_http_log(out / "http.log", "A02 全部业务交互走 WS 帧")
    print("A02 finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
