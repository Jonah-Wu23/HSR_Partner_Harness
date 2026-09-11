"""B-01 「传输中断」形态重采（第二版）：响应下行满 256 字节即刻切断。

第一版两个问题：
- `SET cut_soon 256` 的 1 秒兜底先于字节阈值触发，隧道在响应到达前就被
  abort，客户端只看到连接阶段错误（ConnectError），与「连接被拒」同形；
- 改成「forward 放行 + 固定秒数后 CUT」后，DeepSeek 在这次提示词下 6 秒内
  就完成了整条回复，CUT 落在回复**之后**，回合成功。

本版把沙盒兜底延迟放大到 60 秒（`--cut-delay 60`），让唯一的触发条件变成
「响应已下行 256 字节」——此时连接必然处于**传输过程中**，中断落在真实流上。
"""

from __future__ import annotations

import asyncio
import json
import sys

from ph_client import Harness
from r2common import WS_URL, case_dir, load_token, write_commands
from run_b01_network import PAIR_A, PROJECT_ROOT, control, run_injection


async def main() -> int:
    out = case_dir("B-01")
    token = load_token()
    log: dict = {}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames-cut2.log",
                      events_log=out / "events-cut2.log", device_name="r2-cut2")
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
        log["cut_after_bytes"] = await run_injection(
            session, project_id, "传输中断（下行 256 字节后）", "SET cut_soon 256",
            "复测 B-01：请写一段三百字左右的说明，讲清楚什么是传输中断、"
            "它和连接被拒有什么区别、遇到之后应该怎么排查。",
            timeout=150.0)
    finally:
        await control("SET forward")
        await session.close()
    (out / "cut-retry2-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands-cut-retry2.ps1", [
        "# 沙盒以 --cut-delay 60 启动，唯一触发条件是响应下行 256 字节",
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-r2-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_b01_cut_retry2.py",
    ])
    print(json.dumps(log, ensure_ascii=False, indent=2)[:4000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
