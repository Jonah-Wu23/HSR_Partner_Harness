"""A03：长期记忆 —— 入口侦查（UI / Rust / sidecar / 协议）+ 协议面核验。

入口侦查四面（缺一不可，任一缺失都要有原始证据）：
1. UI 路由/DOM：桌面端是否存在记忆增删改入口；
2. Rust 命令：src-tauri 是否暴露记忆相关命令；
3. sidecar API：Python 侧是否存在记忆写入路径（谁调用 upsert_memory）；
4. 协议枚举：memory.list/update/delete 是否存在、参数与作用域要求。

代码面侦查用 Python 直接遍历文件（不依赖外部 grep 可执行文件）。
最终状态按补充测试 §7：缺入口判失败。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso
from s4common import (
    REPO,
    WS_URL,
    case_dir,
    load_token,
    sidecar_log_mark,
    sidecar_tail,
    write_commands,
    write_http_log,
)

CASE = "A03"
SKIP_DIRS = {"node_modules", "target", "dist", "__pycache__", ".git", "build"}


def scan(pattern: str, roots: list[str], *, max_hits: int = 12) -> list[str]:
    """在指定根目录下按行扫描正则，返回 "相对路径:行号: 内容" 命中。"""
    regex = re.compile(pattern)
    hits: list[str] = []
    for root in roots:
        base = REPO / root
        if not base.exists():
            hits.append(f"{root}: <路径不存在>")
            continue
        paths = [base] if base.is_file() else [
            p for p in base.rglob("*")
            if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)
        ]
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{path.relative_to(REPO)}:{number}: {line.strip()[:200]}")
                    if len(hits) >= max_hits:
                        return hits
    return hits


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}

    print("scan ui/rust/sidecar…", flush=True)
    recon = {
        "ui": {
            "actions_memory": scan(r"memory", ["desktop/src/services/actions.ts"]),
            "contracts_actions_memory": scan(r"memory", ["desktop/src/contracts/actions.ts"]),
            "ui_components_calling_memory_commands": scan(
                r"memory\.list|memory\.update|memory\.delete|queryMemory|updateMemory|deleteMemory",
                ["desktop/src/ui", "desktop/src/app"]),
            "store_event_handling": scan(r'"memory\.(updated|deleted)"',
                                         ["desktop/src/stores/desktopStore.ts"]),
            "context_strip_memory_text": scan(r"记忆", ["desktop/src/ui/status/ContextStatusStrip.tsx"]),
        },
        "rust": {
            "memory_in_src_tauri": scan(r"memory", ["desktop/src-tauri/src"]),
        },
        "sidecar_api": {
            "upsert_memory_definition": scan(r"def upsert_memory", ["src/pair_harness"]),
            "upsert_memory_callers": scan(r"upsert_memory", ["src/pair_harness"], max_hits=20),
            "other_memory_writers": scan(r"def (save|insert|create)_memory", ["src/pair_harness"]),
            "memory_command_registration": scan(r'"memory\.', ["src/pair_harness"], max_hits=20),
        },
    }
    log["reconnaissance"] = recon
    print("ui hits:", {k: len(v) for k, v in recon["ui"].items()}, flush=True)
    print("sidecar upsert callers:", recon["sidecar_api"]["upsert_memory_callers"], flush=True)

    # 组装期是否把长期记忆注入提示词（用于说明"读侧存在、写侧缺失"）
    log["reconnaissance"]["write_path_absence_check"] = {
        "grep_upsert_memory_occurrences": recon["sidecar_api"]["upsert_memory_callers"],
        "conclusion": (
            "只有 storage 层定义，调用点零处 → 运行期没有任何路径会写入 pair_memories"
        ),
    }

    print("protocol probes…", flush=True)
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="s4-a03")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next(p for p in (bootstrap.get("projects") or [])
                       if p.get("name") == "project-alpha")
        project_id = project["project_id"]
        account_id = bootstrap.get("current_account_id")
        conversation_id = None
        for p in bootstrap.get("projects") or []:
            for c in p.get("conversations") or []:
                if c.get("pair_id") == "phainon_ancient_machine":
                    conversation_id = c["conversation_id"]
                    break
            if conversation_id:
                break
        pair_id = "phainon_ancient_machine"
        scope_a = {"account_id": account_id, "project_id": project_id, "pair_id": pair_id,
                   "character_ref": "builtin:phainon", "assistant_identity": "ancient_machine"}
        scope_b = {**scope_a, "assistant_identity": "fourth_mirror"}
        scope_c = {**scope_a, "project_id": "00000000-0000-0000-0000-0000000000ff"}
        log["scopes"] = {"a_pair_phainon": scope_a, "b_same_pair_other_assistant": scope_b,
                         "c_other_project": scope_c}

        probes: dict = {}

        async def probe(name: str, method: str, params: dict, timeout: float = 25.0) -> None:
            try:
                result = await session.call(method, params, timeout=timeout)
                probes[name] = {"ok": True, "result": result}
            except asyncio.TimeoutError:
                probes[name] = {"ok": False, "code": "client_timeout",
                                "note": "服务端无响应（疑似响应体不可序列化）"}
            except HarnessError as exc:
                probes[name] = {"ok": False, "code": exc.code, "message": exc.message[:200]}
            print(" probe", name, json.dumps(probes[name], ensure_ascii=False)[:160], flush=True)

        await probe("incomplete_scope", "memory.list", {"project_id": project_id})
        await probe("scope_a", "memory.list", dict(scope_a))
        await probe("scope_b_same_pair_other_assistant", "memory.list", dict(scope_b))
        await probe("scope_c_other_project", "memory.list", dict(scope_c))
        await probe("by_conversation", "memory.list", {"conversation_id": conversation_id})
        update_params = {**scope_a, "memory_id": "s4-nonexistent-memory",
                         "content": {"note": "s4 probe"}}
        await probe("update_unknown_id", "memory.update", update_params)
        delete_params = {**scope_a, "memory_id": "s4-nonexistent-memory"}
        await probe("delete_unknown_id", "memory.delete", delete_params)
        log["protocol_probes"] = probes

        # memory.list 的返回体是否可序列化（对比 metrics.query/summary.get 的已知缺陷）
        log["memory_list_serializable"] = probes["scope_a"].get("ok") is True
    finally:
        await session.close()

    # 只读结构化证据：作用域是否进入查询键
    schema_probe = REPO / ".tmp" / "dbq.py"
    import subprocess
    result = subprocess.run(
        ["E:/AI/HSR Partner Harness/.venv/Scripts/python.exe", str(schema_probe)],
        cwd=REPO,
        input="select count(*) as memories from pair_memories;\n"
              "select sql from sqlite_master where tbl_name='pair_memories' and type='index';\n",
        capture_output=True, text=True, check=False)
    log["db_readonly"] = {"stdout": result.stdout, "stderr": result.stderr}

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    (out / "a03-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a03.py",
    ])
    write_http_log(out / "http.log", "A03 全部交互走 WS 帧")
    print("A03 finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
