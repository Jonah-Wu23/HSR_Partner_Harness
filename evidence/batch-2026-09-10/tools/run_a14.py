"""A14：鉴权失败（错误/缺失/撤销 token）与网络中断恢复（协议级 + Windows 操作）。

覆盖：
1. 错误 token / 缺失 token → 业务命令被拒（unauthorized）；
2. 撤销 token → 已建立连接被服务端以 4401 断开，后续请求被拒；
3. 网络中断 → 用本机 TCP 代理切断已建立的 WS 连接，验证服务端清理与客户端恢复；
4. 恢复后新 turn 成功（避免重复消息）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import aiohttp

from ph_client import Harness, HarnessError, event_fields, now_iso, pair
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
PROXY_PORT = 8766


class TcpProxy:
    """极简 TCP 转发，用于制造"链路被切断"的真实网络事件。"""

    def __init__(self, listen_port: int, target_port: int = 8765) -> None:
        self.listen_port = listen_port
        self.target_port = target_port
        self._server: asyncio.AbstractServer | None = None
        self._tasks: set[asyncio.Task] = set()
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.listen_port)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", self.target_port)
        except OSError:
            writer.close()
            return
        self._writers.add(upstream_writer)

        async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await src.read(65536)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except (OSError, asyncio.CancelledError):
                pass
            finally:
                try:
                    dst.close()
                except OSError:
                    pass

        for src, dst in ((reader, upstream_writer), (upstream_reader, writer)):
            task = asyncio.create_task(pump(src, dst))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def cut(self) -> None:
        """切断全部已建立连接，模拟链路中断。"""
        for writer in list(self._writers):
            try:
                writer.transport.abort()
            except (OSError, AttributeError):
                pass
        self._writers.clear()

    async def stop(self) -> None:
        await self.cut()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso(), "steps": {}}

    # —— 1. 错误 token / 缺失 token ——
    bad_log = out / "ws-frames-bad-token.log"
    for label, bad_token in (("wrong_token", "s4-invalid-token-0001"), ("missing_token", None)):
        session = Harness(WS_URL, bad_token, frames_log=bad_log if label == "wrong_token" else out / "ws-frames-no-token.log",
                          device_name=f"s4-a14-{label}")
        await session.connect()
        try:
            await session.call("app.bootstrap", timeout=20)
            outcome = {"accepted": True}
        except HarnessError as exc:
            outcome = {"accepted": False, "code": exc.code, "message": exc.message}
        except asyncio.TimeoutError:
            outcome = {"accepted": False, "code": "client_timeout"}
        log["steps"][label] = outcome
        print(label, json.dumps(outcome, ensure_ascii=False), flush=True)
        await session.close()

    # —— 2. 撤销 token ——
    controller = Harness(WS_URL, token, frames_log=out / "ws-frames-controller.log",
                         events_log=out / "events-controller.log", device_name="s4-a14-controller")
    await controller.connect()
    victim_token = ""
    victim = None
    revoked_close: dict = {}
    try:
        issued = await controller.call("remote.issue_code", {}, timeout=20)
        code = issued["code"]
        victim_token, err = await pair(WS_URL, code, "s4-a14-revoke")
        if not victim_token:
            log["steps"]["revoke"] = {"status": "pair_failed", "error": err}
        else:
            victim = Harness(WS_URL, victim_token, frames_log=out / "ws-frames-victim.log",
                             events_log=out / "events-victim.log", device_name="s4-a14-revoke")
            await victim.connect()
            live = await victim.call("app.bootstrap", timeout=20)
            log["steps"]["revoke"] = {
                "paired": True,
                "live_call_ok": bool(live),
                "token_sha_hint": __import__("hashlib").sha256(victim_token.encode()).hexdigest()[:16],
            }
            devices_before = await controller.call("remote.list_devices", {}, timeout=20)
            log["steps"]["revoke"]["devices_before"] = devices_before.get("devices")
            revoke_result = await controller.call(
                "remote.revoke", {"device_name": "s4-a14-revoke"}, timeout=20)
            log["steps"]["revoke"]["revoke_result"] = revoke_result

            # 服务端应主动断开仍以该 token 鉴权的连接
            try:
                message = await asyncio.wait_for(victim._ws.receive(), timeout=15)
                revoked_close = {
                    "type": str(message.type),
                    "extra": getattr(message, "extra", None),
                    "data": message.data if isinstance(message.data, str) else None,
                }
            except asyncio.TimeoutError:
                revoked_close = {"type": "no_close_observed_within_15s"}
            log["steps"]["revoke"]["connection_close"] = revoked_close

            after = Harness(WS_URL, victim_token, frames_log=out / "ws-frames-revoked-retry.log",
                            device_name="s4-a14-revoked-retry")
            await after.connect()
            try:
                await after.call("app.bootstrap", timeout=20)
                log["steps"]["revoke"]["after_revoke_call"] = {"accepted": True}
            except HarnessError as exc:
                log["steps"]["revoke"]["after_revoke_call"] = {
                    "accepted": False, "code": exc.code, "message": exc.message}
            await after.close()
            devices_after = await controller.call("remote.list_devices", {}, timeout=20)
            log["steps"]["revoke"]["devices_after"] = devices_after.get("devices")
    finally:
        if victim is not None:
            await victim.close()

    # —— 3. 网络中断（本机 TCP 代理被切断） ——
    proxy = TcpProxy(PROXY_PORT)
    await proxy.start()
    proxied = Harness(f"ws://127.0.0.1:{PROXY_PORT}/ws", token,
                      frames_log=out / "ws-frames-proxy.log", device_name="s4-a14-proxy")
    await proxied.connect()
    try:
        baseline = await proxied.call("app.bootstrap", timeout=20)
        project = next(p for p in (baseline.get("projects") or []) if p.get("name") == "project-alpha")
        created = await proxied.call(
            "conversation.create",
            {"project_id": project["project_id"], "pair_id": "firefly_sam",
             "title": "A14-netcut"}, timeout=30)
        conversation_id = created["current_conversation_id"]
        log["steps"]["network_cut"] = {"conversation_id": conversation_id}

        before = await proxied.call("conversation.open",
                                    {"conversation_id": conversation_id}, timeout=30)
        log["steps"]["network_cut"]["messages_before"] = len(before.get("messages") or [])

        # 在途请求中切断链路
        request_id, _sent = await proxied.send_async(
            "chat.submit",
            {"conversation_id": conversation_id, "target": "character",
             "text": "A14-NETCUT 只回复一个词：链"})
        await asyncio.sleep(0.3)
        await proxy.cut()
        in_flight = None
        try:
            await proxied.wait_response(request_id, timeout=20)
            in_flight = {"accepted": True}
        except HarnessError as exc:
            in_flight = {"accepted": False, "code": exc.code, "message": exc.message}
        except asyncio.TimeoutError:
            in_flight = {"accepted": False, "code": "client_timeout_after_cut"}
        log["steps"]["network_cut"]["in_flight_request"] = in_flight
        print("network cut in-flight:", json.dumps(in_flight, ensure_ascii=False), flush=True)
        await proxied.close()

        # 恢复：直连重新建立会话，核对无重复消息，并跑通新 turn
        recovered = Harness(WS_URL, token, frames_log=out / "ws-frames-recovered.log",
                            events_log=out / "events-recovered.log", device_name="s4-a14-recovered")
        await recovered.connect()
        try:
            after_open = await recovered.call("conversation.open",
                                              {"conversation_id": conversation_id}, timeout=30)
            texts = [m.get("text") for m in (after_open.get("messages") or [])]
            log["steps"]["network_cut"]["messages_after"] = len(texts)
            log["steps"]["network_cut"]["texts_after"] = texts
            log["steps"]["network_cut"]["duplicate_markers"] = sum(
                1 for t in texts if isinstance(t, str) and "A14-NETCUT" in t)

            await recovered.call(
                "chat.submit",
                {"conversation_id": conversation_id, "target": "character",
                 "text": "A14-RECOVERED 只回复一个词：复"}, timeout=30)
            deadline = time.monotonic() + 120
            final = {}
            while time.monotonic() < deadline:
                final = await recovered.call("conversation.open",
                                             {"conversation_id": conversation_id}, timeout=30)
                pending = [m for m in final.get("messages", [])
                           if m.get("status") in {"pending", "streaming", "processing"}]
                if not pending and not final.get("active_task"):
                    break
                await asyncio.sleep(1.0)
            log["steps"]["network_cut"]["new_turn"] = {
                "texts": [m.get("text") for m in (final.get("messages") or [])],
                "character_final": [
                    m.get("text") for m in (final.get("messages") or [])
                    if m.get("source") == "character" and m.get("status") == "done"
                ],
                "active_task": final.get("active_task"),
            }
        finally:
            await recovered.close()
    finally:
        await proxied.close()
        await proxy.stop()

    await controller.close()
    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    (out / "a14-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a14.py",
    ])
    write_http_log(out / "http.log", "A14 鉴权与断网：WS 帧 + 本机 TCP 代理断链")
    print("A14 finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
