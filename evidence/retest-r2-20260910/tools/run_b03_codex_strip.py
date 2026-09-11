"""B-03 负向三条 + 历史账号形态（S4-R2 真机复测）。

复测计划 §14.2 第 2 条要求的三条负向断言与历史账号形态，全部在真机上取证：

A. 静态残留：仓库与**打包产物**里都不存在要求 Responses 的路径与提示。
B. 运行中的候选（EXE → Sidecar，ws://127.0.0.1:8765）：
   - 供应商切换到通用 `openai_compatible` 端点不再被 Responses 拒绝；
   - 显式写旧 `engine` 被可定位拒绝（invalid_engine），不再是 Responses 报文；
   - 服务商只剩 deepseek / openai_compatible，`openai_oauth` 被 provider_unavailable 拒绝；
   - `codex.oauth_start` / `codex.api_login` 回 codex_login_removed。
C. 历史账号形态（隔离 LOCALAPPDATA 下的独立 Sidecar 实例，端口 8766）：
   - 账号里保存 `dialogue.provider=openai_oauth` + `engine=codex` 时启动**不退出**；
   - 启动期发出**非致命** error.reported（provider_unavailable / engine_removed，fatal=false）；
   - `config.get` 如实回 `provider_supported=false` 且不改写已保存的值；
   - 用户**显式改选**供应商后可恢复（provider_supported=true）。

只读断言全部走候选自身的 WS 通道；唯一的数据准备是在**隔离实例**里直接写
provider_configs 行来构造历史配置（真实升级现场没有别的构造方式），
验收账号的配置不被这个用例改动。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso, pair
from r2common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell, build_block,
)

CASE = "B-03"
REPO = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic")
TOOLS = Path(__file__).resolve().parent
SIDECAR_EXE = REPO / r"desktop\src-tauri\target\release\resources\sidecar" / \
    "pair-harness-sidecar" / "pair-harness-sidecar.exe"
EXE = REPO / r"desktop\src-tauri\target\release\hsr-partner-harness.exe"
DIST = REPO / "desktop" / "dist"
LEGACY_ROOT = REPO / ".tmp" / "r2-legacy-root"
LEGACY_HOME = LEGACY_ROOT / "PairHarness"
LEGACY_PORT = 8766

PROBE_ACCOUNT = "r2-codex-probe"
PROBE_PASSWORD = "r2probe2026"

# 提交历史里 B-03 之前确实存在的判定串（用于证明静态残留检查是有效的）
FORBIDDEN = [
    "_require_responses_backend",
    "Responses API 后端",
    "codex 引擎要求 Responses",
    "OpenAI OAuth",
]


def run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 120.0) -> dict:
    result = subprocess.run(cmd, cwd=str(cwd or REPO), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    return {"cmd": " ".join(cmd), "rc": result.returncode,
            "stdout": (result.stdout or "")[:20000], "stderr": (result.stderr or "")[:4000]}


def find_bytes_in_file(path: Path, needle: str) -> list[int]:
    """在二进制/文本产物里找 UTF-8 或 UTF-16LE 形式的串，返回命中偏移。"""
    data = path.read_bytes()
    hits: list[int] = []
    for encoded in (needle.encode("utf-8"), needle.encode("utf-16-le")):
        start = 0
        while True:
            index = data.find(encoded, start)
            if index < 0:
                break
            hits.append(index)
            start = index + 1
    return hits


async def safe(session: Harness, method: str, params: dict, timeout: float = 60.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:400],
                "details": exc.details}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout"}


# —— A. 静态残留 ——

def part_a() -> dict:
    out: dict = {}
    repo_grep: dict = {}
    for needle in FORBIDDEN:
        repo_grep[needle] = run(["git", "grep", "-n", "-I", "-F", needle, "--",
                                 "src", "desktop/src", "desktop/mobile/src",
                                 "desktop/scripts", "config", "assets"])
    out["repo_grep"] = repo_grep
    out["repo_grep_hits"] = {
        needle: [line for line in payload["stdout"].splitlines() if line.strip()]
        for needle, payload in repo_grep.items()
    }

    artifacts: list[Path] = []
    if DIST.exists():
        artifacts.extend(sorted(DIST.rglob("*.js")) + sorted(DIST.rglob("*.html")))
    if EXE.exists():
        artifacts.append(EXE)
    if SIDECAR_EXE.exists():
        artifacts.append(SIDECAR_EXE)
    out["artifact_scan"] = {}
    for path in artifacts:
        key = str(path.relative_to(REPO)) if REPO in path.parents else str(path)
        out["artifact_scan"][key] = {
            needle: len(find_bytes_in_file(path, needle)) for needle in FORBIDDEN
        }
    out["artifact_files"] = len(artifacts)
    out["hits_total"] = sum(
        count for per_file in out["artifact_scan"].values() for count in per_file.values()
    ) + sum(len(lines) for lines in out["repo_grep_hits"].values())
    return out


# —— B. 运行中的候选：配置写入负向 ——

async def part_b() -> dict:
    token = load_token()
    log: dict = {}
    session = Harness(WS_URL, token, frames_log=case_dir(CASE) / "ws-frames-live.log",
                      events_log=case_dir(CASE) / "events-live.log", device_name="r2-b03")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        original_account = bootstrap.get("current_account_id")
        log["account_before"] = original_account
        log["config_before"] = await safe(session, "config.get", {})

        accounts = await safe(session, "account.list", {})
        existing = next(
            (a for a in ((accounts.get("result") or {}).get("accounts") or [])
             if a.get("username") == PROBE_ACCOUNT), None)
        registered = await safe(session, "account.register", {
            "username": PROBE_ACCOUNT, "display_name": PROBE_ACCOUNT,
            "password": PROBE_PASSWORD})
        probe_id = ((existing or {}).get("account_id")
                    or (registered.get("result") or {}).get("account_id"))
        log["probe_account"] = {"account_id": probe_id, "register": registered}
        switched = await safe(session, "account.switch", {"account_id": probe_id or ""})
        log["probe_account"]["switch"] = switched

        # 1) 通用 openai_compatible 端点（非 OpenAI 域）——修复前这里被 Responses 拒绝
        log["switch_to_generic_endpoint"] = {
            "config_set": await safe(session, "config.set", {"updates": {
                "dialogue.provider": "openai_compatible",
                "dialogue.base_url": "https://api.deepseek.com/v1",
                "dialogue.model": "deepseek-v4-flash",
                "dialogue.api_key": "sk-r2-invalid-000000000000"}}),
        }
        log["switch_to_generic_endpoint"]["config_after"] = await safe(
            session, "config.get", {})

        # 2) 任意 http(s) 端点（本机不可达端口）——不再被 Responses 校验拦下
        log["switch_to_unreachable_endpoint"] = {
            "config_set": await safe(session, "config.set", {"updates": {
                "dialogue.provider": "openai_compatible",
                "dialogue.base_url": "https://127.0.0.1:1/v1",
                "dialogue.model": "r2-none",
                "dialogue.api_key": "sk-r2-invalid-000000000000"}}),
        }
        log["switch_to_unreachable_endpoint"]["config_after"] = await safe(
            session, "config.get", {})

        # 3) 显式写旧 engine —— 期望可定位的 invalid_engine，而不是 Responses 报文
        log["legacy_engine_write"] = {
            "config_set": await safe(session, "config.set", {"updates": {
                "engine": "codex",
                "dialogue.provider": "openai_compatible",
                "dialogue.base_url": "https://api.deepseek.com/v1",
                "dialogue.model": "deepseek-v4-flash",
                "dialogue.api_key": "sk-r2-invalid-000000000000"}}),
        }
        log["legacy_engine_write"]["config_after"] = await safe(
            session, "config.get", {})

        # 4) 直接选 openai_oauth —— 期望 provider_unavailable
        log["legacy_provider_write"] = {
            "config_set": await safe(session, "config.set", {"updates": {
                "dialogue.provider": "openai_oauth"}}),
        }

        # 5) 已移除的登录入口
        log["codex_login_entries"] = {
            "oauth_start": await safe(session, "codex.oauth_start", {}),
            "api_login": await safe(session, "codex.api_login", {
                "api_key": "sk-r2-invalid-000000000000"}),
            "oauth_status": await safe(session, "codex.oauth_status", {}),
        }

        # 6) 探测目标可归属
        log["test_connection"] = await safe(session, "config.test_connection", {},
                                            timeout=60)

        log["account_restore"] = await safe(session, "account.switch",
                                            {"account_id": original_account})
        log["account_after"] = (await session.call("app.bootstrap", timeout=30)
                                ).get("current_account_id")
        log["config_restored"] = await safe(session, "config.get", {})
    finally:
        await session.close()
    return log


# —— C. 历史账号形态（隔离实例） ——

def seed_legacy_config() -> dict:
    db = LEGACY_HOME / "pair_harness.db"
    rows = [
        ("default-local", "dialogue.provider", "openai_oauth"),
        ("default-local", "engine", "codex"),
        ("default-local", "dialogue.base_url", "https://api.openai.com/v1"),
        ("default-local", "dialogue.model", "gpt-5.6-sol"),
        ("default-local", "dialogue.api_key", "sk-r2-legacy-oauth-000000"),
    ]
    con = sqlite3.connect(str(db))
    try:
        con.executemany(
            "insert into provider_configs(account_id, key, value) values(?,?,?) "
            "on conflict(account_id, key) do update set value=excluded.value", rows)
        con.commit()
        stored = list(con.execute(
            "select key, value from provider_configs where account_id='default-local' order by key"))
    finally:
        con.close()
    return {"database": str(db), "rows_written": len(rows),
            "stored": [{"key": k, "value": v} for k, v in stored]}


def boot_isolated(port: int, out_dir: Path, issue_code: bool, delay: float = 14.0) -> dict:
    argv = [sys.executable, str(TOOLS / "launch_sidecar.py"),
            "--exe", str(SIDECAR_EXE), "--port", str(port),
            "--out-dir", str(out_dir), "--mode", "real"]
    if issue_code:
        argv += ["--issue-code", "--issue-delay", str(delay)]
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(LEGACY_ROOT)
    env["PAIR_HARNESS_ENV_FILE"] = str(LEGACY_ROOT / "empty.env")
    (LEGACY_ROOT / "empty.env").write_text("", encoding="utf-8")
    process = subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    return {"argv": argv, "pid": process.pid, "process": process}


def stop_process(process: subprocess.Popen, port: int) -> None:
    """停掉隔离实例：杀掉启动器即归还 stdin，Sidecar 读到 EOF 自行退出。

    不用按进程名批量结束——桌面候选的 Sidecar 与隔离实例是同一个可执行文件
    路径，批量结束会连带杀掉正在运行的桌面候选。
    """
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=25)
    except subprocess.TimeoutExpired:
        process.kill()
    deadline = time.monotonic() + 40.0
    while time.monotonic() < deadline:
        try:
            import socket

            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                time.sleep(1.5)
        except OSError:
            return
    raise RuntimeError(f"隔离实例未在端口 {port} 上退出")


def read_stdout(out_dir: Path) -> list[dict]:
    path = out_dir / "sidecar.serve.stdout.log"
    if not path.exists():
        return []
    frames: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            frames.append(json.loads(line))
        except ValueError:
            frames.append({"raw": line[:400]})
    return frames


async def wait_port(port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            return True
        except OSError:
            await asyncio.sleep(1.0)
    return False


async def part_c() -> dict:
    log: dict = {}
    if LEGACY_ROOT.exists():
        shutil.rmtree(LEGACY_ROOT, ignore_errors=True)
    LEGACY_ROOT.mkdir(parents=True, exist_ok=True)

    # 1) 先起一次创建 schema，然后停掉
    boot_dir = LEGACY_ROOT / "boot"
    proc = boot_isolated(LEGACY_PORT, boot_dir, issue_code=False)
    log["schema_boot_ready"] = await wait_port(LEGACY_PORT, 90.0)
    stop_process(proc["process"], LEGACY_PORT)
    log["schema_boot_pid"] = proc["pid"]

    log["seeded"] = seed_legacy_config()

    # 2) 以历史配置启动（这是本用例的核心）
    run_dir = LEGACY_ROOT / "legacy-run"
    proc = boot_isolated(LEGACY_PORT, run_dir, issue_code=True, delay=16.0)
    log["legacy_boot_pid"] = proc["pid"]
    log["legacy_ready"] = await wait_port(LEGACY_PORT, 90.0)
    await asyncio.sleep(14.0)
    alive = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process -Name pair-harness-sidecar -ErrorAction SilentlyContinue | "
         "Measure-Object).Count"],
        capture_output=True, text=True, check=False)
    log["legacy_process_alive"] = (alive.stdout or "").strip()

    frames = read_stdout(run_dir)
    (case_dir(CASE) / "legacy-stdout-frames.json").write_text(
        json.dumps(frames, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reporter = [
        frame for frame in frames
        if frame.get("event") == "error.reported"
    ]
    log["legacy_events"] = [
        {"event": frame.get("event"), "sequence": frame.get("sequence"),
         "payload": frame.get("payload")}
        for frame in reporter
    ]
    codes = {json.dumps(frame.get("payload", {}), ensure_ascii=False) for frame in reporter}
    log["legacy_event_codes"] = sorted(
        str(frame.get("payload", {}).get("code")) for frame in reporter)

    # 3) 经 stdin 桌面通道取配对码 → 配对 → config.get 如实报不受支持
    code = None
    for frame in frames:
        result = (frame.get("result") or {}) if frame.get("kind") == "response" else {}
        if isinstance(result, dict) and result.get("code"):
            code = str(result["code"])
            serve = result.get("serve_address")
            log["issue_code_response"] = {"code": code, "ttl_seconds": result.get("ttl_seconds"),
                                          "serve_address": serve}
            break
    log["pairing_code"] = code
    if code:
        token, err = await pair(f"ws://127.0.0.1:{LEGACY_PORT}/ws", code, "r2-legacy-probe")
        log["pair_error"] = err
        if token:
            session = Harness(f"ws://127.0.0.1:{LEGACY_PORT}/ws", token,
                              frames_log=case_dir(CASE) / "ws-frames-legacy.log",
                              events_log=case_dir(CASE) / "events-legacy.log",
                              device_name="r2-legacy")
            await session.connect()
            try:
                log["legacy_config_get"] = await safe(session, "config.get", {})
                log["legacy_test_connection"] = await safe(
                    session, "config.test_connection", {}, timeout=60)
                # 显式改选 → 恢复
                log["explicit_reselect"] = await safe(session, "config.set", {"updates": {
                    "dialogue.provider": "deepseek",
                    "dialogue.base_url": "https://api.deepseek.com",
                    "dialogue.model": "deepseek-v4-flash",
                    "dialogue.api_key": "sk-r2-invalid-000000000000"}})
                log["config_after_reselect"] = await safe(session, "config.get", {})
            finally:
                await session.close()
    stop_process(proc["process"], LEGACY_PORT)
    log["legacy_frames_total"] = len(frames)
    return log


async def main() -> int:
    out = case_dir(CASE)
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    log["part_a"] = part_a()
    log["part_b"] = await part_b()
    log["part_c"] = await part_c()
    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        write_info_log(CASE, (out / "sidecar.log").read_text(
            encoding="utf-8").splitlines())
    except OSError:
        pass
    (out / "b03-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "B-03 负向三条：仓库/产物静态扫描 + 运行中候选 WS 帧 + 隔离实例 stdin/WS")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-r2-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_b03_codex_strip.py",
    ])

    r = result_shell(CASE, title="B-03 仅 Chat Completions 可用（负向三条 + 历史账号形态）")
    r["build"] = build_block()
    r["actual"] = json.dumps(log, ensure_ascii=False)[:20000]
    r["timestamps"]["finished_at"] = now_iso()
    r["evidence"] = ["b03-run.json", "legacy-stdout-frames.json", "ws-frames-live.log",
                     "events-live.log", "ws-frames-legacy.log", "events-legacy.log",
                     "sidecar.log", "sidecar-info.log"]
    save_result(CASE, r)
    print(json.dumps({
        "part_a_hits": log["part_a"]["hits_total"],
        "part_b": {k: log["part_b"][k] for k in
                   ("switch_to_generic_endpoint", "switch_to_unreachable_endpoint",
                    "legacy_engine_write", "legacy_provider_write", "codex_login_entries",
                    "test_connection")},
        "part_c": {k: log["part_c"].get(k) for k in
                   ("legacy_ready", "legacy_process_alive", "legacy_event_codes",
                    "pairing_code", "legacy_config_get", "legacy_test_connection",
                    "explicit_reselect", "config_after_reselect")},
    }, ensure_ascii=False, indent=2)[:12000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
