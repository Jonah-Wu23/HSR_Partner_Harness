"""S4-R1 复测批次公共支撑：token 装载、result.json 模板、证据收集。

与上一批次（s4common.py @ batch-2026-09-10）的差异：
- 批次、候选标识、证据根目录改为复测批次；
- Sidecar 日志按复测计划 §3.3 要求**全量落盘**（PAIR_HARNESS_LOG_LEVEL=INFO），
  每用例除 ``sidecar.log``（全量）外另存一份 ``sidecar-info.log`` 供按级别检索。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from ph_client import Harness, now_iso  # noqa: F401

WS_URL = "ws://127.0.0.1:8765/ws"
BATCH = "retest-20260910"
# 候选为工作树快照：HEAD 提交 + 工作树 diff 指纹（本批次未提交 git）。
CANDIDATE_COMMIT = "工作树快照 @ cc4077c + uncommitted fixes"
CONTRACT = "contract-v1（5dae701 + effa4f3）"
DEVICE = "Windows 11 10.0.26200 / 2560x1440 / 缩放150% / 本地桌面会话"
NETWORK = "本机直连公网（无 Tailscale）"
REPO = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic")
EXE = REPO / r"desktop\src-tauri\target\release\hsr-partner-harness.exe"
SIDECAR = (
    REPO
    / r"desktop\src-tauri\target\release\resources\sidecar"
    / "pair-harness-sidecar" / "pair-harness-sidecar.exe"
)
SIDECAR_STDERR = Path(os.environ["APPDATA"]) / "com.jonahwu.hsr-partner-harness" / "sidecar.stderr.log"
EVIDENCE = REPO / "evidence" / BATCH
TOKEN_FILE = REPO / ".tmp" / "retest-token.txt"

_sidecar_marks: dict[str, int] = {}


def load_token() -> str:
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def case_dir(case: str) -> Path:
    path = EVIDENCE / case
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sidecar_log_mark() -> None:
    """记下当前 sidecar stderr 的行数，供 sidecar_tail 只截取本用例新增部分。"""
    try:
        lines = SIDECAR_STDERR.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    _sidecar_marks["lines"] = len(lines)


def sidecar_tail(dest: Path, mark: str = "lines") -> int:
    """把标记之后新增的 sidecar stderr 写入用例目录，返回新增行数。

    复测批次以 PAIR_HARNESS_LOG_LEVEL=INFO 启动，因此这份摘录即全量
    （含 INFO/Debug 归因行）；同时另存一份只含 WARNING 及以上的
    ``sidecar-info.log``，便于按级别检索（复测计划 §3.3）。
    """
    try:
        lines = SIDECAR_STDERR.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    start = _sidecar_marks.get(mark, 0)
    new_lines = lines[start:]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
    return len(new_lines)


def write_info_log(case: str, full_lines: list[str]) -> Path:
    """从全量行里挑出 INFO 及更高级别行，落 sidecar-info.log。"""
    keep = [
        line for line in full_lines
        if " INFO " in line or " WARNING " in line or " ERROR " in line
        or " CRITICAL " in line or " DEBUG " in line
    ]
    path = case_dir(case) / "sidecar-info.log"
    path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    return path


def write_http_log(dest: Path, note: str) -> None:
    dest.write_text(
        json.dumps(
            {
                "note": note,
                "ws_upgrade": f"GET {WS_URL} HTTP/1.1 -> 101 Switching Protocols（唯一 HTTP 交互）",
                "auth": "remote.pair 换取 token；业务请求在 WS 帧内携带同一 token",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_tauri_log(dest: Path) -> None:
    dest.write_text(
        "候选未产出 Rust 侧日志文件：`desktop/src-tauri` 无 --debug-console 时 "
        "stderr 丢弃，Rust 进程内无日志落盘路径（sidecar_stderr_log_path 仅覆盖 "
        "Python Sidecar）。本用例的 Rust 侧证据为进程表与窗口观测。\n",
        encoding="utf-8",
    )


def process_table() -> list[dict]:
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='hsr-partner-harness.exe' or "
            "Name='pair-harness-sidecar.exe'\" | Select-Object ProcessId,Name,CreationDate,"
            "CommandLine | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (out.stdout or "").strip()
    if not text:
        return []
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def result_shell(case: str, *, title: str) -> dict:
    return {
        "batch": BATCH,
        "case_id": case,
        "title": title,
        "candidate_commit": CANDIDATE_COMMIT,
        "contract": CONTRACT,
        "build": {
            "exe": str(EXE),
            "exe_sha256": file_sha256(EXE) if EXE.exists() else None,
            "sidecar": str(SIDECAR),
            "sidecar_sha256": file_sha256(SIDECAR) if SIDECAR.exists() else None,
        },
        "device": DEVICE,
        "network": NETWORK,
        "preconditions": {},
        "steps": [],
        "expected": "",
        "actual": "",
        "timestamps": {"started_at": now_iso(), "finished_at": ""},
        "ids": {},
        "evidence": [],
        "severity": "",
        "frequency": "",
        "impact": "",
        "status": "",
        "blocker": "",
        "owner": "",
        "next_action": "",
    }


def save_result(case: str, payload: dict) -> Path:
    path = case_dir(case) / "result.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def write_commands(dest: Path, lines: list[str]) -> None:
    body = ["# 本用例的原样复现命令（PowerShell / Git Bash 均可）", ""]
    body.extend(lines)
    dest.write_text("\n".join(body) + "\n", encoding="utf-8")


def copy_screenshot(src: Path, case: str, name: str) -> Path:
    target = case_dir(case) / name
    shutil.copyfile(src, target)
    return target


async def poll_conversation(harness: Harness, conversation_id: str, *, timeout: float = 120.0,
                            interval: float = 1.0) -> dict:
    """轮询 conversation.open 直到无在途回合。"""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        last = await harness.call(
            "conversation.open", {"conversation_id": conversation_id}, timeout=30
        )
        pending = [
            item
            for item in last.get("messages", [])
            if item.get("status") in {"pending", "streaming", "processing"}
        ]
        if not pending and not last.get("active_task") and not last.get("queue_items"):
            return last
        await __import__("asyncio").sleep(interval)
    return last


def messages_of(snapshot: dict, *, source: str | None = None, kind: str | None = None) -> list[dict]:
    items = snapshot.get("messages", [])
    if source:
        items = [item for item in items if item.get("source") == source]
    if kind:
        items = [item for item in items if item.get("kind") == kind]
    return items


def texts_of(snapshot: dict, *, source: str | None = None) -> list[str]:
    return [str(item.get("text", "")) for item in messages_of(snapshot, source=source)]
