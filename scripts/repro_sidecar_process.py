"""进程级复现：启动真实 sidecar 进程，用真实 stdin/stdout JSONL 协议
驱动 bootstrap → register → onboarding_complete，按前端 store 逻辑回放。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


class FrontendStore:
    def __init__(self) -> None:
        self.last_sequence = -1
        self.needs_bootstrap = False
        self.current_account = None
        self.onboarding_complete: bool | None = None
        self.gaps: list[int] = []

    def hydrate(self, snapshot: dict) -> None:
        self.last_sequence = snapshot.get("sequence", -1)
        self.needs_bootstrap = False
        account = snapshot.get("current_account")
        self.current_account = account
        self.onboarding_complete = bool(account and account.get("onboarding_complete"))

    def apply_event(self, event: dict) -> None:
        seq = event["sequence"]
        if seq <= self.last_sequence:
            return
        if self.last_sequence >= 0 and seq != self.last_sequence + 1:
            self.gaps.append(seq)
            self.last_sequence = seq
            self.needs_bootstrap = True
            return
        self.last_sequence = seq
        kind = event["event"]
        payload = event["payload"]
        if kind == "account.changed":
            account = payload.get("account")
            if account:
                self.current_account = account
                self.onboarding_complete = bool(account.get("onboarding_complete"))
        elif kind == "state.snapshot":
            self.hydrate(payload)

    @property
    def onboarding(self) -> bool:
        return (
            self.current_account is not None
            and self.current_account.get("username") != "default"
            and self.onboarding_complete is False
        )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_dir = Path(tmp) / "data"
        db_dir.mkdir(parents=True)
        proc = subprocess.Popen(
            [str(PYTHON), "-m", "pair_harness.desktop_backend", "--demo", "--project", str(Path(tmp))],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert proc.stdin and proc.stdout

        store = FrontendStore()
        pending: dict[str, dict] = {}

        def reader() -> None:
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[sidecar] 非JSON输出: {line.strip()[:120]}")
                    continue
                if msg.get("kind") == "response":
                    pending[msg.get("id")] = msg
                else:
                    print(f"  [消息] {json.dumps(msg, ensure_ascii=False)[:300]}")
                    try:
                        store.apply_event(msg)
                    except Exception as exc:
                        print(f"  [store异常] {exc}")

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        request_id = 0

        def request(method: str, params: dict) -> dict:
            nonlocal request_id
            request_id += 1
            rid = f"r{request_id}"
            proc.stdin.write(json.dumps({"kind": "request", "id": rid, "method": method, "params": params}) + "\n")
            proc.stdin.flush()
            # 等待响应（reader 线程会写入 pending）
            import time
            deadline = time.time() + 10
            while time.time() < deadline and rid not in pending:
                time.sleep(0.02)
            return pending.pop(rid, {})

        def show(tag: str) -> None:
            print(
                f"  [{tag}] lastSequence={store.last_sequence} gaps={store.gaps} "
                f"needsBootstrap={store.needs_bootstrap} onboarding={store.onboarding}"
            )

        resp = request("app.bootstrap", {})
        store.hydrate(resp["result"])
        show("启动 bootstrap")

        resp = request("account.register", {"username": "bob", "display_name": "Bob", "password": "secret123"})
        show("注册后")

        resp = request("account.onboarding_complete", {})
        show("点开始使用后")

        resp = request("app.bootstrap", {})
        store.hydrate(resp["result"])
        show("再次 bootstrap")

        proc.stdin.write(json.dumps({"kind": "request", "id": "shutdown", "method": "app.shutdown", "params": {}}) + "\n")
        proc.stdin.flush()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            print(f"  [进程] 未在 10s 内退出（可能卡死），已强制结束。退出码: {proc.poll()}")
        else:
            print(f"  [进程] 正常退出，退出码: {proc.returncode}")

        print()
        if store.gaps:
            print(f"★ 结论：出现 {len(store.gaps)} 次序号缺口 → needsBootstrap → Onboarding 重挂载回 step 0（复现用户问题）")
        elif store.onboarding:
            print("★ 结论：flag 未翻转，仍显示引导（但组件不重挂，UI 停在当前步骤）")
        else:
            print("★ 结论：序号连续、flag=true → 前端进入主页。进程级链路正常。")


if __name__ == "__main__":
    main()
