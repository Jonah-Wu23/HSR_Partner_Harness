"""A14 补充：在途请求被真实切断（先确认请求已达服务端，再断链）。

判定链：
1. 经本机 TCP 代理提交 chat.submit；
2. 用另一条直连确认该用户消息已落库（证明请求已达服务端）；
3. 立即切断代理链路——发起方永久收不到该请求的响应；
4. 直连轮询：该消息仍应恰好一条，且角色回复在链路断开的情况下照常完成；
5. 重连后新 turn 仍然成功（等到角色回复真正出现，不做过早判定）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from ph_client import Harness, now_iso
from run_a14 import PROXY_PORT, TcpProxy
from s4common import WS_URL, case_dir, load_token, sidecar_log_mark, sidecar_tail

CASE = "A14"


async def wait_reply(session: Harness, conversation_id: str, marker: str,
                     *, timeout: float = 120.0) -> dict:
    """轮询到出现针对 marker 这条用户消息的角色回复为止。"""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        last = await session.call("conversation.open",
                                  {"conversation_id": conversation_id}, timeout=30)
        user_index = None
        for index, message in enumerate(last.get("messages", [])):
            if message.get("source") == "user" and marker in str(message.get("text", "")):
                user_index = index
        if user_index is not None:
            for message in last.get("messages", [])[user_index + 1:]:
                if message.get("source") == "character" and message.get("status") == "done":
                    return last
        await asyncio.sleep(1.0)
    return last


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso(), "phase": "in-flight-cut-v2"}

    proxy = TcpProxy(PROXY_PORT)
    await proxy.start()
    proxied = Harness(f"ws://127.0.0.1:{PROXY_PORT}/ws", token,
                      frames_log=out / "ws-frames-inflight.log", device_name="s4-a14-inflight")
    direct = Harness(WS_URL, token, device_name="s4-a14-direct-observer")
    await proxied.connect()
    await direct.connect()
    try:
        baseline = await direct.call("app.bootstrap", timeout=20)
        project = next(p for p in (baseline.get("projects") or []) if p.get("name") == "project-alpha")
        created = await proxied.call(
            "conversation.create",
            {"project_id": project["project_id"], "pair_id": "march7_fourth_mirror",
             "title": "A14-inflight2"}, timeout=30)
        conversation_id = created["current_conversation_id"]
        log["conversation_id"] = conversation_id

        marker = "A14-INFLIGHT2"
        request_id, sent_mono = await proxied.send_async(
            "chat.submit",
            {"conversation_id": conversation_id, "target": "character",
             "text": f"{marker} 只回复一个词：断"})

        # 确认请求已达服务端（用户消息已落库）后再断链
        reached = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            snapshot = await direct.call("conversation.open",
                                         {"conversation_id": conversation_id}, timeout=20)
            if any(marker in str(m.get("text", "")) for m in snapshot.get("messages", [])):
                reached = True
                break
            await asyncio.sleep(0.05)
        log["request_reached_server_before_cut"] = reached
        log["cut_delay_ms"] = round((time.monotonic() - sent_mono) * 1000, 3)
        if not reached:
            log["note"] = "请求未达服务端即被切断；本轮不作为在途切断证据"
        await proxy.cut()

        outcome = None
        try:
            await proxied.wait_response(request_id, timeout=12)
            outcome = {"accepted": True}
        except asyncio.TimeoutError:
            outcome = {"accepted": False, "code": "client_timeout_no_response"}
        except Exception as exc:  # noqa: BLE001 - 链路中断可能以连接错误形式出现
            outcome = {"accepted": False, "code": type(exc).__name__, "message": str(exc)}
        log["in_flight_outcome"] = outcome
        print("in-flight:", json.dumps(outcome, ensure_ascii=False), flush=True)
        await proxied.close()

        # 链路已断：服务端侧该消息与回复应照常完成
        settled = await wait_reply(direct, conversation_id, marker, timeout=120)
        texts = [m.get("text") for m in settled.get("messages", [])]
        log["server_side_after_cut"] = {
            "texts": texts,
            "marker_count": sum(1 for t in texts if isinstance(t, str) and marker in t),
            "character_finals": [m.get("text") for m in settled.get("messages", [])
                                 if m.get("source") == "character" and m.get("status") == "done"],
            "active_task": settled.get("active_task"),
            "turns": settled.get("turns"),
        }

        # 重连后新 turn
        await direct.call(
            "chat.submit",
            {"conversation_id": conversation_id, "target": "character",
             "text": "A14-INFLIGHT2-RECOVERED 只回复一个词：续"}, timeout=30)
        second = await wait_reply(direct, conversation_id, "A14-INFLIGHT2-RECOVERED", timeout=120)
        log["new_turn_after_link_loss"] = {
            "texts": [m.get("text") for m in second.get("messages", [])],
            "character_finals": [m.get("text") for m in second.get("messages", [])
                                 if m.get("source") == "character" and m.get("status") == "done"],
        }
        print(json.dumps(log["new_turn_after_link_loss"], ensure_ascii=False), flush=True)
    finally:
        await direct.close()
        await proxied.close()
        await proxy.stop()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar-inflight.log")
    (out / "a14-inflight.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("A14 in-flight (v2) finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
