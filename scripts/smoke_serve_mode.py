"""V0.3.3 批 4 真实进程冒烟：--serve 模式下真实 Sidecar 进程全链路。

验证点（对照 workplan 第 7 节与计划文档 V0.3.3 集成验收）：
1. 真实进程以 --demo --serve 启动，stdin 循环与 WS 服务器并行运行。
2. stdin JSONL 请求正常收 response（stdout 路径不受 --serve 影响）。
3. WS 未鉴权命令被拒；remote.issue_code（stdin）→ remote.pair（WS）→ token；
   带 token 的 app.bootstrap 在 WS 上成功。
4. 事件（backend.ready 等）同时出现在 stdout 与已鉴权 WS 连接。
5. 退出路径干净（app.shutdown 后进程退出码 0），无端口残留。
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _safe_json(line: str) -> dict:
    try:
        value = json.loads(line)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    port = free_port()
    data_dir = Path(tempfile.mkdtemp(prefix="v033-smoke-"))
    proc = subprocess.Popen(
        [
            str(PY),
            "-m",
            "pair_harness.desktop_backend",
            "--demo",
            "--serve",
            str(port),
            "--data-dir",
            str(data_dir),
            "--project",
            str(data_dir),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )

    stdout_lines: list[str] = []
    reader_done = threading.Event()

    def read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_lines.append(line.rstrip("\n"))
        reader_done.set()

    threading.Thread(target=read_stdout, daemon=True).start()

    def send_stdin(obj: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def wait_response(request_id: str, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for line in stdout_lines:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if message.get("kind") == "response" and message.get("id") == request_id:
                    return message
            time.sleep(0.05)
        raise AssertionError(f"stdin 响应超时：{request_id}，已收到 {len(stdout_lines)} 行")

    failures: list[str] = []

    async def ws_phase(code: str) -> str:
        session = aiohttp.ClientSession()
        token = ""
        try:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/ws")

            # 未鉴权命令被拒
            await ws.send_json(
                {"kind": "request", "id": "w1", "method": "app.bootstrap", "params": {}}
            )
            msg = json.loads((await asyncio.wait_for(ws.receive(), 5)).data)
            if not (msg.get("kind") == "response" and msg["ok"] is False
                    and msg["error"]["code"] == "unauthorized"):
                failures.append(f"未鉴权应被拒，实际：{msg}")
            else:
                print("[ok] WS 未鉴权命令被拒：", msg["error"]["message"])

            # 配对
            await ws.send_json(
                {
                    "kind": "request",
                    "id": "w2",
                    "method": "remote.pair",
                    "params": {"code": code, "device_name": "冒烟手机"},
                }
            )
            msg = json.loads((await asyncio.wait_for(ws.receive(), 5)).data)
            if msg.get("ok") is True and msg.get("result", {}).get("token"):
                token = msg["result"]["token"]
                print("[ok] WS remote.pair 换取 token 成功")
            else:
                failures.append(f"配对失败：{msg}")

            # 鉴权后命令成功，response 回到同一连接
            await ws.send_json(
                {
                    "kind": "request",
                    "id": "w3",
                    "method": "app.bootstrap",
                    "params": {},
                    "auth": {"token": token},
                }
            )
            msg = json.loads((await asyncio.wait_for(ws.receive(), 10)).data)
            if msg.get("ok") is True and "projects" in msg.get("result", {}):
                print("[ok] WS 鉴权命令 app.bootstrap 成功")
            else:
                failures.append(f"鉴权命令失败：{str(msg)[:200]}")

            # 事件扇出：订阅建立后从 stdin 触发真实事件（conversation.rename
            # 发出 conversation.changed），WS 必须收到同一条。
            await asyncio.to_thread(
                send_stdin,
                {
                    "kind": "request",
                    "id": "ev1",
                    "method": "conversation.rename",
                    "params": {"title": "冒烟重命名"},
                },
            )
            got_event = False
            try:
                while True:
                    raw = await asyncio.wait_for(ws.receive(), 5)
                    if raw.type != aiohttp.WSMsgType.TEXT:
                        break
                    message = json.loads(raw.data)
                    if message.get("kind") == "event":
                        got_event = True
                        print(f"[ok] WS 收到扇出事件：{message.get('event')} "
                              f"sequence={message.get('sequence')}")
                        break
            except asyncio.TimeoutError:
                failures.append("WS 5 秒内未收到扇出事件")
            if not got_event and "WS 5 秒内未收到扇出事件" not in failures:
                failures.append("WS 事件流意外关闭")

            await ws.close()
        finally:
            await session.close()
        return token

    try:
        # 等服务就绪（backend.ready 事件到 stdout）
        deadline = time.monotonic() + 15
        ready = False
        while time.monotonic() < deadline:
            if any(
                _safe_json(line).get("event") == "backend.ready"
                for line in stdout_lines
            ):
                ready = True
                break
            if proc.poll() is not None:
                stderr = proc.stderr.read() if proc.stderr else ""
                raise AssertionError(
                    f"进程提前退出 code={proc.returncode}\nstderr: {stderr[:2000]}"
                )
            time.sleep(0.1)
        if not ready:
            failures.append("backend.ready 未在 15 秒内出现")
        else:
            print("[ok] 真实进程启动，backend.ready 到达 stdout")

        # stdin 路径：生成配对码（验证 stdin 与 WS 并行）
        send_stdin({"kind": "request", "id": "s1", "method": "remote.issue_code", "params": {}})
        resp = wait_response("s1")
        code = resp.get("result", {}).get("code", "")
        if resp.get("ok") is True and len(code) == 6:
            print(f"[ok] stdin remote.issue_code 成功：{code}")
        else:
            failures.append(f"stdin 配对码生成失败：{resp}")

        # stdin 再验证一条业务命令（card.list，验证新命令在真实进程可用）
        send_stdin({"kind": "request", "id": "s2", "method": "card.list", "params": {}})
        resp = wait_response("s2")
        cards = resp.get("result", {}).get("cards", [])
        builtin = [c for c in cards if c.get("source") == "builtin"]
        if resp.get("ok") is True and len(builtin) == 3:
            print(f"[ok] stdin card.list 成功，内置角色 {len(builtin)} 个")
        else:
            failures.append(f"card.list 异常：ok={resp.get('ok')} builtin={len(builtin)}")

        # WS 阶段
        if code:
            token = asyncio.run(ws_phase(code))
            # 撤销 token 后 WS 拒绝——通过 stdin revoke 再连一次
            if token:
                send_stdin({
                    "kind": "request", "id": "s3",
                    "method": "remote.revoke",
                    "params": {"device_name": "冒烟手机"},
                })
                resp = wait_response("s3")
                if resp.get("ok") is True:
                    print("[ok] stdin remote.revoke 成功")

                    async def revoked_check() -> None:
                        session = aiohttp.ClientSession()
                        try:
                            ws = await session.ws_connect(f"http://127.0.0.1:{port}/ws")
                            await ws.send_json({
                                "kind": "request", "id": "w4",
                                "method": "app.bootstrap", "params": {},
                                "auth": {"token": token},
                            })
                            msg = json.loads((await asyncio.wait_for(ws.receive(), 5)).data)
                            if msg.get("error", {}).get("code") == "unauthorized":
                                print("[ok] 已撤销 token 被真实拒绝")
                            else:
                                failures.append(f"撤销后未拒绝：{str(msg)[:200]}")
                            await ws.close()
                        finally:
                            await session.close()

                    asyncio.run(revoked_check())
                else:
                    failures.append(f"remote.revoke 失败：{resp}")

        # 正常退出
        send_stdin({"kind": "request", "id": "s9", "method": "app.shutdown", "params": {}})
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            failures.append("app.shutdown 后进程未在 15 秒内退出")
            proc.kill()
            proc.wait()
        if proc.returncode == 0:
            print("[ok] 进程正常退出，退出码 0")
        else:
            failures.append(f"退出码异常：{proc.returncode}")

        # 端口释放检查
        time.sleep(0.3)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                failures.append("端口仍被占用，服务器未清理")
            else:
                print("[ok] 端口已释放")

    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    print()
    if failures:
        print("冒烟失败项：")
        for item in failures:
            print(" -", item)
        return 1
    print("真实进程冒烟全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
