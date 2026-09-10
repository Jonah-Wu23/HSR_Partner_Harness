"""A08：长世界书角色卡上的混合时间线、装配诊断与真实语音输入输出（协议级）。

步骤：
1. 建第二个项目（project-beta）与四个绑定导入卡（fix-c）的聊天，两个项目各两个；
2. 世界书命中：含真实关键词（黑塔空间站）的消息 → 角色回复，装配诊断应见 world_book 模块；
3. 混合时间线：协作模式下达真实委派，产生 角色自然语言 + 助手自然语言 + 思考 + 工具 四类消息；
4. 装配诊断：普通查询不返回隐藏原文；include_hidden=true 才返回，且不是对话流内容；
5. 真实语音输出：领取播放控制 → voice.preview（真实 DashScope 合成）→ 观察语音事件；
6. 真实语音输入：用系统 TTS（Windows SAPI）合成 16kHz 单声道 PCM，按 base64 分片喂入
   mobile PTT 会话 → 得到真实 ASR 文本；
7. 固定 ASR/TTS 模型标识核对（只读，不可通过配置漂移）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

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

CASE = "A08"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CARD_ID = "ad95dd92f89d427f974e69d44b366901"
WORLD_BOOK_KEY = "黑塔空间站"
SPOKEN_TEXT = "请把项目根目录里的文件念给我听"


def synth_speech(path: Path, text: str) -> dict:
    """用 Windows 系统 TTS 合成 16kHz 单声道 PCM WAV（真实语音输入源）。"""
    script = f"""
Add-Type -AssemblyName System.Speech
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile('{path}', $fmt)
$synth.Speak('{text}')
$synth.Dispose()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True, check=False)
    info = {"returncode": result.returncode, "stderr": (result.stderr or "")[:400]}
    if path.exists():
        with wave.open(str(path), "rb") as handle:
            info.update({"channels": handle.getnchannels(),
                         "sampwidth": handle.getsampwidth(),
                         "framerate": handle.getframerate(),
                         "frames": handle.getnframes()})
    return info


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso(), "card_id": CARD_ID}

    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="s4-a08")
    await session.connect()

    async def safe(method: str, params: dict, timeout: float = 45.0) -> dict:
        try:
            return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
        except asyncio.TimeoutError:
            return {"ok": False, "code": "client_timeout"}
        except HarnessError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message[:200]}

    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project_alpha = next(p for p in (bootstrap.get("projects") or [])
                             if p.get("name") == "project-alpha")
        # 第二个项目
        beta_path = Path(r"E:\AI\HSR-v039-acceptance\project-beta")
        beta_path.mkdir(parents=True, exist_ok=True)
        created_project = await safe("project.create",
                                     {"name": "project-beta", "root_path": str(beta_path)})
        log["project_beta"] = created_project if not created_project["ok"] else {
            "ok": True, "project_id": (created_project["result"].get("current_project_id")
                                       or created_project["result"].get("project_id"))}
        bootstrap2 = await session.call("app.bootstrap", timeout=30)
        projects = {p["name"]: p["project_id"] for p in (bootstrap2.get("projects") or [])}
        log["projects"] = projects

        # 四个绑定导入卡的聊天：两个项目各两个
        conversations: dict[str, str] = {}
        for index, (project_name, pair_id) in enumerate(
                (("project-alpha", "phainon_ancient_machine"),
                 ("project-alpha", "march7_fourth_mirror"),
                 ("project-beta", "firefly_sam"),
                 ("project-beta", "phainon_ancient_machine"))):
            title = f"A08-card-{index + 1}"
            created = await session.call(
                "conversation.create",
                {"project_id": projects[project_name], "pair_id": pair_id,
                 "title": title, "character_card_id": CARD_ID}, timeout=30)
            conversations[title] = {
                "conversation_id": created["current_conversation_id"],
                "project_id": projects[project_name], "pair_id": pair_id}
        log["conversations"] = conversations
        print("conversations:", json.dumps(conversations, ensure_ascii=False)[:400], flush=True)

        main_conv = conversations["A08-card-1"]["conversation_id"]

        # —— 世界书命中的真实回合 ——
        await session.call(
            "chat.submit",
            {"conversation_id": main_conv, "target": "character",
             "text": f"我们刚才路过{WORLD_BOOK_KEY}，那边现在是什么情况？用两句话说说。"},
            timeout=60)
        deadline = time.monotonic() + 180
        snapshot = {}
        while time.monotonic() < deadline:
            snapshot = await session.call("conversation.open",
                                          {"conversation_id": main_conv}, timeout=30)
            pending = [m for m in snapshot.get("messages", [])
                       if m.get("status") in {"pending", "streaming", "processing"}]
            if not pending and not snapshot.get("active_task"):
                break
            await asyncio.sleep(1.0)
        log["world_book_turn"] = {
            "character": [m.get("text") for m in snapshot.get("messages", [])
                          if m.get("source") == "character" and m.get("status") == "done"],
            "tts_eligible": [m.get("tts_eligible") for m in snapshot.get("messages", [])
                             if m.get("source") == "character"],
        }

        # —— 装配诊断：普通 vs 隐藏原文 ——
        assembly = await safe("diagnostics.prompt_assembly", {"conversation_id": main_conv})
        assembly_hidden = await safe("diagnostics.prompt_assembly",
                                     {"conversation_id": main_conv, "include_hidden": True})
        log["assembly"] = {
            "normal": assembly,
            "hidden": {
                "ok": assembly_hidden.get("ok"),
                "module_count": len((assembly_hidden.get("result") or {}).get("modules") or []),
                "hidden_present": [
                    bool(m.get("hidden_content"))
                    for m in ((assembly_hidden.get("result") or {}).get("modules") or [])
                ],
                "diagnostics": (assembly_hidden.get("result") or {}).get("diagnostics"),
            },
        }
        normal_modules = (assembly.get("result") or {}).get("modules") or []
        log["assembly"]["normal_module_names"] = [m.get("name") for m in normal_modules]
        log["assembly"]["normal_hidden_all_null"] = all(
            m.get("hidden_content") is None for m in normal_modules)
        print("assembly modules:", log["assembly"]["normal_module_names"], flush=True)

        # —— 混合时间线：协作模式真实委派 ——
        collab = conversations["A08-card-2"]["conversation_id"]
        await session.call("conversation.set_mode",
                           {"conversation_id": collab, "mode": "collaboration"}, timeout=30)
        await session.call(
            "chat.submit",
            {"conversation_id": collab, "target": "assistant",
             "text": "请让第四面镜在项目根目录新建文件 a08-mixed.md，内容写一行：S4-A08 混合时间线。"},
            timeout=60)
        try:
            await session.wait_event("approval.requested", timeout=240,
                                     predicate=lambda e: event_fields(e).get("conversation_id") == collab)
            await session.call("approval.resolve",
                               {"approval_id": event_fields(session.events_named("approval.requested")[-1])
                                .get("approval_id"), "decision": "allow"}, timeout=30)
        except (asyncio.TimeoutError, HarnessError) as exc:
            log["mixed_timeline_approval_error"] = f"{type(exc).__name__}: {exc}"
        deadline = time.monotonic() + 300
        mixed = {}
        while time.monotonic() < deadline:
            mixed = await session.call("conversation.open",
                                       {"conversation_id": collab}, timeout=30)
            kinds = {m.get("kind") for m in mixed.get("messages", [])}
            pending = [m for m in mixed.get("messages", [])
                       if m.get("status") in {"pending", "streaming", "processing"}]
            if not pending and not mixed.get("active_task") and len(kinds) >= 3:
                break
            await asyncio.sleep(2.0)
        log["mixed_timeline"] = {
            "kinds": sorted({str(m.get("kind")) for m in mixed.get("messages", [])}),
            "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                          "status": m.get("status"), "text": str(m.get("text"))[:80]}
                         for m in mixed.get("messages", [])],
            "tool_runs": [{"tool_call_id": t.get("tool_call_id"), "status": t.get("status")}
                          for t in mixed.get("tool_runs", [])],
        }

        # —— 语音：固定模型标识与真实合成 ——
        config = await session.call("config.get", timeout=30)
        log["voice_config"] = config.get("voice")
        log["voice_runtime_state"] = (await session.call("app.bootstrap", timeout=30)).get("voice")

        preview = await safe("voice.preview", {"text": "这是 S4 批次真实语音合成验证。",
                                               "voice_id": "qwen-audio-3.0-tts-flash-phainon-46e9bd0087cd4c4c8d29e1b9f1b5db32"})
        log["voice_preview"] = preview
        await asyncio.sleep(8)
        voice_events = [event_fields(e) for e in session.events
                        if str(e.get("event", "")).startswith("voice")]
        log["voice_events"] = voice_events[-12:]
        print("voice preview:", json.dumps(preview, ensure_ascii=False)[:200], flush=True)

        # —— 真实语音输入：系统 TTS 合成 → 分片喂入 ASR ——
        wav_path = out / "a08-asr-input.wav"
        synth = synth_speech(wav_path, SPOKEN_TEXT)
        log["asr_input_synthesis"] = synth
        if synth.get("returncode") == 0 and wav_path.exists():
            ptt = await safe("voice.mobile_ptt_start", {"conversation_id": main_conv})
            log["asr_ptt_start"] = ptt
            if ptt.get("ok"):
                session_id = ptt["result"]["session_id"]
                with wave.open(str(wav_path), "rb") as handle:
                    pcm = handle.readframes(handle.getnframes())
                chunk_bytes = 3200  # 100ms @16k mono s16le
                chunks = [pcm[i:i + chunk_bytes] for i in range(0, len(pcm), chunk_bytes)]
                sent = 0
                for seq, chunk in enumerate(chunks):
                    result = await safe("voice.mobile_audio_chunk",
                                        {"session_id": session_id, "seq": seq,
                                         "data": base64.b64encode(chunk).decode("ascii")},
                                        timeout=30)
                    if not result.get("ok"):
                        log.setdefault("asr_chunk_errors", []).append({"seq": seq, **result})
                        break
                    sent += 1
                    await asyncio.sleep(0.02)
                log["asr_chunks_sent"] = {"count": sent, "total": len(chunks),
                                          "pcm_bytes": len(pcm)}
                stop = await safe("voice.mobile_ptt_stop", {"session_id": session_id}, timeout=90)
                log["asr_ptt_stop"] = stop
                await asyncio.sleep(6)
                asr_events = [event_fields(e) for e in session.events
                              if str(e.get("event", "")).startswith("voice")]
                log["asr_events"] = asr_events[-10:]
                transcript = ""
                for item in asr_events:
                    for key in ("text", "transcript", "final_text"):
                        if isinstance(item.get(key), str) and item.get(key):
                            transcript = item[key]
                log["asr_transcript"] = transcript
                log["asr_expected"] = SPOKEN_TEXT
                print("ASR transcript:", transcript, flush=True)
            else:
                await safe("voice.mobile_ptt_stop", {"session_id": "none"}, timeout=10)
        else:
            log["asr_input_synthesis_error"] = synth
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    (out / "a08-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a08.py",
        "# 语音输入源：Windows 系统 TTS 合成 16kHz 单声道 WAV（见同目录 a08-asr-input.wav）",
    ])
    write_http_log(out / "http.log", "A08 全部交互走 WS 帧；语音为 DashScope 真实请求")
    print("A08 finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
