"""复测批次 Sidecar 启动器：常驻持有 stdin 管道，保证 serve 模式不被 EOF 关停。

候选在 ``--serve`` 模式下把 stdin 当作桌面命令通道，stdin 读到 EOF 即正常退出；
因此协议级复测需要一个不会关闭 stdin 的父进程把它托管起来，同时把
stdout（JSONL 帧）与 stderr（日志，含 INFO）分别全量落盘。

用法：python launch_sidecar.py --exe <path> --port 8765 --out-dir <dir> [--demo|--real]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mode", choices=("default", "demo", "real"), default="default")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = out_dir / "sidecar.serve.stdout.log"
    stderr_path = out_dir / "sidecar.serve.stderr.log"
    pid_path = out_dir / "sidecar.serve.pid"

    env = dict(os.environ)
    env["PAIR_HARNESS_LOG_LEVEL"] = "INFO"
    argv = [args.exe, "--serve", str(args.port)]
    if args.mode == "demo":
        argv.append("--demo")
    elif args.mode == "real":
        argv.append("--real")

    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=out,
                                   stderr=err, env=env)
        pid_path.write_text(str(process.pid), encoding="utf-8")
        print(f"sidecar started pid={process.pid} mode={args.mode} "
              f"stdout={stdout_path} stderr={stderr_path}", flush=True)
        # stdin 句柄由本进程持有且从不写入、从不关闭：候选不会因 EOF 退出。
        return_code = process.wait()
        print(f"sidecar exited rc={return_code}", flush=True)
        return return_code


if __name__ == "__main__":
    sys.exit(main())
