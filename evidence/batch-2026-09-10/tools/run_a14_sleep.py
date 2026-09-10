"""A14 收尾：真实系统休眠 3 分钟后唤醒，验证恢复。

流程：
1. 记录休眠前状态（bootstrap、voice、当前会话、sidecar 进程）；
2. 注册一个带 WakeToRun 的计划任务在 3 分钟后唤醒本机；
3. 调用 SetSuspendState 让本机进入睡眠；
4. 唤醒后记录状态，跑一条真实新 turn，确认链路恢复；
5. 删除计划任务并落盘证据。

若计划任务未能在唤醒时生效，机器会保持睡眠直到人工唤醒；唤醒后本脚本继续执行。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
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

CASE = "A14"
SLEEP_MINUTES = 3
WAKE_TASK = "S4-A14-Wake"


def ps(command: str) -> dict:
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    return {"rc": result.returncode, "stdout": (result.stdout or "").strip()[:500],
            "stderr": (result.stderr or "").strip()[:300]}


def process_snapshot() -> str:
    return ps("Get-CimInstance Win32_Process -Filter \"Name='hsr-partner-harness.exe' or "
              "Name='pair-harness-sidecar.exe'\" | Select-Object ProcessId,Name,"
              "CreationDate | ConvertTo-Json -Compress").get("stdout", "")


async def state(session: Harness, conversation_id: str | None) -> dict:
    bootstrap = await session.call("app.bootstrap", timeout=30)
    result = {
        "at": now_iso(),
        "current_conversation_id": bootstrap.get("current_conversation_id"),
        "active_tasks": bootstrap.get("active_tasks"),
        "approvals": len(bootstrap.get("approvals") or []),
        "voice": bootstrap.get("voice"),
    }
    if conversation_id:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        result["messages"] = [{"source": m.get("source"), "kind": m.get("kind"),
                               "status": m.get("status"), "text": str(m.get("text"))[:80]}
                              for m in snapshot.get("messages", [])]
    return result


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso(), "sleep_minutes": SLEEP_MINUTES}

    session = Harness(WS_URL, token, frames_log=out / "ws-frames-sleep.log",
                      events_log=out / "events-sleep.log", device_name="s4-a14-sleep")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next(p for p in (bootstrap.get("projects") or [])
                       if p.get("name") == "project-alpha")
        created = await session.call(
            "conversation.create",
            {"project_id": project["project_id"], "pair_id": "firefly_sam",
             "title": "A14-sleep"}, timeout=30)
        conversation_id = created["current_conversation_id"]
        log["conversation_id"] = conversation_id
        log["pre_sleep_state"] = await state(session, conversation_id)
        log["pre_sleep_processes"] = process_snapshot()

        schedule = ps(
            f"$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes({SLEEP_MINUTES}); "
            f"$s = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries "
            f"-DontStopIfGoingOnBatteries; "
            f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c exit'; "
            f"Register-ScheduledTask -TaskName '{WAKE_TASK}' -Trigger $t -Settings $s "
            f"-Action $a -Force | Select-Object -ExpandProperty TaskName")
        log["wake_task_register"] = schedule
        if schedule.get("rc") != 0 or WAKE_TASK not in (schedule.get("stdout") or ""):
            log["aborted"] = "唤醒计划任务注册失败，未执行休眠（避免无法自动唤醒）"
            print(json.dumps(log, ensure_ascii=False)[:600], flush=True)
            return 1

        log["suspend_command"] = ps(
            "Add-Type -Namespace S4 -Name Power -MemberDefinition "
            "'[DllImport(\"powrprof.dll\")] public static extern bool SetSuspendState(bool hibernate, bool forceCritical, bool disableWakeEvent);'; "
            "[S4.Power]::SetSuspendState($false, $false, $false) | Out-Null; 'suspend-requested'")
        print("suspend requested at", now_iso(), flush=True)

        # 休眠期间本进程被挂起；唤醒后从这里继续。
        await asyncio.sleep(SLEEP_MINUTES * 60 + 20)
        log["resumed_at"] = now_iso()
        log["post_wake_processes"] = process_snapshot()

        try:
            log["post_wake_state"] = await state(session, conversation_id)
            submit = await session.call(
                "chat.submit",
                {"conversation_id": conversation_id, "target": "character",
                 "text": "A14-SLEEP-RESUME 只回复一个词：醒"}, timeout=60)
            log["post_wake_submit"] = {"ok": True,
                                       "message_id": submit.get("message_id") if isinstance(submit, dict) else None}
            deadline = time.monotonic() + 180
            snapshot = {}
            while time.monotonic() < deadline:
                snapshot = await session.call("conversation.open",
                                              {"conversation_id": conversation_id}, timeout=30)
                pending = [m for m in snapshot.get("messages", [])
                           if m.get("status") in {"pending", "streaming", "processing"}]
                if not pending and not snapshot.get("active_task"):
                    break
                await asyncio.sleep(2)
            log["post_wake_turn"] = {
                "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                              "status": m.get("status"), "text": str(m.get("text"))[:80]}
                             for m in snapshot.get("messages", [])],
                "turns": snapshot.get("turns"),
            }
        except (HarnessError, asyncio.TimeoutError, OSError) as exc:
            log["post_wake_error"] = f"{type(exc).__name__}: {exc}"
            print("post-wake error:", log["post_wake_error"], flush=True)
    finally:
        log["wake_task_cleanup"] = ps(
            f"Unregister-ScheduledTask -TaskName '{WAKE_TASK}' -Confirm:$false "
            f"-ErrorAction SilentlyContinue; "
            f"(Get-ScheduledTask -TaskName '{WAKE_TASK}' -ErrorAction SilentlyContinue | "
            f"Measure-Object).Count")
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar-sleep.log")
    (out / "a14-sleep.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a14_sleep.py",
        "# 本机真实休眠 3 分钟后由 WakeToRun 计划任务唤醒；异常时手工唤醒并删除 S4-A14-Wake 任务",
    ])
    write_http_log(out / "http.log", "A14 休眠恢复：WS 帧 + Windows 电源操作")
    print("A14 sleep phase finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
