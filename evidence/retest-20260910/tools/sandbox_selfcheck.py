"""B-01 沙盒自检：不依赖候选，验证四种故障形态是否真的可注入。

判据（复测计划 §4.1）：

| 形态 | 沙盒动作 | 观察到的现象 |
| --- | --- | --- |
| forward | 正常 CONNECT 隧道 | 请求成功 |
| reject | 停止监听 | 连接被拒（ECONNREFUSED） |
| cut | 已建立连接 abort | 传输中断 |
| hang | 接受 CONNECT 但不建上游 | 请求悬挂至客户端超时 |

外加一次「名称解析失败」形态：不经代理、直接请求不可解析的 `.invalid` 域。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

TOOLS = Path(__file__).resolve().parent
OUT = TOOLS.parent / "B-01"
SANDBOX = TOOLS / "net_sandbox.py"
PYTHON = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.venv\Scripts\python.exe")
LISTEN, CONTROL = 8767, 8768
PROXY = f"http://127.0.0.1:{LISTEN}"


async def control(command: str) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", CONTROL)
    try:
        writer.write((command + "\n").encode())
        await writer.drain()
        return (await reader.readline()).decode().strip()
    finally:
        writer.close()


async def probe(proxy: str | None, url: str, timeout: float) -> dict:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=timeout, trust_env=False) as client:
            response = await client.get(url)
        return {"outcome": "response", "status": response.status_code,
                "elapsed": round(time.monotonic() - started, 3)}
    except Exception as exc:  # noqa: BLE001 - 错误形态本身就是证据
        return {"outcome": type(exc).__name__, "message": str(exc)[:300],
                "elapsed": round(time.monotonic() - started, 3)}


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "sandbox.selftest.log"
    log_path.write_text("", encoding="utf-8")
    with (OUT / "sandbox.stdout.log").open("wb") as stdout, \
            (OUT / "sandbox.stderr.log").open("wb") as stderr:
        process = subprocess.Popen(
            [str(PYTHON), str(SANDBOX), "--listen", str(LISTEN),
             "--upstream", "api.deepseek.com:443", "--control", str(CONTROL),
             "--log", str(log_path)],
            stdout=stdout, stderr=stderr)
    report: dict = {"sandbox_pid": process.pid, "modes": {}}
    try:
        await asyncio.sleep(2.0)
        # 目标：deepseek 的任意可达端点（用 401/404 也足以证明隧道通了）
        target = "https://api.deepseek.com/"

        report["modes"]["forward"] = {
            "control": await control("SET forward"),
            "probe": await probe(PROXY, target, 20.0),
        }
        report["modes"]["reject"] = {
            "control": await control("SET reject"),
            "probe": await probe(PROXY, target, 10.0),
        }
        report["modes"]["hang"] = {
            "control": await control("SET hang"),
            "probe": await probe(PROXY, target, 6.0),
        }
        # cut 需要先有已建立的隧道：用裸 CONNECT 建立隧道，切断后该隧道必须失效
        await control("SET forward")
        reader, writer = await asyncio.open_connection("127.0.0.1", LISTEN)
        writer.write(b"CONNECT api.deepseek.com:443 HTTP/1.1\r\n"
                     b"Host: api.deepseek.com:443\r\n\r\n")
        await writer.drain()
        header_lines: list[bytes] = []
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            header_lines.append(line)
            if line in (b"\r\n", b"\n", b""):
                break
        cut_reply = await control("CUT")
        cut_outcome: dict = {
            "tunnel_header": b"".join(header_lines).decode("latin-1").strip()}
        try:
            writer.write(b"GET / HTTP/1.1\r\nHost: api.deepseek.com\r\n\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(200), timeout=6)
            cut_outcome["outcome"] = ("connection_closed_after_cut" if not data
                                      else "unexpected_data")
            cut_outcome["bytes_read"] = len(data)
        except asyncio.TimeoutError:
            cut_outcome["outcome"] = "no_response_after_cut"
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                OSError) as exc:
            cut_outcome["outcome"] = type(exc).__name__
            cut_outcome["message"] = str(exc)[:200]
        finally:
            writer.close()
        report["modes"]["cut"] = {"control": cut_reply, "probe": cut_outcome}

        # 名称解析失败：不经代理直连不可解析域
        await control("SET forward")
        report["modes"]["dns_failure"] = {
            "note": "不经代理，直接请求 RFC6761 保留域（沙盒不参与）",
            "probe": await probe(None, "https://no-such-host-r1.invalid/", 10.0),
        }

        report["stats"] = await control("STATS")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    (OUT / "sandbox-selftest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
