"""V039-S4-016 复验：播放控制守卫的调用方身份判定。

修复目标（V039-S4-016）：租约有效期内只有**持有者**可以起播。
三项共享守卫的方法（``voice.tts_play`` / ``voice.preview`` / ``voice.card_preview``）
在三种调用方身份下逐一核对：

| 身份 | 期望 |
| --- | --- |
| 无租约的任何调用方 | 放行（守卫不拦），随后按各自参数规则失败或成功 |
| 租约持有者 | **放行**（修复前被拒——原实现只看租约是否存在） |
| 另一台远程设备 | 被拒，文案点名「另一台远程设备」 |

合成成本控制（B-02：语音输出侧最小确认 ≤3 条）：除一次真实试听外，
其余全部用「无效参数」探测守卫是否放行——被守卫拦下时错误码为
``remote_playback_active``，放行时则是参数类错误（card_not_found / invalid_text），
两者可明确区分且不产生任何合成请求。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso, pair
from r1common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell,
)

CASE = "V039-S4-016"
SHORT_TEXT = "复测语音守卫，只念这一句。"
MISSING_CARD = "no-such-card-r1-016"


async def safe(session: Harness, method: str, params: dict, timeout: float = 45.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:300],
                "details": exc.details}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout"}


def classify(result: dict) -> str:
    """把守卫判定归一化：被拒 / 放行（参数类错误）/ 其他。"""
    if result.get("ok"):
        return "放行（成功）"
    code = result.get("code")
    if code == "remote_playback_active":
        return "被守卫拒绝"
    if code in {"card_not_found", "invalid_text", "voice_unavailable",
                "message_not_found", "invalid_params"}:
        return "放行（参数类错误）"
    return f"其他（{code}）"


async def probe_guarded(session: Harness, label: str) -> dict:
    """用三个共享守卫的方法探测调用方是否被放行（不产生合成）。"""
    probes = {
        "voice.preview": {"text": "   "},                       # 空文本 → invalid_text
        "voice.tts_play": {"message_id": "no-such-message-r1"},  # 未知消息 → 参数类错误
        "voice.card_preview": {"card_id": MISSING_CARD},         # 未知卡 → card_not_found
    }
    out: dict = {}
    for method, params in probes.items():
        result = await safe(session, method, params)
        out[method] = {"code": result.get("code"), "ok": result.get("ok"),
                       "message": result.get("message"),
                       "guarded": classify(result)}
    print(f"[{label}] " + json.dumps(out, ensure_ascii=False)[:400], flush=True)
    return out


async def main() -> int:
    out = case_dir(CASE)
    result = result_shell(CASE, title="播放控制守卫的调用方身份判定复验")
    token_a = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session_a = Harness(WS_URL, token_a, frames_log=out / "ws-frames-a.log",
                        events_log=out / "events-a.log", device_name="r1-device-a")
    await session_a.connect()
    session_b: Harness | None = None
    try:
        # 第二台远程设备：由已鉴权连接签发配对码后配对（remote.issue_code）
        issued = await safe(session_a, "remote.issue_code", {})
        log["issue_code"] = {"ok": issued.get("ok"), "result": issued.get("result"),
                             "code": issued.get("code"), "message": issued.get("message")}
        code = str((issued.get("result") or {}).get("code") or "")
        if code:
            token_b, err = await pair(WS_URL, code, "r1-device-b")
            log["pair_device_b"] = {"ok": bool(token_b), "error": err}
            if token_b:
                session_b = Harness(WS_URL, token_b, frames_log=out / "ws-frames-b.log",
                                    events_log=out / "events-b.log", device_name="r1-device-b")
                await session_b.connect()

        # 1. 无租约基线：任何调用方都应被放行
        log["baseline_no_lease"] = await probe_guarded(session_a, "无租约 A")

        # 2. A 认领控制权
        log["claim_control"] = await safe(session_a, "remote.claim_control", {})
        log["control_status_after_claim"] = await safe(session_a, "remote.control_status", {})

        # 3. 租约期内：持有者放行（修复核心）
        log["holder_a"] = await probe_guarded(session_a, "持权 A")

        # 4. 租约期内：另一台远程设备被拒
        if session_b is not None:
            log["other_device_b"] = await probe_guarded(session_b, "他端 B")

        # 5. 真实试听一次（持权端真的能起播），随后立即停声
        preview = await safe(session_a, "voice.preview",
                             {"text": SHORT_TEXT}, timeout=60)
        log["holder_real_preview"] = {"ok": preview.get("ok"), "code": preview.get("code"),
                                      "message": preview.get("message")}
        await asyncio.sleep(2)
        bootstrap = await session_a.call("app.bootstrap", timeout=30)
        log["voice_during_preview"] = bootstrap.get("voice")
        log["tts_stop"] = await safe(session_a, "voice.tts_stop", {})

        # 6. 释放后：任意调用方恢复放行
        log["release_control"] = await safe(session_a, "remote.release_control", {})
        log["after_release"] = await probe_guarded(session_a, "释放后 A")
        if session_b is not None:
            log["after_release_b"] = await probe_guarded(session_b, "释放后 B")

        # 7. 事件证据
        log["control_events"] = [
            {"event": e.get("event"), **(e.get("payload") or {})}
            for e in session_a.events
            if str(e.get("event", "")).startswith("remote.control")
        ]
    finally:
        await session_a.close()
        if session_b is not None:
            await session_b.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        write_info_log(CASE, (out / "sidecar.log").read_text(encoding="utf-8").splitlines())
    except OSError:
        pass
    (out / "guard-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "V039-S4-016 全部交互走 WS 帧；含 1 条真实 DashScope 合成")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_016_guard.py",
    ])
    result["status"] = "待判定"
    result["actual"] = json.dumps(log, ensure_ascii=False)[:5000]
    result["timestamps"]["finished_at"] = now_iso()
    result["evidence"] = ["guard-run.json", "ws-frames-a.log", "ws-frames-b.log",
                          "events-a.log", "sidecar.log", "sidecar-info.log"]
    save_result(CASE, result)
    print(json.dumps(log, ensure_ascii=False, indent=2)[:6000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
