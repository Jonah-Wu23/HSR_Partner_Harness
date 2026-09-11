"""复测批次启动探测：确认候选在线、bootstrap 结构、模式自报与可用装配。

只读，不产生真实模型调用。用于开测前核对 002 的模式自报字段（demo/mode_source）
与后续脚本需要的 id（账号/项目/pair/角色卡）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ph_client import Harness, now_iso
from r1common import (
    WS_URL,
    case_dir,
    load_token,
    process_table,
    sidecar_log_mark,
    sidecar_tail,
    write_info_log,
    write_commands,
)


async def main() -> int:
    out = case_dir("00-precheck")
    try:
        token = load_token()
        report_token = True
    except OSError:
        token = None  # 尚未配对：先验证免鉴权命令与 bootstrap 可用性
        report_token = False
    report = {"has_token": report_token}
    sidecar_log_mark()
    report: dict = {"started_at": now_iso()}
    report = dict(report)
    report["has_token"] = report_token
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="r1-probe")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        report["backend"] = bootstrap.get("backend")
        report["backend_info"] = bootstrap.get("backend_info") or bootstrap.get("backendInfo")
        report["current_account_id"] = bootstrap.get("current_account_id")
        report["projects"] = [
            {k: p.get(k) for k in ("project_id", "name", "root_path", "archived")}
            for p in (bootstrap.get("projects") or [])
        ]
        report["conversations"] = [
            {k: c.get(k) for k in ("conversation_id", "title", "pair_id", "project_id")}
            for c in (bootstrap.get("conversations") or [])
        ]
        report["pairs"] = bootstrap.get("pairs")
        report["accounts"] = bootstrap.get("accounts")
        report["voice"] = bootstrap.get("voice")
        report["bootstrap_top_level_keys"] = sorted(bootstrap.keys())
        report["cards"] = await session.call("card.list", timeout=30)
        report["config"] = await session.call("config.get", timeout=30)
        report["processes"] = process_table()
        report["ok"] = True
    except Exception as exc:  # noqa: BLE001 - 探测失败如实记录
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await session.close()
    report["finished_at"] = now_iso()
    report["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        full = (Path(out / "sidecar.log")).read_text(encoding="utf-8").splitlines()
        write_info_log("00-precheck", full)
    except OSError:
        pass
    (out / "probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' probe.py",
    ])
    print(json.dumps(report, ensure_ascii=False, indent=2)[:3000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
