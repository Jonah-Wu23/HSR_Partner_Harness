"""V039-S4-018 复验：抢占与停止只产生「已中断」的正常收尾。

上一批次失败现象：正常抢占被上报成 ``voice.mobile_tts_failed``（报文为
「TTS 消息不存在」），把产品自身的抢占误报成供应商失败，直接污染了限流基线。

修复点：``mobile_audio.stop()`` 保留墓碑（上限 128），被回收条目在后续
``feed()`` / ``end()`` 抛 ``MobileTtsInterrupted``（``CancelledError`` 子类，属正常
中断），生产者按中断收尾，不广播 ``voice.mobile_tts_failed``。

本轮复验（真实链路，桌面端发送制造真实抢占）：
1. 角色回复完成 → mobile-tts 下发开始（``voice.mobile_tts_chunk``）；
2. 新回复到达 → 抢占中断旧合成任务；
3. 断言：抢占**不产生** ``voice.mobile_tts_failed``；被中断的任务以
   ``voice.mobile_tts_end`` 或静默收尾结束；日志出现「抢占中断旧合成任务」；
4. 真实供应商失败必须仍如实上报（本轮若未出现，如实记录未构造）。
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

CASE = "V039-S4-018"
PAIR_A = "phainon_ancient_machine"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-project"
LONG_PROMPT = ("复测语音抢占：请用大约 600 字讲一段关于启程与告别的独白，"
               "句子完整、不要分行、不要列表。")
SHORT_PROMPT = "只回复两个字：收到。"


async def safe(session: Harness, method: str, params: dict, timeout: float = 60.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:300]}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout"}


async def wait_character_done(session: Harness, conversation_id: str,
                              timeout: float = 240.0) -> dict:
    """等到本轮角色消息落定为 done（mobile-tts 随即开始下发）。"""
    deadline = asyncio.get_running_loop().time() + timeout
    snapshot: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        characters = [m for m in snapshot.get("messages", [])
                      if m.get("source") == "character"]
        if characters and all(m.get("status") in {"done", "failed", "cancelled"}
                              for m in characters) and not snapshot.get("active_task"):
            return snapshot
        await asyncio.sleep(0.5)
    return snapshot


def voice_events(session: Harness, names: tuple[str, ...]) -> list[dict]:
    out = []
    for envelope in session.events:
        name = str(envelope.get("event") or "")
        if any(name == n for n in names):
            out.append({"event": name, **event_fields(envelope)})
    return out


async def main() -> int:
    out = case_dir(CASE)
    result = result_shell(CASE, title="抢占与停止的收尾语义复验（不误报合成失败）")
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="r1-mobile-tts")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next((p for p in (bootstrap.get("projects") or [])
                        if p.get("root_path", "").endswith("retest-project")), None)
        project_id = (project or {}).get("project_id")
        if project_id is None:
            created = await session.call("project.create", {
                "root_path": PROJECT_ROOT, "name": "retest-project", "pair_id": PAIR_A},
                timeout=30)
            project_id = next(p["project_id"] for p in created["projects"]
                              if p.get("name") == "retest-project")
        conversation = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A, "title": "R1-018-preempt"},
            timeout=30)
        conversation_id = conversation["current_conversation_id"]
        log["conversation_id"] = conversation_id
        log["remote_subscribers"] = True  # 本连接即远程订阅者

        # 第 1 回合：要求长回复，制造可持续数秒的真实合成
        await session.call("chat.submit", {
            "conversation_id": conversation_id, "target": "character",
            "text": LONG_PROMPT}, timeout=60)
        snapshot = await wait_character_done(session, conversation_id, timeout=240)
        first = [m for m in snapshot.get("messages", []) if m.get("source") == "character"]
        log["turn_1"] = {
            "character_messages": [{"message_id": m.get("message_id"),
                                    "chars": len(str(m.get("text") or "")),
                                    "status": m.get("status"),
                                    "tts_eligible": m.get("tts_eligible")}
                                   for m in first],
            "first_message_id": first[0].get("message_id") if first else None,
        }
        # 给下发一点启动时间，确认已进入合成，再抢占
        await asyncio.sleep(2.0)
        chunks_before = len(voice_events(session, ("voice.mobile_tts_chunk",)))
        log["turn_1"]["chunks_before_preemption"] = chunks_before
        log["turn_1"]["preemption_submitted_at"] = now_iso()

        # 抢占：桌面发送新消息 → 新回复到达后中断旧合成任务
        # （第二条要求极短，使新回复尽快到达，落在长合成仍进行中的窗口内）
        await session.call("chat.submit", {
            "conversation_id": conversation_id, "target": "character",
            "text": SHORT_PROMPT}, timeout=60)
        snapshot2 = await wait_character_done(session, conversation_id, timeout=240)
        characters2 = [m for m in snapshot2.get("messages", []) if m.get("source") == "character"]
        log["turn_2"] = {
            "character_messages": [{"message_id": m.get("message_id"),
                                    "chars": len(str(m.get("text") or "")),
                                    "status": m.get("status")}
                                   for m in characters2],
            "active_task": bool(snapshot2.get("active_task")),
        }
        # 让被中断任务与后续任务收尾
        await asyncio.sleep(8)

        events = voice_events(session, ("voice.mobile_tts_chunk", "voice.mobile_tts_end",
                                        "voice.mobile_tts_failed", "voice.state_changed"))
        failed = [e for e in events if e["event"] == "voice.mobile_tts_failed"]
        ended = [e for e in events if e["event"] == "voice.mobile_tts_end"]
        chunk_count: dict = {}
        for e in events:
            if e["event"] == "voice.mobile_tts_chunk":
                chunk_count[e.get("message_id")] = chunk_count.get(e.get("message_id"), 0) + 1
        log["voice_events_summary"] = {
            "chunk_per_message": chunk_count,
            "end_messages": [e.get("message_id") for e in ended],
            "failed_count": len(failed),
            "failed_payloads": failed[:5],
        }
        log["assertions"] = {
            "no_failed_event": len(failed) == 0,
            "at_least_one_synthesis_observed": bool(chunk_count),
            "end_after_preemption": bool(ended),
            "preemption_observed_in_log": None,  # 由下方 sidecar 日志填充
        }
        log["preempted_message_id"] = next(
            (e.get("message_id") for e in ended), None)
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        lines = (out / "sidecar.log").read_text(encoding="utf-8").splitlines()
        write_info_log(CASE, lines)
        log["preemption_log_lines"] = [
            line for line in lines
            if "抢占中断旧合成任务" in line or "mobile-tts" in line
            or "mobile_tts" in line][:200]
    except OSError:
        pass
    log["assertions"]["preemption_observed_in_log"] = any(
        "抢占中断旧合成任务" in line for line in (log.get("preemption_log_lines") or []))
    (out / "preempt-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "V039-S4-018 全部交互走 WS 帧；含真实 DashScope 合成")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_018_preempt.py",
    ])
    result["status"] = "待判定"
    result["actual"] = json.dumps({
        "turn_1": log["turn_1"], "turn_2": log["turn_2"],
        "voice_events_summary": log["voice_events_summary"],
        "assertions": log["assertions"]}, ensure_ascii=False)[:4000]
    result["timestamps"]["finished_at"] = now_iso()
    result["evidence"] = ["preempt-run.json", "ws-frames.log", "events.log",
                          "sidecar.log", "sidecar-info.log"]
    save_result(CASE, result)
    print(json.dumps(log, ensure_ascii=False, indent=2)[:6000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
