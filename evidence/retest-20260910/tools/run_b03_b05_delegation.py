"""B-03 正向验证 + B-05 子项复测：Chat Completions 端点上的真实委派全链路。

两个复测对象在**同一次真实委派回合**上成交（复测计划 §5 与 §6）：

B-03 正向：以 DeepSeek（Chat Completions）为唯一真实供应商跑通
  角色自然语言 → 结构化委派 → 多轮工具 → 真实审批 → 文件落盘 → 助手结果摘要 → 角色终局回复，
  并断言全链路成功后不出现终态错误（覆盖 V039-S4-009）。

B-05 混合时间线：会话绑定 fix-c（85 条世界书，正文 129,992 B）后重跑一个回合，
  核对同一回合内同时成立 4 类以上时间线（用户消息 / 角色发言 / 助手自然语言 / 工具记录，含思考条目）
  与世界书激活；并按 §6.4 导出**完整消息载荷**（含 payload.reasoning）以判定 V039-S4-008。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ph_client import Harness, HarnessError, event_fields, now_iso
from r1common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell,
)

CASE_B03 = "B-03"
CASE_B05 = "B-05"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-project"
PAIR_A = "phainon_ancient_machine"
TARGET_FILE = "r1-b05-delegation.md"
TARGET_CONTENT = "S4-R1 B-05 混合时间线：由助手在真实委派中创建。"


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
    """按到达顺序逐一放行本会话的审批，直到终局或超时。"""
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
    out03 = case_dir(CASE_B03)
    out05 = case_dir(CASE_B05)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out05 / "ws-frames.log",
                      events_log=out05 / "events.log", device_name="r1-b03b05")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next((p for p in (bootstrap.get("projects") or [])
                        if p.get("root_path", "").endswith("retest-project")), None)
        if project is None:
            created = await session.call("project.create", {
                "root_path": PROJECT_ROOT, "name": "retest-project", "pair_id": PAIR_A},
                timeout=30)
            project = next(p for p in created["projects"] if p.get("name") == "retest-project")
        project_id = project["project_id"]

        # fix-c 卡（85 条世界书）：优先复用 017 导入的卡，否则重新导入
        cards = await session.call("card.list", {"include_archived": True}, timeout=30)
        card_id = next(
            (c.get("card_id") for c in ((cards.get("result") or {}).get("cards") or [])
             if "fix-c" in str(c.get("name", "")).lower()
             or str(c.get("name", "")).startswith("PINOCONY")), None)
        if card_id is None:
            imported = await safe(session, "card.import_json",
                                  {"path": str(FIXTURES / "fix-c-worldbook-card.json")})
            card_id = (imported.get("result") or {}).get("card_id")
        log["card_id"] = card_id
        log["card_choice"] = [{"card_id": c.get("card_id"), "name": c.get("name")}
                              for c in ((cards.get("result") or {}).get("cards") or [])]

        conversation = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A,
            "title": "R1-B05-delegation", "character_card_id": card_id}, timeout=30)
        conversation_id = conversation["current_conversation_id"]
        log["conversation_id"] = conversation_id

        # 世界书激活基线（回合前）
        before = await safe(session, "diagnostics.prompt_assembly",
                            {"conversation_id": conversation_id})
        log["assembly_before"] = {
            "module_count": len((before.get("result") or {}).get("modules") or []),
            "diagnostics": (before.get("result") or {}).get("diagnostics"),
        }

        # 协作模式 + 真实委派
        await session.call("conversation.set_mode",
                           {"conversation_id": conversation_id, "mode": "collaboration"},
                           timeout=30)
        submit = await safe(session, "chat.submit", {
            "conversation_id": conversation_id, "target": "assistant",
            "text": (f"请让助手在项目根目录创建文件 {TARGET_FILE}，"
                     f"内容写一行：{TARGET_CONTENT}。创建后回读校验并把结果告诉角色。")},
            timeout=60)
        log["submit"] = submit
        log["approvals"] = await resolve_all_approvals(session, conversation_id, 420.0)

        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=60)
        # 完整消息载荷（含 payload / channel）—— V039-S4-008 的判定依据
        messages_full = [
            {"message_id": m.get("message_id"), "source": m.get("source"),
             "kind": m.get("kind"), "status": m.get("status"),
             "text": str(m.get("text") or ""),
             "tts_eligible": m.get("tts_eligible"),
             "keys": sorted(m.keys()),
             "payload": m.get("payload")}
            for m in snapshot.get("messages", [])
        ]
        (out05 / "messages-full.json").write_text(
            json.dumps(messages_full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        kinds = sorted({str(m.get("kind")) for m in snapshot.get("messages", [])})
        sources = sorted({str(m.get("source")) for m in snapshot.get("messages", [])})
        reasoning_messages = [
            m for m in messages_full
            if isinstance(m.get("payload"), dict)
            and str(m.get("payload", {}).get("reasoning") or "").strip()]
        empty_text_messages = [m for m in messages_full if not m["text"].strip()]

        log["mixed_timeline"] = {
            "kinds": kinds,
            "sources": sources,
            "kind_count": len(kinds),
            "message_count": len(messages_full),
            "tool_runs": [{"tool_call_id": t.get("tool_call_id"), "status": t.get("status"),
                           "tool_name": t.get("tool_name") or t.get("name")}
                          for t in snapshot.get("tool_runs", [])],
            "tool_run_count": len(snapshot.get("tool_runs", [])),
            "messages": [{"source": m["source"], "kind": m["kind"], "status": m["status"],
                          "chars": len(m["text"]), "text": m["text"][:120]}
                         for m in messages_full],
        }
        log["s4_008_check"] = {
            "question": "空 text 的条目是否为 reasoning-only 的段",
            "empty_text_count": len(empty_text_messages),
            "empty_text_messages": [
                {"source": m["source"], "kind": m["kind"], "status": m["status"],
                 "has_payload": isinstance(m.get("payload"), dict),
                 "payload_keys": sorted((m.get("payload") or {}).keys())
                 if isinstance(m.get("payload"), dict) else None,
                 "reasoning_chars": len(str((m.get("payload") or {}).get("reasoning") or ""))
                 if isinstance(m.get("payload"), dict) else None}
                for m in empty_text_messages],
            "messages_with_reasoning": len(reasoning_messages),
            "reasoning_sample": [
                {"kind": m["kind"], "reasoning_chars": len(str(m["payload"]["reasoning"]))}
                for m in reasoning_messages[:5]],
        }
        log["s4_009_check"] = {
            "question": "全链路成功后是否出现终态错误",
            "terminal_errors": [
                {"source": m["source"], "kind": m["kind"], "status": m["status"],
                 "text": m["text"][:300]}
                for m in messages_full
                if "失败" in m["text"] or m["status"] == "failed"],
            "active_task": bool(snapshot.get("active_task")),
            "queue_items": len(snapshot.get("queue_items") or []),
        }

        # 世界书激活（回合后）
        after = await safe(session, "diagnostics.prompt_assembly",
                           {"conversation_id": conversation_id})
        hidden = await safe(session, "diagnostics.prompt_assembly",
                            {"conversation_id": conversation_id, "include_hidden": True})
        after_result = after.get("result") or {}
        log["assembly_after"] = {
            "reason": after_result.get("reason"),
            "module_count": len(after_result.get("modules") or []),
            "module_names": [m.get("name") for m in (after_result.get("modules") or [])],
            "budget_lines": [d for d in (after_result.get("diagnostics") or [])
                             if "budget" in d or "overflow" in d or "warnings" in d],
            "hidden_chars_total": sum(
                len(str(m.get("hidden_content") or ""))
                for m in ((hidden.get("result") or {}).get("modules") or [])),
        }

        # 文件落盘验证
        target = Path(PROJECT_ROOT) / TARGET_FILE
        log["file_check"] = {
            "path": str(target),
            "exists": target.exists(),
            "bytes": target.stat().st_size if target.exists() else None,
            "content": target.read_text(encoding="utf-8")[:200] if target.exists() else None,
        }
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out05 / "sidecar.log")
    try:
        write_info_log(CASE_B05, (out05 / "sidecar.log").read_text(
            encoding="utf-8").splitlines())
    except OSError:
        pass
    (out05 / "delegation-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out03 / "delegation-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out05 / "http.log", "B-03/B-05 全部交互走 WS 帧；真实委派与审批")
    write_commands(out05 / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_b03_b05_delegation.py",
    ])
    print(json.dumps({k: log[k] for k in
                      ("card_id", "conversation_id", "approvals", "mixed_timeline",
                       "s4_008_check", "s4_009_check", "file_check")},
                     ensure_ascii=False, indent=2)[:6000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
