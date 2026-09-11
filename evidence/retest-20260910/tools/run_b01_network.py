"""B-01 子项复测：A06 断网注入（进程级网络沙盒）。

用 §4.1 的进程级沙盒把候选出站流量引到本机 TCP 转发器，按形态注入真实故障，
核对「错误可定位、失败如实暴露、隐藏内容不进入普通对话」：

| 形态 | 沙盒动作 | 期望 |
| --- | --- | --- |
| forward | 正常隧道 | 真实回合成功（同时证明候选确实经代理出站） |
| reject | 停止监听 | 连接阶段失败，失败原因可见 |
| cut | 已建立隧道 abort | 传输阶段中断，失败原因可见 |
| hang | 接受 CONNECT 但不建上游 | 请求悬挂至客户端超时 |

名称解析失败形态由 `run_b01_dns.ps1` 在重启候选后单独注入（不经代理直连保留域）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso
from r1common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell,
)

CASE = "B-01"
CONTROL = ("127.0.0.1", 8768)
PAIR_A = "phainon_ancient_machine"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-project"
SANDBOX_LOG = Path(__file__).resolve().parents[1] / "B-01" / "sandbox.injection.log"


async def control(command: str) -> str:
    reader, writer = await asyncio.open_connection(*CONTROL)
    try:
        writer.write((command + "\n").encode())
        await writer.drain()
        return (await reader.readline()).decode().strip()
    finally:
        writer.close()


def sandbox_events_since(offset: int) -> tuple[list[dict], int]:
    """读取沙盒日志中新增的事件。"""
    if not SANDBOX_LOG.exists():
        return [], offset
    lines = SANDBOX_LOG.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[offset:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out, len(lines)


async def safe(session: Harness, method: str, params: dict, timeout: float = 60.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:300]}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout"}


async def wait_turn(session: Harness, conversation_id: str, timeout: float = 150.0) -> dict:
    """等待本会话出现角色/系统终态（每个形态独立会话，因此不存在历史消息干扰）。"""
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


def summarize(snapshot: dict) -> dict:
    messages = snapshot.get("messages", [])
    return {
        "message_count": len(messages),
        "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                      "status": m.get("status"),
                      "text": str(m.get("text") or "")[:400]}
                     for m in messages],
        "failure_notice": next(
            (str(m.get("text")) for m in messages
             if m.get("source") == "system" and "失败" in str(m.get("text") or "")), None),
    }


async def run_injection(session: Harness, project_id: str, label: str,
                        action: str, prompt: str, *, cut_after: float | None = None,
                        timeout: float = 150.0) -> dict:
    """在**独立新会话**里注入一种故障形态（避免历史消息干扰终态判定）。"""
    offset = len(SANDBOX_LOG.read_text(encoding="utf-8").splitlines()) if SANDBOX_LOG.exists() else 0
    created = await session.call("conversation.create", {
        "project_id": project_id, "pair_id": PAIR_A, "title": f"R1-B01-{label}"},
        timeout=30)
    conversation_id = created["current_conversation_id"]
    started = time.monotonic()
    control_reply = await control(action)
    submit = await safe(session, "chat.submit", {
        "conversation_id": conversation_id, "target": "character", "text": prompt},
        timeout=60)
    if cut_after is not None:
        await asyncio.sleep(cut_after)
        cut_reply = await control("CUT")
    else:
        cut_reply = None
    snapshot = await wait_turn(session, conversation_id, timeout=timeout)
    events, _ = sandbox_events_since(offset)
    result = {
        "label": label,
        "conversation_id": conversation_id,
        "sandbox_action": action,
        "control_reply": control_reply,
        "cut_reply": cut_reply,
        "submit": submit,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "turn": summarize(snapshot),
        "sandbox_events": [{"event": e.get("event"), "mode": e.get("mode"),
                            "request": e.get("request"), "error": e.get("error")}
                           for e in events],
    }
    # 还原为 forward，避免影响下一形态
    await control("SET forward")
    return result


async def main() -> int:
    out = case_dir(CASE)
    result = result_shell(CASE, title="断网注入（进程级网络沙盒）与错误可定位性复验")
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="r1-network")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next((p for p in (bootstrap.get("projects") or [])
                        if p.get("root_path", "").endswith("retest-project")), None)
        project_id = (project or {}).get("project_id")
        if project_id is None:
            created = await session.call("project.create", {
                "root_path": PROJECT_ROOT, "name": "retest-project", "pair_id": PAIR_A},
                timeout=30)
            project_id = next(p["project_id"] for p in created["projects"]
                              if p.get("name") == "retest-project")
        conversation = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A, "title": "R1-B01-warmup"},
            timeout=30)
        log["conversation_id"] = conversation["current_conversation_id"]
        log["proxy_env"] = {
            "HTTPS_PROXY": "http://127.0.0.1:8767",
            "NO_PROXY": "127.0.0.1,localhost",
            "note": "候选 EXE 及其 Sidecar 在启动时继承该环境（复测计划 §4.1）",
        }
        del conversation

        # 1. forward：证明候选真的经代理出站，且真实回合可用
        log["forward_baseline"] = await run_injection(
            session, project_id, "forward 基线", "SET forward",
            "复测 B-01：请只回复两个字：通路。")

        # 2. reject：连接被拒
        log["reject"] = await run_injection(
            session, project_id, "连接被拒", "SET reject",
            "复测 B-01：请只回复两个字：拒绝。")

        # 3. cut_soon：隧道建立后由沙盒在传输过程中自动切断（响应流必然中断）
        log["cut"] = await run_injection(
            session, project_id, "传输中断", "SET cut_soon 256",
            "复测 B-01：请只回复两个字：中断。")

        # 4. hang：请求悬挂至客户端超时
        log["hang"] = await run_injection(
            session, project_id, "请求悬挂", "SET hang",
            "复测 B-01：请只回复两个字：悬挂。", timeout=120.0)
    finally:
        await control("SET forward")
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        write_info_log(CASE, (out / "sidecar.log").read_text(encoding="utf-8").splitlines())
    except OSError:
        pass
    (out / "network-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log",
                   "B-01 业务交互走 WS 帧；出站经本机沙盒代理 127.0.0.1:8767")
    write_commands(out / "commands.ps1", [
        "# 1) 启动沙盒",
        "python evidence/retest-20260910/tools/net_sandbox.py --listen 8767 "
        "--upstream api.deepseek.com:443 --control 8768 --log <log>",
        "# 2) 以代理环境启动候选",
        "$env:HTTPS_PROXY='http://127.0.0.1:8767'; $env:NO_PROXY='127.0.0.1,localhost'",
        "$env:PAIR_HARNESS_LOG_LEVEL='INFO'",
        "Start-Process desktop/src-tauri/target/release/hsr-partner-harness.exe",
        "# 3) 注入",
        "python evidence/retest-20260910/tools/run_b01_network.py",
    ])
    result["status"] = "待判定"
    result["actual"] = json.dumps({
        k: log[k] for k in ("forward_baseline", "reject", "cut", "hang")},
        ensure_ascii=False)[:5000]
    result["timestamps"]["finished_at"] = now_iso()
    result["evidence"] = ["network-run.json", "ws-frames.log", "events.log",
                          "sidecar.log", "sandbox.injection.log"]
    save_result(CASE, result)
    print(json.dumps(log, ensure_ascii=False, indent=2)[:6000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
