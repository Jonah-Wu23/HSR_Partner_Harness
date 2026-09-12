"""M10 模拟复测（R1-002 修复后）：进程级强杀 cloudflared，断言 Sidecar stdout 真实发出 tunnel.failed。

流程：
1. 以真实 Sidecar 子进程启动（--serve 回环端口，demo 接线，隔离数据目录）；
2. 经 stdin 发送 remote.tunnel_start（desktop 来源，控制面合法路径）；
3. 等待 stdout 出现 tunnel.started（真实 cloudflared Quick Tunnel 就绪）；
4. taskkill /F 强杀 cloudflared.exe（模拟任务管理器强杀）；
5. 断言 stdout 随后出现 tunnel.failed，payload.error 携带真实退出码，
   且事件序号在桌面可见流内连续（本场景无 remote-only 消费）。

结果落 stdout 转写（本文件所在目录 transcript.log）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORT = 18799
DATA_DIR = Path(__file__).resolve().parent / "sidecar-data"

transcript_lines: list[str] = []


def log(line: str) -> None:
    stamped = f"[{time.strftime('%H:%M:%S')}] {line}"
    transcript_lines.append(stamped)
    print(stamped, flush=True)


def read_stdout_until(proc: subprocess.Popen, want_event: str | None, want_id: str | None, timeout: float) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            log(f"NON-JSON STDOUT: {text[:200]}")
            continue
        kind = message.get("kind")
        if kind == "event":
            log(f"EVENT seq={message.get('sequence')} {message.get('event')} payload={json.dumps(message.get('payload'), ensure_ascii=False)[:160]}")
            if want_event and message.get("event") == want_event:
                return message
        else:
            log(f"MSG kind={kind} id={message.get('id')} ok={message.get('ok')}")
            if want_id and message.get("id") == want_id:
                return message
    raise TimeoutError(f"等待 {want_event or want_id} 超时（{timeout}s）")


def find_cloudflared_pid() -> int:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV", "/NH"],
        capture_output=True, check=True,
    ).stdout.decode("gbk", errors="replace")
    for row in out.splitlines():
        parts = [p.strip('"') for p in row.split('","')]
        if parts and parts[0].lower().startswith("cloudflared"):
            return int(parts[1])
    raise RuntimeError("未找到 cloudflared.exe 进程")


def main() -> int:
    # 数据目录保持隔离全新：cloudflared 由 Sidecar 按需下载（官方源 + SHA256
    # 校验），同时在 sidecar stderr 留下 R1-004 的完整过程日志（下载、哈希、
    # 子进程启动、主机名解析）。
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True)

    cmd = [
        str(REPO / ".venv" / "Scripts" / "python.exe"),
        "-m", "pair_harness.desktop_backend",
        "--serve", str(PORT),
        "--data-dir", str(DATA_DIR),
        "--project", str(DATA_DIR),
        "--demo",
    ]
    log(f"启动 Sidecar：{' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=REPO,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        # backend.ready / serve.started 等启动事件
        read_stdout_until(proc, "backend.ready", None, 60)
        read_stdout_until(proc, "serve.started", None, 60)

        request = {"kind": "request", "id": "t1", "method": "remote.tunnel_start", "params": {"port": PORT}}
        proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        proc.stdin.flush()
        log("已发送 remote.tunnel_start（port=18799，desktop 来源）")
        resp = read_stdout_until(proc, None, "t1", 30)
        assert resp.get("ok") is True, f"tunnel_start 失败：{resp}"
        log(f"tunnel_start 响应：{json.dumps(resp.get('result'), ensure_ascii=False)}")

        started = read_stdout_until(proc, "tunnel.started", None, 300)
        started_seq = started["sequence"]
        log(f"隧道就绪：{started['payload'].get('public_url')}（seq={started_seq}）")

        pid = find_cloudflared_pid()
        log(f"强杀 cloudflared.exe pid={pid}")
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)

        failed = read_stdout_until(proc, "tunnel.failed", None, 60)
        failed_seq = failed["sequence"]
        error_text = str(failed["payload"].get("error"))
        log(f"tunnel.failed seq={failed_seq} error={error_text}")

        assert "退出码" in error_text, f"失败原因未携带退出码：{error_text}"
        assert failed_seq == started_seq + 1, (
            f"桌面可见事件序号不连续：tunnel.started={started_seq} -> tunnel.failed={failed_seq}"
        )
        log("PASS：Sidecar 真实发出 tunnel.failed（真实退出码），序号连续；桌面 store/面板消费已由 vitest 回归覆盖")
        return 0
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr_tail = proc.stderr.read().decode("utf-8", errors="replace")
        log("SIDECAR STDERR 末尾：\n" + stderr_tail)
        (Path(__file__).resolve().parent / "transcript.log").write_text(
            "\n".join(transcript_lines), encoding="utf-8"
        )


if __name__ == "__main__":
    sys.exit(main())
