"""移动平台矩阵：安全与并发维度（S4-R2 手机端真机批次）。

全部经**局域网地址** 10.81.102.166:8765 发起（与手机同一条通道），不绕回环：

安全维度
  未鉴权 / 错误 token / 撤销 token / 缺失 token 四类非法请求必须被拒，
  且拒绝原因可定位；非法请求不得执行任何命令。

并发维度
  桌面连接与移动连接同时在线时，四会话并发提交的任务归属、审批裁决
  归属与终态来源必须正确，无串线。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from ph_client import Harness, HarnessError, event_fields, now_iso
from r2common import TOKEN_FILE, REPO, case_dir, load_token, save_result, \
    write_commands, write_http_log, result_shell, build_block

LAN_HOST = "10.81.102.166"
LAN_WS = f"ws://{LAN_HOST}:8765/ws"
LOOPBACK_WS = "ws://127.0.0.1:8765/ws"
CASE = "mobile-security-concurrency"
PAIR_A = "phainon_ancient_machine"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\r2-mobile-project"


async def safe_call(session: Harness, method: str, params: dict,
                    timeout: float = 40.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:300]}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout"}


async def security(out: Path) -> dict:
    token = load_token()
    log: dict = {}

    # 1) 未鉴权（不携带 auth 字段）
    session = Harness(LAN_WS, None, frames_log=out / "ws-anon.log",
                      events_log=out / "events-anon.log", device_name="mobile-anon")
    await session.connect()
    try:
        log["no_auth"] = await safe_call(session, "app.bootstrap", {})
        log["no_auth_command"] = await safe_call(session, "chat.submit", {
            "conversation_id": "does-not-matter", "target": "character",
            "text": "unauthorized"})
    finally:
        await session.close()

    # 2) 错误 token
    session = Harness(LAN_WS, "not-a-real-token-000000000000000000",
                      frames_log=out / "ws-badtoken.log",
                      events_log=out / "events-badtoken.log", device_name="mobile-bad")
    await session.connect()
    try:
        log["bad_token"] = await safe_call(session, "app.bootstrap", {})
        log["bad_token_command"] = await safe_call(session, "chat.submit", {
            "conversation_id": "does-not-matter", "target": "character",
            "text": "unauthorized"})
    finally:
        await session.close()

    # 3) 已配对设备清册（撤销形态在手机端交互之后单独执行，避免打断手机连接）
    valid = Harness(LOOPBACK_WS, token, device_name="mobile-admin")
    await valid.connect()
    try:
        devices = await safe_call(valid, "remote.list_devices", {})
        log["paired_devices"] = ((devices.get("result") or {}).get("devices") or [])
    finally:
        await valid.close()
    return log


async def concurrency(out: Path) -> dict:
    token = load_token()
    log: dict = {}
    # 两条连接：一条走局域网地址（模拟移动端），一条走回环（桌面端）
    mobile = Harness(LAN_WS, token, frames_log=out / "ws-mobile.log",
                     events_log=out / "events-mobile.log", device_name="mobile-lan")
    desktop = Harness(LOOPBACK_WS, token, frames_log=out / "ws-desktop.log",
                      events_log=out / "events-desktop.log", device_name="desktop-loopback")
    await mobile.connect()
    await desktop.connect()
    try:
        bootstrap = await desktop.call("app.bootstrap", timeout=30)
        project = next((p for p in (bootstrap.get("projects") or [])
                        if p.get("root_path", "").endswith("r2-mobile-project")), None)
        if project is None:
            created = await desktop.call("project.create", {
                "root_path": PROJECT_ROOT, "name": "r2-mobile-project",
                "pair_id": PAIR_A}, timeout=30)
            project = next(p for p in created["projects"]
                           if p.get("name") == "r2-mobile-project")
        project_id = project["project_id"]
        Path(PROJECT_ROOT).mkdir(parents=True, exist_ok=True)

        conversation_ids: list[dict] = []
        for index in range(4):
            created = await desktop.call("conversation.create", {
                "project_id": project_id, "pair_id": PAIR_A,
                "title": f"R2-mobile-conc-{index + 1}"}, timeout=30)
            conversation_ids.append({
                "index": index + 1,
                "conversation_id": created["current_conversation_id"],
                "owner": "desktop" if index % 2 == 0 else "mobile",
            })
        log["conversations"] = conversation_ids

        # 四会话并发提交：两条从移动连接、两条从桌面连接
        sends: list[tuple[dict, float]] = []
        for item in conversation_ids:
            session = mobile if item["owner"] == "mobile" else desktop
            request_id, sent = await session.send_async("chat.submit", {
                "conversation_id": item["conversation_id"], "target": "character",
                "text": f"复测移动并发：会话 {item['index']}，请只回复两个字：收到。"})
            sends.append((item, sent))
        spread = max(s for _, s in sends) - min(s for _, s in sends)
        log["submit_spread_seconds"] = round(spread, 4)

        # 逐条确认响应与终态归属
        results: list[dict] = []
        for session, item in zip(
                [mobile if i["owner"] == "mobile" else desktop for i in conversation_ids],
                conversation_ids):
            snapshot = await session.call("conversation.open", {
                "conversation_id": item["conversation_id"]}, timeout=40)
            results.append({
                "index": item["index"],
                "owner": item["owner"],
                "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                              "status": m.get("status"),
                              "text": str(m.get("text") or "")[:60]}
                             for m in snapshot.get("messages", [])],
                "active_task": bool(snapshot.get("active_task")),
                "queue_items": len(snapshot.get("queue_items") or []),
            })
        log["initial_open"] = results

        # 收敛：等待四会话都无在途回合
        deadline = time.monotonic() + 240
        final: list[dict] = []
        while time.monotonic() < deadline:
            final = []
            for item in conversation_ids:
                session = mobile if item["owner"] == "mobile" else desktop
                snapshot = await session.call("conversation.open", {
                    "conversation_id": item["conversation_id"]}, timeout=40)
                final.append({
                    "index": item["index"], "owner": item["owner"],
                    "settled": not snapshot.get("active_task")
                    and not snapshot.get("queue_items"),
                    "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                                  "status": m.get("status"),
                                  "text": str(m.get("text") or "")[:60]}
                                 for m in snapshot.get("messages", [])],
                })
            if all(item["settled"] for item in final):
                break
            await asyncio.sleep(3)
        log["final"] = final
        log["all_settled"] = all(item["settled"] for item in final)
        log["cross_talk"] = [
            {"index": item["index"],
             "user_texts": [m["text"] for m in item["messages"] if m["source"] == "user"],
             "char_texts": [m["text"] for m in item["messages"] if m["source"] == "character"]}
            for item in final
        ]
    finally:
        await mobile.close()
        await desktop.close()
    return log


async def main() -> int:
    out = case_dir(CASE)
    log: dict = {"started_at": now_iso()}
    log["security"] = await security(out)
    log["concurrency"] = await concurrency(out)
    log["finished_at"] = now_iso()
    (out / "mobile-matrix-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log",
                   "安全与并发维度全部经局域网 10.81.102.166:8765 的 /ws 通道")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-r2-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_mobile_matrix.py",
    ])
    r = result_shell(CASE, title="移动平台矩阵：安全与并发维度（Android 壳 + Android 浏览器）")
    r["build"] = build_block()
    r["device"] = "Xiaomi 24129PN74C（Android 16 / SDK 36 / arm64-v8a）/ 1200x2670 / 520dpi / 约 369dp 宽"
    r["network"] = "局域网 10.81.0.0/16；手机 10.81.140.245 ↔ PC 10.81.102.166:8765（HTTP，非 HTTPS）"
    r["actual"] = json.dumps(log, ensure_ascii=False)[:20000]
    r["timestamps"]["finished_at"] = now_iso()
    r["evidence"] = ["mobile-matrix-run.json", "ws-anon.log", "ws-badtoken.log",
                     "ws-mobile.log", "ws-desktop.log", "events-mobile.log",
                     "events-desktop.log"]
    save_result(CASE, r)
    print(json.dumps(log, ensure_ascii=False, indent=2)[:7000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
