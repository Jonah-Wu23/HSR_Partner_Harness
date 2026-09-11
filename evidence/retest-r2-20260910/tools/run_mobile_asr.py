"""Android 壳语音输入（ASR）真机用例。

思路：手机端「按住说话」会经 `voice.mobile_ptt_start` 开一个 ASR 会话并从
麦克风采集；这里用**电脑扬声器**朗读一句中文，让手机麦克风真实拾音，从而走完
「真实麦克风 → 真实 DashScope ASR → 转写文本」的完整链路。

不合成转写结果、不伪造文本：若拾音失败（没识别出内容），如实记录为未构造。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ph_client import Harness, now_iso
from r2common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_commands, write_http_log, result_shell, build_block,
)

CASE = "mobile-voice-input"
ADB = r"E:\AI\CHD-class-table\tools\android-sdk\platform-tools\adb.exe"
SERIAL = "10.81.140.245:42919"
UTTERANCE = "请把项目根目录里的文件念给我听"
PTT_BUTTON = (173, 2380)   # 「语音」（按住说话）按钮，取自 ui-chat 的 clickable bounds


def _env() -> dict:
    merged = dict(os.environ)
    merged["MSYS_NO_PATHCONV"] = "1"
    merged["ANDROID_SERIAL"] = SERIAL
    return merged


def adb(*args: str, timeout: float = 120.0) -> str:
    result = subprocess.run([ADB, *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout,
                            check=False, env=_env())
    return (result.stdout or "").strip()


def screen(path: Path) -> None:
    with path.open("wb") as handle:
        subprocess.run([ADB, "exec-out", "screencap", "-p"], stdout=handle,
                       stderr=subprocess.DEVNULL, timeout=90, env=_env())


def dump(path: Path) -> Path:
    adb("shell", "uiautomator", "dump", "/sdcard/vasr.xml")
    out = adb("shell", "cat", "/sdcard/vasr.xml")
    path.write_text(out, encoding="utf-8")
    return path


def readable_texts(path: Path) -> list[str]:
    import html
    import re
    x = path.read_text(encoding="utf-8", errors="replace")
    found = []
    for m in re.finditer(r"<node[^>]*>", x):
        t = re.search(r'text="([^"]*)"', m.group(0))
        if t and html.unescape(t.group(1)).strip():
            found.append(html.unescape(t.group(1)))
    return found


def speak_async(text: str, delay: float) -> subprocess.Popen:
    escaped = text.replace("'", "''")
    script = (
        f"Start-Sleep -Milliseconds {int(delay * 1000)}; "
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = -1; $s.Volume = 100; "
        "$s.SelectVoice('Microsoft Huihui Desktop'); "
        f"$s.Speak('{escaped}'); $s.Dispose()"
    )
    return subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def press_ptt() -> None:
    x, y = PTT_BUTTON
    adb("shell", "input", "motionevent", "DOWN", str(x), str(y))


def release_ptt() -> None:
    x, y = PTT_BUTTON
    adb("shell", "input", "motionevent", "UP", str(x), str(y))


async def main() -> int:
    out = case_dir(CASE)
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    token = load_token()
    conversation_id = Path(
        r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\r2-voice-conversation.txt"
    ).read_text(encoding="utf-8").strip()
    log["conversation_id"] = conversation_id
    log["utterance"] = UTTERANCE

    # 事件观察连接：只读，用于记录服务端语音输入相关事件
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="voice-input-observer")
    await session.connect()
    try:
        before = dump(out / "01-before.xml")
        log["ui_before"] = readable_texts(before)[:25]
        screen(out / "01-before.png")

        # 按下后先等会话与麦克风就绪（面板出现「按住说话 / 自动检测」），再让电脑朗读，
        # 否则采集尚未开始，朗读会落在静默里（首轮即因此无转写）。
        press_ptt()
        ready_seen = False
        for _ in range(12):
            await asyncio.sleep(1.5)
            probe = dump(out / "00-ready-probe.xml")
            texts = readable_texts(probe)
            log.setdefault("readiness_probe", []).append([t for t in texts if t in
                                                          ("准备中…", "按住说话", "自动检测", "松开结束")])
            if any(t in texts for t in ("松开结束", "自动检测")):
                ready_seen = True
                break
        log["session_ready"] = ready_seen
        screen(out / "01b-ready.png")

        speaker = speak_async(UTTERANCE, delay=0.4)
        speaker.wait(timeout=60)
        await asyncio.sleep(1.5)
        release_ptt()
        await asyncio.sleep(10)

        after = dump(out / "02-after.xml")
        texts = readable_texts(after)
        log["ui_after"] = texts[:30]
        screen(out / "02-after.png")
        log["transcript_visible"] = [t for t in texts if "文件" in t or "根目录" in t]

        voice_events = [{"event": e.get("event"), "payload": e.get("payload"),
                         "at": e.get("_received_at")}
                        for e in session.events
                        if "voice" in str(e.get("event", ""))]
        log["voice_events"] = voice_events[-25:]
        log["voice_event_names"] = sorted({str(e.get("event")) for e in session.events})
    finally:
        await session.close()

    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        lines = (out / "sidecar.log").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    log["asr_log_lines"] = [line for line in lines
                            if any(k in line for k in ("asr", "ASR", "语音", "转写", "ptt"))]
    log["finished_at"] = now_iso()
    (out / "asr-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log",
                   "语音输入：手机端「按住说话」经 WS 开 ASR 会话并上传麦克风 PCM；音频来源为电脑扬声器朗读")
    write_commands(out / "commands.ps1", [
        "# 电脑扬声器朗读一句中文，同时手机端按住「语音」按钮 8 秒",
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-r2-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_mobile_asr.py",
    ])
    r = result_shell(CASE, title="Android 壳语音输入（真实麦克风 → 真实 ASR）")
    r["build"] = build_block()
    r["device"] = "Xiaomi 24129PN74C（Android 16 / SDK 36 / arm64-v8a）"
    r["network"] = "局域网 10.81.0.0/16（HTTP）；出站到 DashScope 真实 WSS"
    r["actual"] = json.dumps(log, ensure_ascii=False)[:20000]
    r["timestamps"]["finished_at"] = now_iso()
    r["evidence"] = ["asr-run.json", "ws-frames.log", "events.log", "sidecar.log",
                     "01-before.png", "02-after.png", "01-before.xml", "02-after.xml"]
    save_result(CASE, r)
    print(json.dumps({
        "transcript_visible": log.get("transcript_visible"),
        "voice_event_names": log.get("voice_event_names"),
        "ui_after_tail": log.get("ui_after", [])[-12:],
        "asr_log_lines": log.get("asr_log_lines", [])[:20],
    }, ensure_ascii=False, indent=2)[:6000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
