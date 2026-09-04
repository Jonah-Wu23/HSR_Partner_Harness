"""V0.3.7 真机验收 serve 驱动器：常驻 Sidecar --serve 进程 + stdin 命令注入。

用法：
    python scripts/serve_driver_v037.py <data_dir> <cmd_file> <log_file> [port]

- Sidecar 以 --real --serve 启动；DashScope 环境变量从调用环境继承
  （DASHSCOPE_API_KEY 自动映射为 PAIR_HARNESS_DIALOGUE_API_KEY）。
- stdout JSONL（事件+响应）全量追加写 log_file，作为验收观察窗口。
- cmd_file 追加的每行 JSON 作为 stdin 请求注入；追加 {"__stop__": true}
  发送 app.shutdown 优雅停机。

铁律：显式 --data-dir（.archive 下临时目录），绝不触碰用户真实库。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    data_dir = Path(sys.argv[1]).resolve()
    cmd_file = Path(sys.argv[2]).resolve()
    log_file = Path(sys.argv[3]).resolve()
    port = sys.argv[4] if len(sys.argv) > 4 else "8765"

    project_dir = data_dir.parent
    data_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    cmd_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    cmd_file.touch()
    log_file.touch()

    env = {**os.environ}
    env.setdefault(
        "PAIR_HARNESS_DIALOGUE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    if env.get("DASHSCOPE_API_KEY") and not env.get("PAIR_HARNESS_DIALOGUE_API_KEY"):
        env["PAIR_HARNESS_DIALOGUE_API_KEY"] = env["DASHSCOPE_API_KEY"]
    env.setdefault("PAIR_HARNESS_DIALOGUE_MODEL", "qwen-plus")
    env["PYTHONUNBUFFERED"] = "1"

    log = open(log_file, "a", encoding="utf-8", errors="replace")
    log.write(f"== serve_driver start {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} ==\n")
    log.flush()

    root = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pair_harness.desktop_backend",
            "--real",
            "--serve",
            port,
            "--data-dir",
            str(data_dir),
            "--project",
            str(project_dir),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=str(root),
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None

    def reader() -> None:
        for line in proc.stdout:
            log.write(line)
            log.flush()
        log.write("== sidecar stdout closed ==\n")
        log.flush()

    threading.Thread(target=reader, daemon=True).start()

    processed_lines = 0
    stop_requested = False
    try:
        while proc.poll() is None:
            with open(cmd_file, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            while processed_lines < len(lines):
                line = lines[processed_lines].strip()
                processed_lines += 1
                if not line:
                    continue
                if line == '{"__stop__": true}':
                    stop_requested = True
                    proc.stdin.write(
                        json.dumps(
                            {
                                "kind": "request",
                                "id": "driver-stop",
                                "method": "app.shutdown",
                                "params": {},
                            }
                        )
                        + "\n"
                    )
                else:
                    proc.stdin.write(line + "\n")
                proc.stdin.flush()
            if stop_requested:
                # 给优雅停机一点时间，随后退出观察循环。
                for _ in range(60):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.5)
                break
            time.sleep(0.3)
    finally:
        if proc.poll() is None and not stop_requested:
            proc.kill()
        code = proc.wait()
        log.write(f"== serve_driver exit code={code} ==\n")
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
