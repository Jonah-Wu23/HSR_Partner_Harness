"""A01：协议级四会话并发提交 + 排队 + 取消 + 审批归属。

不使用 GUI 顺序点击：四条 chat.submit 由四个独立 WS 会话（同一真实 token）
几乎同时发出，测量 submitted_at 最大差值；随后分别验证事件/消息/终态归属，
再在同一会话内制造排队，并在协作会话里制造审批与取消。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from ph_client import Harness, HarnessError, now_iso
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
PAIRS = (
    ("phainon_ancient_machine", "A01-conv-1"),
    ("march7_fourth_mirror", "A01-conv-2"),
    ("firefly_sam", "A01-conv-3"),
    ("phainon_ancient_machine", "A01-conv-4"),
)
MARKERS = {
    "A01-conv-1": "A01-MARKER-CONV1 只回复一个词：壹",
    "A01-conv-2": "A01-MARKER-CONV2 只回复一个词：贰",
    "A01-conv-3": "A01-MARKER-CONV3 只回复一个词：叁",
    "A01-conv-4": "A01-MARKER-CONV4 只回复一个词：肆",
}


async def settle(h: Harness, conversation_id: str, timeout: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout
    snapshot = {}
    while time.monotonic() < deadline:
        snapshot = await h.call(
            "conversation.open", {"conversation_id": conversation_id}, timeout=30
        )
        pending = [
            m
            for m in snapshot.get("messages", [])
            if m.get("status") in {"pending", "streaming", "processing"}
        ]
        if not pending and not snapshot.get("active_task") and not snapshot.get("queue_items"):
            return snapshot
        await asyncio.sleep(1.0)
    return snapshot


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"steps": [], "evidence": {}}

    def note(step: str, **fields: object) -> None:
        record = {"ts": now_iso(), **fields}
        log["steps"].append({"step": step, **record})
        print(json.dumps({"step": step, **record}, ensure_ascii=False), flush=True)

    sessions = [Harness(WS_URL, token, device_name=f"s4-a01-s{i}") for i in range(4)]
    observer = Harness(
        WS_URL, token, frames_log=out / "ws-frames.log",
        events_log=out / "events.log", device_name="s4-a01-observer",
    )
    for s in sessions:
        await s.connect()
    await observer.connect()

    try:
        bootstrap = await observer.call("app.bootstrap", timeout=30)
        projects = bootstrap.get("projects") or []
        project = next(p for p in projects if p.get("name") == "project-alpha")
        project_id = project["project_id"]

        conversations: dict[str, str] = {}
        for pair_id, title in PAIRS:
            existing = next(
                (
                    c
                    for c in (project.get("conversations") or [])
                    if c.get("title") == title
                ),
                None,
            )
            if existing is not None:
                conversations[title] = existing["conversation_id"]
                continue
            created = await observer.call(
                "conversation.create",
                {"project_id": project_id, "pair_id": pair_id, "title": title},
                timeout=30,
            )
            conversations[title] = created["current_conversation_id"]
        note("conversations", project_id=project_id, conversations=conversations)

        # —— 四会话并发提交 ——
        sends = []
        for index, (pair_id, title) in enumerate(PAIRS):
            conversation_id = conversations[title]
            request_id, sent = await sessions[index].send_async(
                "chat.submit",
                {
                    "conversation_id": conversation_id,
                    "target": "character",
                    "text": MARKERS[title],
                },
            )
            sends.append({"title": title, "conversation_id": conversation_id,
                          "pair_id": pair_id, "request_id": request_id, "sent_mono": sent,
                          "sent_ts": now_iso()})
        spread = max(item["sent_mono"] for item in sends) - min(
            item["sent_mono"] for item in sends
        )
        log["evidence"]["submit_spread_s"] = round(spread, 6)
        for item in sends:
            item["spread_from_first_ms"] = round((item["sent_mono"] - min(s["sent_mono"] for s in sends)) * 1000, 3)
        note("four_session_submit", spread_seconds=round(spread, 6),
             sends=[{k: v for k, v in item.items() if k != "sent_mono"} for item in sends])

        acceptances = []
        for index, item in enumerate(sends):
            try:
                result = await sessions[index].wait_response(item["request_id"], timeout=60)
                item["accepted"] = True
                item["message_id"] = result.get("message_id") if isinstance(result, dict) else None
            except HarnessError as exc:
                item["accepted"] = False
                item["error"] = {"code": exc.code, "message": exc.message}
            except asyncio.TimeoutError:
                item["accepted"] = False
                item["error"] = {"code": "client_timeout"}
            acceptances.append(item)
        note("submit_acceptances", acceptances=[
            {k: v for k, v in item.items() if k != "sent_mono"} for item in acceptances
        ])

        # —— 等待四会话各自终态并核对归属 ——
        attribution = {}
        for item in sends:
            snapshot = await settle(observer, item["conversation_id"], timeout=180)
            user_texts = [
                str(m.get("text", ""))
                for m in snapshot.get("messages", [])
                if m.get("source") == "user"
            ]
            character_texts = [
                str(m.get("text", ""))
                for m in snapshot.get("messages", [])
                if m.get("source") == "character"
            ]
            conversation = snapshot.get("conversation") or {}
            attribution[item["title"]] = {
                "conversation_id": item["conversation_id"],
                "pair_id": conversation.get("pair_id"),
                "user_texts": user_texts,
                "character_texts": character_texts,
                "other_markers_present": [
                    title
                    for title, marker in {
                        "A01-conv-1": "A01-MARKER-CONV1",
                        "A01-conv-2": "A01-MARKER-CONV2",
                        "A01-conv-3": "A01-MARKER-CONV3",
                        "A01-conv-4": "A01-MARKER-CONV4",
                    }.items()
                    if title != item["title"]
                    and any(marker in text for text in user_texts)
                ],
                "character_status": [
                    m.get("status")
                    for m in snapshot.get("messages", [])
                    if m.get("source") == "character"
                ],
            }
        log["evidence"]["attribution"] = attribution
        note("attribution", attribution=attribution)

        # —— 排队：同一会话连续两条 ——
        queue_title = "A01-conv-1"
        queue_conv = conversations[queue_title]
        _, first_sent = await observer.send_async(
            "chat.submit",
            {"conversation_id": queue_conv, "target": "character",
             "text": "A01-QUEUE-A 只回复一个词：甲"},
        )
        await asyncio.sleep(0.2)
        _, second_sent = await observer.send_async(
            "chat.submit",
            {"conversation_id": queue_conv, "target": "character",
             "text": "A01-QUEUE-B 只回复一个词：乙"},
        )
        queue_spread = abs(second_sent - first_sent)
        await asyncio.sleep(1.0)
        mid = await observer.call(
            "conversation.open", {"conversation_id": queue_conv}, timeout=30
        )
        queue_snapshot = {
            "queue_items": mid.get("queue_items"),
            "active_task": mid.get("active_task"),
            "busy": bool(mid.get("active_task")),
        }
        log["evidence"]["queue_at_submit_time"] = queue_snapshot
        note("queue_probe", gap_seconds=round(queue_spread, 3), **queue_snapshot)

        settled = await settle(observer, queue_conv, timeout=240)
        queue_user_texts = [
            str(m.get("text", ""))
            for m in settled.get("messages", [])
            if m.get("source") == "user"
        ]
        queue_character_texts = [
            str(m.get("text", ""))
            for m in settled.get("messages", [])
            if m.get("source") == "character"
        ]
        queue_result = {
            "user_texts": queue_user_texts,
            "character_texts": queue_character_texts,
            "order_ok": queue_user_texts.index("A01-QUEUE-A 只回复一个词：甲")
            < queue_user_texts.index("A01-QUEUE-B 只回复一个词：乙")
            if "A01-QUEUE-A 只回复一个词：甲" in queue_user_texts
            and "A01-QUEUE-B 只回复一个词：乙" in queue_user_texts
            else False,
            "remaining_queue_items": settled.get("queue_items"),
        }
        log["evidence"]["queue_result"] = queue_result
        note("queue_result", **queue_result)

        # —— 取消 + 审批归属：协作会话 ——
        cancel_title = "A01-conv-4"
        cancel_conv = conversations[cancel_title]
        await observer.call(
            "conversation.set_mode",
            {"conversation_id": cancel_conv, "mode": "collaboration"},
            timeout=30,
        )
        submitted = await observer.call(
            "chat.submit",
            {"conversation_id": cancel_conv, "target": "assistant",
             "text": "请让神秘的古代机械在项目根目录新建文件 a01-cancel.md，"
                     "内容写一行：S4-A01-取消样本。写完回报。"},
            timeout=60,
        )
        note("cancel_task_submitted", conversation_id=cancel_conv,
             message_id=submitted.get("message_id") if isinstance(submitted, dict) else None)

        approval_event = None
        try:
            approval_event = await observer.wait_event(
                "approval.requested",
                timeout=240,
                predicate=lambda e: e.get("conversation_id") == cancel_conv,
            )
        except asyncio.TimeoutError:
            note("approval_requested", status="timeout_waiting")
        if approval_event is not None:
            note("approval_requested", approval_id=approval_event.get("approval_id"),
                 conversation_id=approval_event.get("conversation_id"),
                 task_id=approval_event.get("task_id"),
                 operation=approval_event.get("operation"))

        cancel_result = await observer.call(
            "task.cancel", {"conversation_id": cancel_conv}, timeout=60
        )
        note("task_cancel", result=cancel_result if isinstance(cancel_result, (dict, list)) else str(cancel_result))

        cancelled = await settle(observer, cancel_conv, timeout=240)
        cancel_summary = {
            "active_task": cancelled.get("active_task"),
            "queue_items": cancelled.get("queue_items"),
            "messages": [
                {"source": m.get("source"), "kind": m.get("kind"),
                 "status": m.get("status"), "text": str(m.get("text"))[:100]}
                for m in cancelled.get("messages", [])
            ],
            "approvals_snapshot": (await observer.call("app.bootstrap", timeout=30)).get("approvals"),
        }
        log["evidence"]["cancel_result"] = cancel_summary
        note("cancel_result", active_task=cancel_summary["active_task"],
             approvals=cancel_summary["approvals_snapshot"])

    finally:
        for s in sessions:
            await s.close()
        await observer.close()

    new_lines = sidecar_tail(out / "sidecar.log")
    log["sidecar_new_lines"] = new_lines
    (out / "a01-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_commands(
        out / "commands.ps1",
        [
            "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
            "$env:PYTHONPATH=(Get-Location).Path",
            "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a01.py",
            "# 依赖：候选 EXE 以 --serve 8765 运行；token 见 .tmp/s4-token.txt（不入库）",
        ],
    )
    write_http_log(out / "http.log", "A01 全部业务交互走 WS 帧；无独立 HTTP 业务请求")
    print("A01 finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
