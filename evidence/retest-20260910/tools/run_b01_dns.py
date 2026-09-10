"""B-01 第五形态：名称解析失败（不经代理的 .invalid 域）。

沙盒（§4.1 首选方案）覆盖「连接被拒 / 传输中断 / 悬挂超时」三种出站故障；
名称解析失败必须在**客户端自身解析**的路径上注入，因此本用例：
1. 停候选 → 把 `%LOCALAPPDATA%\\PairHarness\\.env` 的对话端点改为 RFC 6761 保留域
   `no-such-host-r1.invalid`（保证不解析）→ 重启候选；
2. 用一个**没有任何账号级配置**的独立账号跑真实回合，使其回落到环境变量端点；
3. 记录失败如何暴露，随后恢复 .env、重启候选并核对真实端点可用。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso
from r1common import (
    WS_URL, case_dir, load_token, process_table, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell, save_result,
)

CASE = "B-01"
REPO = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic")
ENV_FILE = Path(os.environ["LOCALAPPDATA"]) / "PairHarness" / ".env"
ENV_BACKUP = REPO / ".tmp" / "retest-env-backup.env"
EXE = REPO / r"desktop\src-tauri\target\release\hsr-partner-harness.exe"
DNS_HOST = "https://no-such-host-r1.invalid/v1"
PROBE_ACCOUNT = "R1-dns-probe"
PROBE_PASSWORD = "r1dnsprobe2026"
PROBE_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-dns-project"


def ps(command: str) -> dict:
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    return {"rc": result.returncode, "stdout": (result.stdout or "").strip()[:400],
            "stderr": (result.stderr or "").strip()[:400]}


def stop_candidate() -> dict:
    return ps("Stop-Process -Name hsr-partner-harness -Force -ErrorAction SilentlyContinue; "
              "Start-Sleep -Seconds 3; (Get-Process -Name hsr-partner-harness "
              "-ErrorAction SilentlyContinue | Measure-Object).Count")


def start_candidate(use_proxy: bool) -> dict:
    proxy = ("$env:HTTPS_PROXY='http://127.0.0.1:8767'; "
             "$env:HTTP_PROXY='http://127.0.0.1:8767'; "
             "$env:NO_PROXY='127.0.0.1,localhost,no-such-host-r1.invalid'; ") if use_proxy else ""
    return ps(f"{proxy}$env:PAIR_HARNESS_LOG_LEVEL='INFO'; "
              f"Start-Process -FilePath '{EXE}' | Out-Null; Start-Sleep -Seconds 10; "
              "(Get-Process -Name hsr-partner-harness -ErrorAction SilentlyContinue | "
              "Select-Object -First 1 -ExpandProperty Id)")


def write_env(base_url: str, proxy_note: str) -> str:
    text = ENV_BACKUP.read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if line.startswith("PAIR_HARNESS_DIALOGUE_BASE_URL="):
            lines.append(f"PAIR_HARNESS_DIALOGUE_BASE_URL={base_url}")
        else:
            lines.append(line)
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return proxy_note


async def wait_ready(timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 8765)
            writer.close()
            return True
        except OSError:
            await asyncio.sleep(1.5)
    return False


async def safe(session: Harness, method: str, params: dict, timeout: float = 60.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:300]}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout"}


async def wait_turn(session: Harness, conversation_id: str, timeout: float = 120.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    snapshot: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        messages = snapshot.get("messages", [])
        settled = [m for m in messages
                   if m.get("source") != "user"
                   and m.get("status") in {"done", "failed", "cancelled"}]
        if settled and not snapshot.get("active_task") and not snapshot.get("queue_items"):
            return snapshot
        await asyncio.sleep(1.5)
    return snapshot


async def main() -> int:
    out = case_dir(CASE)
    log: dict = {"started_at": now_iso()}
    token = load_token()
    sidecar_log_mark()

    # —— 1. 注入：改 .env 端点 → 重启候选（不带代理，客户端自行解析）——
    log["env_before"] = ENV_FILE.read_text(encoding="utf-8").splitlines()[:1]
    write_env(DNS_HOST, "客户端自行解析 .invalid 域，不经沙盒")
    log["env_injected"] = DNS_HOST
    log["stop_before_inject"] = stop_candidate()
    log["start_with_dns"] = start_candidate(use_proxy=False)
    ready = await wait_ready()
    log["sidecar_ready"] = ready
    if not ready:
        raise RuntimeError("候选在 DNS 注入后未就绪")

    session = Harness(WS_URL, token, frames_log=out / "ws-frames-dns.log",
                      events_log=out / "events-dns.log", device_name="r1-dns")
    await session.connect()
    try:
        # 独立账号（无账号级配置 → 回落到环境变量端点）
        accounts = await safe(session, "account.list", {})
        existing = next((a for a in ((accounts.get("result") or {}).get("accounts") or [])
                         if a.get("username") == PROBE_ACCOUNT), None)
        registered = await safe(session, "account.register", {
            "username": PROBE_ACCOUNT, "display_name": PROBE_ACCOUNT,
            "password": PROBE_PASSWORD})
        probe_id = ((existing or {}).get("account_id")
                    or (registered.get("result") or {}).get("account_id"))
        switched = await safe(session, "account.switch", {"account_id": probe_id or ""})
        current = (await session.call("app.bootstrap", timeout=30)).get("current_account_id")
        log["probe_account"] = {"account_id": probe_id, "current": current,
                                "register": registered, "switch": switched}
        Path(PROBE_ROOT).mkdir(parents=True, exist_ok=True)
        project = await safe(session, "project.create", {
            "root_path": PROBE_ROOT, "name": "retest-dns-project",
            "pair_id": "phainon_ancient_machine"})
        project_id = next(
            (p["project_id"] for p in ((project.get("result") or {}).get("projects") or [])
             if p.get("name") == "retest-dns-project"), None)
        log["probe_project_id"] = project_id
        log["effective_config"] = await safe(session, "config.get", {})
        conversation = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": "phainon_ancient_machine",
            "title": "R1-B01-dns"}, timeout=30)
        conversation_id = conversation["current_conversation_id"]
        log["conversation_id"] = conversation_id
        await session.call("chat.submit", {
            "conversation_id": conversation_id, "target": "character",
            "text": "复测 B-01：请只回复两个字：解析。"}, timeout=60)
        snapshot = await wait_turn(session, conversation_id, timeout=120)
        log["dns_turn"] = {
            "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                          "status": m.get("status"),
                          "text": str(m.get("text") or "")[:400]}
                         for m in snapshot.get("messages", [])],
            "failure_notice": next(
                (str(m.get("text")) for m in snapshot.get("messages", [])
                 if m.get("source") == "system" and "失败" in str(m.get("text") or "")),
                None),
        }
        log["restore_account"] = await safe(session, "account.switch",
                                            {"account_id": "default-local"})
    finally:
        await session.close()

    # —— 2. 恢复 .env 并重启候选，核对真实端点恢复可用 ——
    write_env("https://api.deepseek.com", "恢复")
    log["stop_before_restore"] = stop_candidate()
    log["start_after_restore"] = start_candidate(use_proxy=False)
    log["ready_after_restore"] = await wait_ready()
    log["env_restored"] = ENV_FILE.read_text(encoding="utf-8").splitlines()[0]

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar-dns.log")
    try:
        write_info_log(CASE, (out / "sidecar-dns.log").read_text(
            encoding="utf-8").splitlines())
    except OSError:
        pass
    (out / "dns-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http-dns.log", "B-01 名称解析失败形态；不经代理")
    write_commands(out / "commands.ps1", [
        "# 名称解析失败形态：改 %LOCALAPPDATA%\\PairHarness\\.env 的对话端点为保留域后重启候选",
        "python evidence/retest-20260910/tools/run_b01_dns.py",
    ])
    print(json.dumps(log, ensure_ascii=False, indent=2)[:4000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
