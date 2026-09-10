"""B-01 第五形态：名称解析失败（不经代理的 RFC 6761 保留域）。

沙盒覆盖「连接被拒 / 传输中断 / 悬挂超时」三种出站故障；名称解析失败必须在
**客户端自身解析**的路径上注入（经代理时由代理解析，量不到候选的解析阶段），
因此本模块：

1. 停候选 → 把 `%LOCALAPPDATA%\\PairHarness\\.env` 的对话端点改为保留域
   `no-such-host-r2.invalid`（保证不解析）→ 重启候选；
2. 在**同一个验收账号**上跑一个真实回合（账号没有保存过账号级端点，因此
   回落到环境变量端点）；
3. 记录失败如何暴露，随后恢复 .env、重启候选并核对真实端点可用。

S4-R1 时本形态受阻：候选启动期因 `_require_responses_backend` 直接抛错退出
（退出码 2），无法以不可解析端点进入可用运行态。该校验已随 B-03 剥离删除，
本批次须取得区别于前三种的解析阶段失败证据。
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
    EXE, WS_URL, case_dir, load_token, sidecar_log_mark, sidecar_tail,
    write_info_log,
)
from run_b01_network import PAIR_A, PROJECT_ROOT, safe, summarize, wait_turn

CASE = "B-01"
DNS_HOST = "https://no-such-host-r2.invalid/v1"
ENV_FILE = Path(os.environ["LOCALAPPDATA"]) / "PairHarness" / ".env"
ENV_BACKUP = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\r2-env-backup.env")
REAL_HOST = "https://api.deepseek.com"


def ps(command: str) -> dict:
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    return {"rc": result.returncode, "stdout": (result.stdout or "").strip()[:600],
            "stderr": (result.stderr or "").strip()[:600]}


def stop_candidate() -> dict:
    return ps("Stop-Process -Name hsr-partner-harness -Force -ErrorAction SilentlyContinue; "
              "Start-Sleep -Seconds 4; (Get-Process -Name hsr-partner-harness "
              "-ErrorAction SilentlyContinue | Measure-Object).Count")


def start_candidate() -> dict:
    # 显式清空代理：本形态必须由**客户端自己**解析保留域，经代理时失败会落在
    # 代理的连接阶段，量不到候选的解析阶段（首采即因此无效）。
    return ps(f"$env:HTTPS_PROXY=''; $env:HTTP_PROXY=''; $env:ALL_PROXY=''; "
              f"$env:NO_PROXY='*'; $env:PAIR_HARNESS_LOG_LEVEL='INFO'; "
              f"Start-Process -FilePath '{EXE}' | Out-Null; Start-Sleep -Seconds 14; "
              "(Get-Process -Name hsr-partner-harness -ErrorAction SilentlyContinue | "
              "Select-Object -First 1 -ExpandProperty Id)")


def write_env(base_url: str) -> None:
    text = ENV_BACKUP.read_text(encoding="utf-8")
    lines = []
    for line in text.splitlines():
        if line.startswith("PAIR_HARNESS_DIALOGUE_BASE_URL="):
            lines.append(f"PAIR_HARNESS_DIALOGUE_BASE_URL={base_url}")
        else:
            lines.append(line)
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def wait_port(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            return True
        except OSError:
            await asyncio.sleep(1.5)
    return False


async def main_dns() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}

    log["env_before"] = ENV_FILE.read_text(encoding="utf-8").splitlines()[0]
    write_env(DNS_HOST)
    log["env_injected"] = DNS_HOST
    log["stop_before_inject"] = stop_candidate()
    log["start_with_dns"] = start_candidate()
    log["sidecar_ready"] = await wait_port(8765, 75.0)

    if log["sidecar_ready"]:
        session = Harness(WS_URL, token, frames_log=out / "ws-frames-dns.log",
                          events_log=out / "events-dns.log", device_name="r2-dns")
        await session.connect()
        try:
            bootstrap = await session.call("app.bootstrap", timeout=30)
            log["account"] = bootstrap.get("current_account_id")
            log["effective_config"] = await safe(session, "config.get", {})
            project = next((p for p in (bootstrap.get("projects") or [])
                            if p.get("root_path", "").endswith("r2-chain-project")), None)
            project_id = (project or {}).get("project_id")
            if project_id is None:
                created = await session.call("project.create", {
                    "root_path": PROJECT_ROOT, "name": "r2-chain-project",
                    "pair_id": PAIR_A}, timeout=30)
                project_id = next(p["project_id"] for p in created["projects"]
                                  if p.get("name") == "r2-chain-project")
            created = await session.call("conversation.create", {
                "project_id": project_id, "pair_id": PAIR_A,
                "title": "R2-B01-dns"}, timeout=30)
            conversation_id = created["current_conversation_id"]
            log["conversation_id"] = conversation_id
            started = time.monotonic()
            log["submit"] = await safe(session, "chat.submit", {
                "conversation_id": conversation_id, "target": "character",
                "text": "复测 B-01 解析形态：请只回复两个字：解析。"}, timeout=60)
            snapshot = await wait_turn(session, conversation_id, timeout=180)
            log["elapsed_seconds"] = round(time.monotonic() - started, 2)
            log["turn"] = summarize(snapshot)
        finally:
            await session.close()
    else:
        log["note"] = "候选未能以保留域端点进入可用运行态"

    write_env(REAL_HOST)
    log["stop_before_restore"] = stop_candidate()
    log["start_after_restore"] = start_candidate()
    log["ready_after_restore"] = await wait_port(8765, 75.0)
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
    print(json.dumps(log, ensure_ascii=False, indent=2)[:6000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_dns()))
