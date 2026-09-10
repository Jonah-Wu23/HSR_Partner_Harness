"""B-01 「传输中断」形态重采：隧道先放行、响应开始流式后再 CUT。

首轮用 `SET cut_soon 256`，沙盒的 1 秒兜底（cut_delay）先于 256 字节触发，
隧道在响应到达前就被 abort，客户端看到的是连接阶段错误（ConnectError），
与「连接被拒」不可区分——这不构成有效的「传输阶段中断」证据。

本脚本改为：forward 放行 → 等 `cut_after` 秒让响应开始下行 → CUT，
使中断落在**已建立连接的传输过程中**。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ph_client import Harness
from r2common import WS_URL, case_dir, load_token, save_result, write_commands, result_shell
from run_b01_network import PAIR_A, PROJECT_ROOT, control, run_injection


async def main() -> int:
    out = case_dir("B-01")
    token = load_token()
    log: dict = {}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames-cut.log",
                      events_log=out / "events-cut.log", device_name="r2-cut")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next((p for p in (bootstrap.get("projects") or [])
                        if p.get("root_path", "").endswith("r2-chain-project")), None)
        project_id = (project or {}).get("project_id")
        if project_id is None:
            created = await session.call("project.create", {
                "root_path": PROJECT_ROOT, "name": "r2-chain-project", "pair_id": PAIR_A},
                timeout=30)
            project_id = next(p["project_id"] for p in created["projects"]
                              if p.get("name") == "r2-chain-project")
        log["cut_midstream"] = await run_injection(
            session, project_id, "传输中断（流式中途）", "SET forward",
            "复测 B-01：请写一段两百字左右的短文，说明什么是传输中断。",
            cut_after=6.0, timeout=150.0)
    finally:
        await control("SET forward")
        await session.close()
    (out / "cut-retry-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands-cut-retry.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-r2-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_b01_cut_retry.py",
    ])
    print(json.dumps(log, ensure_ascii=False, indent=2)[:4000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
