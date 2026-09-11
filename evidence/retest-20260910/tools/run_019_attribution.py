"""V039-S4-019 复测取证：空输出与重试的可归因性。

上一批次的取证缺口：`sidecar.log` 只保留 WARNING 及以上，导致
「输出不可用（empty）」的告警无法区分「重试后成功」与「直接失败」，
一次真实计费往返无法归因；且 `logger.info("抢占中断旧合成任务")` 被过滤掉。

本轮以 `PAIR_HARNESS_LOG_LEVEL=INFO` 启动，日志全量落盘（不过滤），并主动
构造一条「首次输出不可用 → 重试」的真实路径：沙盒在**第一次请求**的响应
传输中切断（cut_soon 单次），使首个输出形态不可用，随后自动恢复 forward，
让重试请求可达。

判据：
1. 未过滤日志里出现「输出不可用」告警，且携带可数信息（category、字符数）；
2. 出现「是否重试」的 INFO 归因（重试原因 / attempt / 是否放宽格式）；
3. 出现「最终输出来源」的 INFO 归因（首次请求 / 重试后成功 / 不再重试）；
4. 三种归因共同构成一次真实计费往返的完整解释链。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso
from r1common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell,
)

CASE = "V039-S4-019"
CONTROL = ("127.0.0.1", 8768)
PAIR_A = "phainon_ancient_machine"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-project"

SOURCE_MARKERS = ("回合输出来源", "重试真实模型", "不再重试", "输出不可用")


async def control(command: str) -> str:
    reader, writer = await asyncio.open_connection(*CONTROL)
    try:
        writer.write((command + "\n").encode())
        await writer.drain()
        return (await reader.readline()).decode().strip()
    finally:
        writer.close()


async def wait_turn(session: Harness, conversation_id: str, timeout: float = 180.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    snapshot: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        settled = [m for m in snapshot.get("messages", [])
                   if m.get("source") != "user"
                   and m.get("status") in {"done", "failed", "cancelled"}]
        if settled and not snapshot.get("active_task") and not snapshot.get("queue_items"):
            return snapshot
        await asyncio.sleep(1.0)
    return snapshot


async def main() -> int:
    out = case_dir(CASE)
    result = result_shell(CASE, title="空输出与重试的 INFO 级可数归因复验")
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="r1-019")
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

        # 场景 A：正常回合（首次请求即成功）——归因应说明来源为首次请求
        normal = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A, "title": "R1-019-normal"},
            timeout=30)
        log["normal_turn"] = {"conversation_id": normal["current_conversation_id"]}
        await session.call("chat.submit", {
            "conversation_id": normal["current_conversation_id"], "target": "character",
            "text": "复测 019：请只回复两个字：首发。"}, timeout=60)
        snapshot = await wait_turn(session, normal["current_conversation_id"], timeout=120)
        log["normal_turn"]["messages"] = [
            {"source": m.get("source"), "status": m.get("status"),
             "text": str(m.get("text") or "")[:80]}
            for m in snapshot.get("messages", [])]

        # 场景 B：首个响应被切断 → 输出不可用 → 重试
        await control("SET cut_soon 256")
        injected = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A, "title": "R1-019-retry"},
            timeout=30)
        conversation_id = injected["current_conversation_id"]
        log["retry_turn"] = {
            "conversation_id": conversation_id,
            "injection": "沙盒在首次响应传输 256 字节后切断（单次），随后自动恢复 forward",
            "control_reply": await control("PING"),
        }
        started = time.monotonic()
        await session.call("chat.submit", {
            "conversation_id": conversation_id, "target": "character",
            "text": "复测 019：请只回复两个字：重试。"}, timeout=60)
        snapshot = await wait_turn(session, conversation_id, timeout=180)
        log["retry_turn"]["elapsed_seconds"] = round(time.monotonic() - started, 2)
        log["retry_turn"]["messages"] = [
            {"source": m.get("source"), "kind": m.get("kind"), "status": m.get("status"),
             "text": str(m.get("text") or "")[:200]}
            for m in snapshot.get("messages", [])]
        await control("SET forward")
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        lines = (out / "sidecar.log").read_text(encoding="utf-8").splitlines()
        write_info_log(CASE, lines)
        log["attribution_lines"] = [line for line in lines
                                    if any(m in line for m in SOURCE_MARKERS)]
    except OSError:
        log["attribution_lines"] = []
    lines = log.get("attribution_lines") or []
    log["assertions"] = {
        "has_unusable_output_warning": any("输出不可用" in l for l in lines),
        "has_retry_decision_info": any(
            ("重试真实模型" in l) or ("不再重试" in l) for l in lines),
        "has_final_source_info": any("回合输出来源" in l for l in lines),
        "countable_fields_present": all(
            any(field in l for l in lines)
            for field in ("category=", "attempt=")),
    }
    (out / "attribution-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "V039-S4-019 全部交互走 WS 帧；含真实模型回合")
    write_commands(out / "commands.ps1", [
        "# Sidecar 必须以 INFO 级启动，否则本用例的归因日志不可观测",
        "$env:PAIR_HARNESS_LOG_LEVEL='INFO'",
        "python evidence/retest-20260910/tools/run_019_attribution.py",
    ])
    result["status"] = "待判定"
    result["actual"] = json.dumps({
        "assertions": log["assertions"],
        "attribution_lines": lines[:20]}, ensure_ascii=False)[:4000]
    result["timestamps"]["finished_at"] = now_iso()
    result["evidence"] = ["attribution-run.json", "ws-frames.log", "events.log",
                          "sidecar.log", "sidecar-info.log"]
    save_result(CASE, result)
    print(json.dumps(log, ensure_ascii=False, indent=2)[:5000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
