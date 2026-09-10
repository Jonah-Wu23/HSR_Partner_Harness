"""V039-S4-001 复验：只读查询载荷可序列化（metrics / summary / memory）。

上一批次失败现象：`metrics.query` 与 `summary.get` 整条读取失败——一旦存在
摘要记录，`summary.get` 即 30 秒无响应（服务端 response 不可序列化被静默丢弃，
调用方只能等到 backend_timeout）。

本轮复验：
1. `metrics.query` 能读回真实回合指标，时间戳为 ISO 8601 文本；
2. 存在摘要记录时 `summary.get` 能读回（不再 30 秒超时），content 解析回对象；
3. `memory.list` 同样可读回（写入链路由 V039-S4-003 覆盖）；
4. 空会话的 `summary.get` 正常返回空数组。

摘要用**条数阈值**触发（80 条未压缩消息）：前 79 条提交后立即取消，
第 80 条走一次真实模型回合，避免 402 KB 级输入的额外成本。
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

CASE = "V039-S4-001"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-project"
PAIR_A = "phainon_ancient_machine"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ISO_HINT = ("created_at", "updated_at", "started_at", "finished_at")


async def safe(session: Harness, method: str, params: dict, timeout: float = 35.0) -> dict:
    """只读命令容错：服务端不回响应时如实记录，不当作成功。"""
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:400],
                "details": exc.details}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout",
                "note": f"{method} 无响应（疑似响应体不可序列化）"}


def timestamp_shape(payload: object) -> dict:
    """统计载荷里时间戳字段的形态（ISO 文本 / null / 其他类型）。"""
    found: dict = {}
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key in ISO_HINT:
                    if value is None:
                        found.setdefault("null", []).append(key)
                    elif isinstance(value, str):
                        found.setdefault("iso_text", []).append(f"{key}={value[:32]}")
                    else:
                        found.setdefault("other", []).append(f"{key}={type(value).__name__}")
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return found


async def wait_idle(session: Harness, conversation_id: str, timeout: float = 120.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    snapshot: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        if not snapshot.get("active_task") and not snapshot.get("queue_items"):
            return snapshot
        await asyncio.sleep(0.5)
    return snapshot


async def main() -> int:
    out = case_dir(CASE)
    result = result_shell(CASE, title="只读查询载荷序列化（metrics/summary/memory）复验")
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="r1-001")
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
        conversation = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A, "title": "R1-001-protocol"},
            timeout=30)
        conversation_id = conversation["current_conversation_id"]
        log["ids"] = {"project_id": project_id, "conversation_id": conversation_id}

        # 1. 用条数阈值触发真实摘要：80 条未压缩消息
        payload = json.loads((FIXTURES / "fix-b2-count-only.json").read_text(encoding="utf-8"))
        messages = payload["sets"]["chat1"]
        log["summary_phase"] = {
            "fixture": "fix-b2-count-only.json",
            "fixture_messages": len(messages),
            "fixture_total_bytes": payload.get("total_bytes"),
            "plan": "前 79 条提交后 task.cancel；第 80 条走真实模型完整回合",
            "submits": [],
        }
        for index, text in enumerate(messages):
            last = index == len(messages) - 1
            submitted = await session.call("chat.submit", {
                "conversation_id": conversation_id, "target": "character", "text": text},
                timeout=60)
            record = {"index": index, "real_turn": last,
                      "message_id": (submitted or {}).get("message_id")}
            if not last:
                try:
                    await session.call("task.cancel", {"conversation_id": conversation_id},
                                       timeout=60)
                    await wait_idle(session, conversation_id, timeout=45)
                    record["cancelled"] = True
                except Exception as exc:  # noqa: BLE001 - 取消失败如实记录
                    record["cancelled"] = False
                    record["cancel_error"] = f"{type(exc).__name__}: {exc}"
            log["summary_phase"]["submits"].append(record)
            if index % 20 == 0 or last:
                print(f"submitted {index + 1}/{len(messages)} last={last}", flush=True)
            if not last:
                await asyncio.sleep(0.05)

        try:
            envelope = await session.wait_event(
                "summary.started", timeout=240,
                predicate=lambda e: event_fields(e).get("conversation_id") == conversation_id)
            log["summary_phase"]["started_event"] = event_fields(envelope)
        except asyncio.TimeoutError:
            log["summary_phase"]["started_event"] = {"__timeout__": True}
        try:
            envelope = await session.wait_event(
                "summary.completed", timeout=420,
                predicate=lambda e: event_fields(e).get("conversation_id") == conversation_id)
            log["summary_phase"]["terminal_event"] = {
                "event": "summary.completed", **event_fields(envelope)}
        except asyncio.TimeoutError:
            try:
                envelope = await session.wait_event(
                    "summary.failed", timeout=60,
                    predicate=lambda e: event_fields(e).get("conversation_id") == conversation_id)
                log["summary_phase"]["terminal_event"] = {
                    "event": "summary.failed", **event_fields(envelope)}
            except asyncio.TimeoutError:
                log["summary_phase"]["terminal_event"] = {"__timeout__": True}

        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=60)
        log["conversation_after"] = {
            "message_count": len(snapshot.get("messages", [])),
            "fixture_messages_present": sum(
                1 for m in snapshot.get("messages", [])
                if str(m.get("text") or "").startswith("FIXTURE-PINOCONY-SMALL")),
            "timestamp_shape": timestamp_shape(snapshot),
        }

        # 2. summary.get：上一批「一旦存在摘要记录即 30 秒超时」
        summary_get = await safe(session, "summary.get", {"conversation_id": conversation_id})
        summaries = (summary_get.get("result") or {}).get("summaries") or []
        log["summary_get"] = {
            "ok": summary_get.get("ok"),
            "code": summary_get.get("code"),
            "note": summary_get.get("note") or summary_get.get("message"),
            "count": len(summaries),
            "statuses": [s.get("status") for s in summaries],
            "timestamp_shape": timestamp_shape(summaries),
            "has_content_object": [isinstance(s.get("content"), dict) for s in summaries],
            "provider_model": [(s.get("provider"), s.get("model")) for s in summaries],
            "covers_message_count": [s.get("covers_message_count") for s in summaries],
        }

        # 3. metrics.query
        metrics = await safe(session, "metrics.query",
                             {"conversation_id": conversation_id, "limit": 30})
        metric_items = (metrics.get("result") or {}).get("metrics") or []
        log["metrics_query"] = {
            "ok": metrics.get("ok"),
            "code": metrics.get("code"),
            "note": metrics.get("note") or metrics.get("message"),
            "record_count": len(metric_items),
            "timestamp_shape": timestamp_shape(metrics.get("result")),
            "sample": metric_items[0] if metric_items else None,
        }

        # 4. memory.list（读取链路的同口径核对）
        memory = await safe(session, "memory.list", {"conversation_id": conversation_id})
        log["memory_list"] = {
            "ok": memory.get("ok"), "code": memory.get("code"),
            "count": len((memory.get("result") or {}).get("memories") or []),
            "timestamp_shape": timestamp_shape(memory.get("result")),
        }

        # 5. 空会话必须正常返回空数组（不是超时）
        empty = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A, "title": "R1-001-empty"}, timeout=30)
        empty_get = await safe(session, "summary.get",
                               {"conversation_id": empty["current_conversation_id"]})
        log["empty_summary_get"] = {
            "ok": empty_get.get("ok"),
            "count": len((empty_get.get("result") or {}).get("summaries") or []),
            "code": empty_get.get("code"),
        }
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        write_info_log(CASE, (out / "sidecar.log").read_text(encoding="utf-8").splitlines())
    except OSError:
        pass
    (out / "protocol-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "V039-S4-001 全部交互走 WS 帧；含真实模型回合与摘要")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_001_protocol.py",
    ])
    result["status"] = "待判定"
    result["actual"] = json.dumps({
        "summary_get": log["summary_get"], "metrics_query": log["metrics_query"],
        "memory_list": log["memory_list"], "empty_summary_get": log["empty_summary_get"]},
        ensure_ascii=False)[:4000]
    result["timestamps"]["finished_at"] = now_iso()
    result["evidence"] = ["protocol-run.json", "ws-frames.log", "events.log",
                          "sidecar.log", "sidecar-info.log"]
    save_result(CASE, result)
    print(json.dumps(log, ensure_ascii=False, indent=2)[:5000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
