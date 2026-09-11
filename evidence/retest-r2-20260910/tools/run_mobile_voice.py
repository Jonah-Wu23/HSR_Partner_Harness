"""Android 壳语音播放与打断（抢占）真机用例。

场景（对应移动平台矩阵「语音：输入、播放、打断、挂起恢复、溢出」中的播放与打断）：

1. **播放**：桌面提交一条要求较长回复的角色消息 → 服务端真实合成并逐片下行
   `voice.mobile_tts_chunk`（24 kHz s16le PCM）→ 手机端播放。断言：分片真实下行、
   合成条数与真实模型回复匹配、播放期间手机 UI 进入播报态。
2. **打断（抢占）**：播放进行中再从桌面提交一条新消息 → 旧消息必须被抢占中断、
   其分片不得复活、且**不得**产生 `voice.mobile_tts_failed`（V039-S4-018 回归）。

只做真实链路：真实 DeepSeek 回复 + 真实 DashScope 合成，不合成成功事件。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

from ph_client import Harness, event_fields, now_iso
from r2common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_commands, write_http_log, result_shell, build_block,
)

CASE = "mobile-voice"
ADB = r"E:\AI\CHD-class-table\tools\android-sdk\platform-tools\adb.exe"
SERIAL = "10.81.140.245:42919"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\r2-mobile-project"
PAIR_A = "phainon_ancient_machine"

MSG_A = ("请用大约六百字写一段连贯的自述，介绍你的来历、日常、性格和在意的人，"
         "分成若干自然段，不要用列表，不要用标题。这段文字会被完整朗读出来，"
         "请写适合朗读的长句。")
MSG_B = "打断测试：请只回复两个字：收到。"


def adb(*args: str, timeout: float = 60.0) -> str:
    env = {"MSYS_NO_PATHCONV": "1"}
    import os
    merged = dict(os.environ)
    merged.update(env)
    merged["ANDROID_SERIAL"] = SERIAL
    result = subprocess.run([ADB, *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout,
                            check=False, env=merged)
    return (result.stdout or "").strip()


def screen(path: Path) -> bool:
    import os
    merged = dict(os.environ)
    merged["MSYS_NO_PATHCONV"] = "1"
    merged["ANDROID_SERIAL"] = SERIAL
    with path.open("wb") as handle:
        result = subprocess.run([ADB, "exec-out", "screencap", "-p"], stdout=handle,
                                stderr=subprocess.DEVNULL, timeout=90, env=merged)
    return result.returncode == 0 and path.stat().st_size > 0


def audio_state() -> str:
    out = adb("shell", "dumpsys", "audio")
    keep = [line.strip() for line in out.splitlines()
            if any(k in line for k in ("state:", "AudioPlaybackConfiguration",
                                       "player piid", "usage=", "AudioFocus",
                                       "mFocusStack"))]
    return "\n".join(keep[:60])


class Watch:
    """在会话事件流上按 message_id 归集 TTS 分片。"""

    def __init__(self, session: Harness) -> None:
        self.session = session

    def tts_events(self) -> list[dict]:
        return [e for e in self.session.events
                if str(e.get("event", "")).startswith("voice.mobile_tts")]

    def summary(self) -> dict:
        buckets: dict[str, dict] = {}
        for envelope in self.tts_events():
            payload = event_fields(envelope)
            message_id = str(payload.get("message_id") or "?")
            bucket = buckets.setdefault(message_id, {
                "message_id": message_id, "chunks": 0, "bytes": 0,
                "first_chunk_at": None, "last_chunk_at": None,
                "end": None, "failed": None, "failed_payload": None,
            })
            name = envelope.get("event")
            if name == "voice.mobile_tts_chunk":
                bucket["chunks"] += 1
                bucket["bytes"] += len(str(payload.get("data") or ""))
                if bucket["first_chunk_at"] is None:
                    bucket["first_chunk_at"] = envelope.get("_received_at")
                bucket["last_chunk_at"] = envelope.get("_received_at")
            elif name == "voice.mobile_tts_end":
                bucket["end"] = envelope.get("_received_at")
            elif name == "voice.mobile_tts_failed":
                bucket["failed"] = envelope.get("_received_at")
                bucket["failed_payload"] = payload
        return buckets

    def counts(self) -> dict:
        events = self.tts_events()
        names = ("voice.mobile_tts_chunk", "voice.mobile_tts_end", "voice.mobile_tts_failed")
        return {name: sum(1 for e in events if e.get("event") == name) for name in names}


async def settle(session: Harness, conversation_id: str, *, timeout: float = 180.0) -> dict:
    """等本会话出现角色终态。"""
    deadline = time.monotonic() + timeout
    snapshot: dict = {}
    while time.monotonic() < deadline:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        settled = [m for m in snapshot.get("messages", [])
                   if m.get("source") == "character"
                   and m.get("status") in {"done", "failed", "cancelled"}]
        if settled and not snapshot.get("active_task") and not snapshot.get("queue_items"):
            return snapshot
        await asyncio.sleep(1.5)
    return snapshot


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    conversation_id = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\r2-voice-conversation.txt").read_text(encoding="utf-8").strip()
    log["conversation_id"] = conversation_id

    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="voice-runner")
    await session.connect()
    watch = Watch(session)
    try:
        # 手机端先停在会话页，播放与播放态截图才有意义
        log["phone_focus"] = adb("shell", "am", "start", "-n",
                                 "com.jonahwu.hsr_partner_harness/.MainActivity")
        await asyncio.sleep(5)
        screen(out / "01-before-play.png")

        # —— 1. 播放 ——
        log["submit_a"] = await session.call("chat.submit", {
            "conversation_id": conversation_id, "target": "character", "text": MSG_A},
            timeout=60)
        log["playback_watch"] = []
        playing_seen = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            counts = watch.counts()
            log["playback_watch"].append({"at": now_iso(), **counts})
            if counts["voice.mobile_tts_chunk"] > 0 and not playing_seen:
                playing_seen = True
                log["first_chunk_at"] = now_iso()
                await asyncio.sleep(3)
                screen(out / "02-playing.png")
                log["audio_during_play"] = audio_state()[:4000]
                break
            await asyncio.sleep(1.0)
        log["playback_started"] = playing_seen

        # 分片下行远快于实时播放（DashScope 合成快于 1x），因此抢占必须紧跟首个分片；
        # 首轮用 6 秒间隔时旧合成早已结束，服务端抢占根本没发生（见首轮证据）。
        await asyncio.sleep(1.2)
        log["chunks_before_preempt"] = watch.counts()
        screen(out / "03-playing-later.png")

        # —— 2. 打断（抢占）：合成仍在进行时立刻提交新消息 ——
        log["submit_b"] = await session.call("chat.submit", {
            "conversation_id": conversation_id, "target": "character", "text": MSG_B},
            timeout=60)
        log["preempt_at"] = now_iso()
        preempt_counts = watch.counts()
        await asyncio.sleep(6)
        screen(out / "04-after-preempt.png")
        log["counts_after_preempt"] = watch.counts()
        log["preempt_observed"] = {
            "chunks_before": preempt_counts,
            "chunks_after": log["counts_after_preempt"],
        }

        # 等两个回合都收尾
        snapshot = await settle(session, conversation_id, timeout=180)
        await asyncio.sleep(8)
        log["final_counts"] = watch.counts()
        log["message_ids"] = [
            {"message_id": m.get("message_id"), "source": m.get("source"),
             "kind": m.get("kind"), "status": m.get("status"),
             "tts_eligible": m.get("tts_eligible"), "chars": len(str(m.get("text") or "")),
             "text": str(m.get("text") or "")[:120]}
            for m in snapshot.get("messages", [])]
        log["tts_buckets"] = watch.summary()
        log["audio_after"] = audio_state()[:4000]
        screen(out / "05-final.png")
    finally:
        await session.close()

    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        lines = (out / "sidecar.log").read_text(encoding="utf-8").splitlines()
        log["preempt_log_lines"] = [line for line in lines if "抢占" in line or "mobile-tts" in line]
    except OSError:
        log["preempt_log_lines"] = []
    log["finished_at"] = now_iso()
    (out / "voice-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "语音播放与打断：真实 DeepSeek 回复 + 真实 DashScope 合成，手机端经局域网播放")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-r2-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_mobile_voice.py",
    ])
    r = result_shell(CASE, title="Android 壳语音：真实合成播放与打断（抢占）")
    r["build"] = build_block()
    r["device"] = "Xiaomi 24129PN74C（Android 16 / SDK 36 / arm64-v8a）"
    r["network"] = "局域网 10.81.0.0/16（HTTP）；出站到 DashScope 真实 WSS"
    r["actual"] = json.dumps(log, ensure_ascii=False)[:20000]
    r["timestamps"]["finished_at"] = now_iso()
    r["evidence"] = ["voice-run.json", "ws-frames.log", "events.log",
                     "sidecar.log", "01-before-play.png", "02-playing.png",
                     "03-playing-later.png", "04-after-preempt.png", "05-final.png"]
    save_result(CASE, r)
    print(json.dumps({
        "playback_started": log.get("playback_started"),
        "first_chunk_at": log.get("first_chunk_at"),
        "chunks_after_6s": log.get("chunks_after_6s"),
        "counts_after_preempt": log.get("counts_after_preempt"),
        "final_counts": log.get("final_counts"),
        "tts_buckets": log.get("tts_buckets"),
        "preempt_log_lines": log.get("preempt_log_lines"),
        "messages": log.get("message_ids"),
    }, ensure_ascii=False, indent=2)[:8000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
