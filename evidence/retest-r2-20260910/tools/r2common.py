"""S4-R2 复测批次公共支撑：token 装载、result.json 模板、证据收集。

与 S4-R1（r1common.py @ retest-20260910）的差异：
- 批次、证据根目录、候选标识改为 S4-R2 复测批次；
- 候选产物为 S4-R2 修复后重建的 EXE / Sidecar / APK（SHA256 见 batch-manifest.json）；
- Sidecar 日志仍按复测计划 §3.3 要求全量落盘（PAIR_HARNESS_LOG_LEVEL=INFO）。
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
BATCH = "retest-r2-20260910"
# 候选为工作树快照：HEAD 提交 + S4-R2 未提交修复（本批次同样未提交 git）。
CANDIDATE_COMMIT = "工作树快照 @ cc4077c + S4-R2 uncommitted fixes"
CONTRACT = "contract-v1（5dae701 + effa4f3）"
DEVICE = "Windows 11 10.0.26200 / 2560x1440 / 缩放150% / 本地桌面会话"
NETWORK = "本机直连公网（无 Tailscale）；手机端经局域网 10.81.0.0/16"
REPO = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic")
EXE = REPO / r"desktop\src-tauri\target\release\hsr-partner-harness.exe"
SIDECAR = (
    REPO
    / r"desktop\src-tauri\target\release\resources\sidecar"
    / "pair-harness-sidecar" / "pair-harness-sidecar.exe"
)
APK = (
    REPO
    / r"desktop\src-tauri\gen\android\app\build\outputs\apk\arm64\debug"
    / "app-arm64-debug.apk"
)
SIDECAR_STDERR = Path(os.environ["APPDATA"]) / "com.jonahwu.hsr-partner-harness" / "sidecar.stderr.log"
EVIDENCE = REPO / "evidence" / BATCH
TOKEN_FILE = REPO / ".tmp" / "r2-token.txt"

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
    try:
        lines = SIDECAR_STDERR.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    _sidecar_marks["lines"] = len(lines)


def sidecar_tail(dest: Path, mark: str = "lines") -> int:
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


def build_block() -> dict:
    return {
        "exe": str(EXE),
        "exe_sha256": file_sha256(EXE) if EXE.exists() else None,
        "sidecar": str(SIDECAR),
        "sidecar_sha256": file_sha256(SIDECAR) if SIDECAR.exists() else None,
        "apk": str(APK),
        "apk_sha256": file_sha256(APK) if APK.exists() else None,
    }


def result_shell(case: str, *, title: str) -> dict:
    return {
        "batch": BATCH,
        "case_id": case,
        "title": title,
        "candidate_commit": CANDIDATE_COMMIT,
        "contract": CONTRACT,
        "build": build_block(),
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
    import asyncio

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
        await asyncio.sleep(interval)
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
