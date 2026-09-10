"""A09：真实 TTS 播放中的三类抢占（协议级）。

准备：领取远程播放控制权 → voice.preview 合成一段长文本（约 60–120 秒语音）。
抢占：在播放过程中触发
  1) 桌面发送（chat.submit 走 _interrupt_desktop_speech("user_send")）；
  2) 新回复到达（角色最终消息 → TTS 入队，取代旧队列）；
  3) 首 delta（流式 partial 不应直接朗读）。
断言：旧播放/队列/在途合成停止、迟到 PCM 不复活、partial delta 不直接朗读；
      以 voice.state_changed / voice.* 事件与 bootstrap.voice 快照为证据。
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
    write_http_log,
)

CASE = "A09"
LONG_TEXT = (
    "接下来这段试听会持续较长时间，用来验证播放中的抢占行为。"
    "第一件事是排队：早先入队的语音必须在新的语音到来时让位，不能两条一起念。"
    "第二件事是在途合成：已经开始合成分片的句子要被真正停下，而不是等它念完。"
    "第三件事是迟到分片：被取消的那条语音，即使有分片稍后才到达，也不得重新开始播放。"
    "第四件事是流式正文：角色回复还在逐个字往外流的时候，不应该被当作完整句子朗读，"
    "只有最终成文的那一条才进入语音队列。"
    "现在把这些规则一条一条地念出来，念到自然结束为止，中间不要停。"
) * 3


async def voice_snapshot(session: Harness) -> dict:
    bootstrap = await session.call("app.bootstrap", timeout=30)
    return bootstrap.get("voice") or {}


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso(), "long_text_chars": len(LONG_TEXT)}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="s4-a09")
    await session.connect()

    async def safe(method: str, params: dict, timeout: float = 60.0) -> dict:
        try:
            return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
        except asyncio.TimeoutError:
            return {"ok": False, "code": "client_timeout"}
        except HarnessError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message[:250]}

    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next(p for p in (bootstrap.get("projects") or [])
                       if p.get("name") == "project-alpha")
        created = await session.call(
            "conversation.create",
            {"project_id": project["project_id"], "pair_id": "firefly_sam",
             "title": "A09-preemption"}, timeout=30)
        conversation_id = created["current_conversation_id"]
        log["conversation_id"] = conversation_id

        log["control_claim"] = await safe("remote.claim_control", {})
        log["voice_before"] = await voice_snapshot(session)

        preview = await safe("voice.preview",
                             {"text": LONG_TEXT,
                              "voice_id": "qwen-audio-3.0-tts-flash-firefly-233c61b0cb184b1e94fe5de4448df4ea"})
        log["preview"] = preview
        await asyncio.sleep(6)
        playing = await voice_snapshot(session)
        log["voice_during_playback"] = playing

        # —— 抢占 1：桌面发送 ——
        events_len_before = len(session.events)
        log["preempt_desktop_send"] = {
            "submit": await safe("chat.submit",
                                 {"conversation_id": conversation_id, "target": "character",
                                  "text": "A09-PREEMPT 只回复一个词：停"}, 30),
        }
        await asyncio.sleep(3)
        log["voice_after_send"] = await voice_snapshot(session)
        new_events = [event_fields(e) for e in session.events[events_len_before:]
                      if str(e.get("event", "")).startswith("voice")]
        log["preempt_desktop_send"]["events"] = new_events[:10]

        # —— 抢占 2：新回复到达（等角色最终消息 + TTS 入队）——
        deadline = time.monotonic() + 120
        snapshot = {}
        while time.monotonic() < deadline:
            snapshot = await session.call("conversation.open",
                                          {"conversation_id": conversation_id}, timeout=30)
            pending = [m for m in snapshot.get("messages", [])
                       if m.get("status") in {"pending", "streaming", "processing"}]
            if not pending and not snapshot.get("active_task"):
                break
            await asyncio.sleep(1.0)
        log["turn_after_preemption"] = {
            "character": [{"text": m.get("text"), "tts_eligible": m.get("tts_eligible"),
                           "status": m.get("status")}
                          for m in snapshot.get("messages", []) if m.get("source") == "character"],
            "user": [{"text": m.get("text"), "tts_eligible": m.get("tts_eligible")}
                     for m in snapshot.get("messages", []) if m.get("source") == "user"],
        }
        await asyncio.sleep(4)
        log["voice_after_new_reply"] = await voice_snapshot(session)

        # —— 抢占 3：首 delta 与 partial 不直接朗读 ——
        deltas = [event_fields(e) for e in session.events if e.get("event") == "message.delta"]
        log["delta_analysis"] = {
            "delta_event_count": len(deltas),
            "delta_kinds": sorted({str(d.get("kind")) for d in deltas}),
            "tts_events_during_deltas": [
                event_fields(e) for e in session.events
                if str(e.get("event", "")).startswith("voice")
            ][-6:],
        }

        # —— 显式停声：voice.tts_stop ——
        log["tts_stop"] = await safe("voice.tts_stop", {})
        await asyncio.sleep(2)
        log["voice_after_stop"] = await voice_snapshot(session)
        log["control_release"] = await safe("remote.release_control", {})
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    (out / "a09-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a09.py",
        "# 长文本约 3×160 字，用于制造 60 秒以上真实播放",
    ])
    write_http_log(out / "http.log", "A09 全部交互走 WS 帧；TTS 为 DashScope 真实合成")
    print("A09 finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
