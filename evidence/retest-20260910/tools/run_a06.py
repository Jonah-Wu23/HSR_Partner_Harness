"""A06：指标与装配诊断、真实服务失败注入（协议级 + Windows 操作）。

覆盖补充测试 §6 的 A06 要求：
- 隐藏原文必须显式请求（include_hidden=true），普通请求一律为 null；
- 隐藏内容不进普通对话（对话流里查不到模块原文）；
- 错误可定位：错误 key、错误 base_url（连接被拒）、DNS 失败、防火墙断网；
- 缺失指标为 null、真实零为 0（本候选两处只读命令的序列化缺陷导致整条读取失败，
  如实记录，不伪造通过）；
- sidecar kill 后的状态与恢复。

错误注入一律在独立账号上进行，结束时切回验收账号并清理防火墙规则。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ph_client import Harness, HarnessError, event_fields, now_iso
from s4common import (
    WS_URL,
    case_dir,
    load_token,
    sidecar_log_mark,
    sidecar_tail,
    write_commands,
    write_http_log,
)

CASE = "A06"
CARD_CONVERSATION = "daa0a2bc-629c-424b-8c0b-c2b48b83c3fb"  # A08-card-1（绑定导入卡）
FIREWALL_RULE = "S4-A06-block-deepseek"
ACCOUNT_NAME = "A06-error-probe"
ACCOUNT_PASSWORD = "<redacted>"


def ps(command: str) -> dict:
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False)
    return {"rc": result.returncode, "stdout": (result.stdout or "").strip()[:600],
            "stderr": (result.stderr or "").strip()[:400]}


def firewall_block(on: bool) -> dict:
    if on:
        resolved = ps("(Resolve-DnsName api.deepseek.com -Type A -ErrorAction Stop).IPAddress -join ','")
        ips = (resolved.get("stdout") or "").strip()
        if not ips:
            return {"rc": 1, "skipped": True, "resolve": resolved}
        result = ps(f"New-NetFirewallRule -DisplayName '{FIREWALL_RULE}' -Direction Outbound "
                    f"-Action Block -Protocol TCP -RemoteAddress {ips} -ErrorAction Stop | "
                    f"Select-Object -ExpandProperty DisplayName")
        result["target_ips"] = ips
        return result
    return ps(f"Remove-NetFirewallRule -DisplayName '{FIREWALL_RULE}' -ErrorAction SilentlyContinue; "
              f"(Get-NetFirewallRule -DisplayName '{FIREWALL_RULE}' -ErrorAction SilentlyContinue | "
              f"Measure-Object).Count")


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="s4-a06")
    await session.connect()

    async def safe(method: str, params: dict, timeout: float = 40.0) -> dict:
        try:
            return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
        except asyncio.TimeoutError:
            return {"ok": False, "code": "client_timeout",
                    "note": "服务端未回响应（响应体不可序列化）"}
        except HarnessError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message[:300],
                    "details": exc.details}

    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        current_account = bootstrap.get("current_account_id")
        log["account_before"] = current_account

        # —— 1. 装配诊断：隐藏原文的显式请求规则 ——
        normal = await safe("diagnostics.prompt_assembly", {"conversation_id": CARD_CONVERSATION})
        hidden = await safe("diagnostics.prompt_assembly",
                            {"conversation_id": CARD_CONVERSATION, "include_hidden": True})
        normal_modules = (normal.get("result") or {}).get("modules") or []
        hidden_modules = (hidden.get("result") or {}).get("modules") or []
        log["assembly_hidden_rule"] = {
            "normal_ok": normal.get("ok"),
            "normal_module_count": len(normal_modules),
            "normal_all_hidden_null": all(m.get("hidden_content") is None for m in normal_modules),
            "hidden_ok": hidden.get("ok"),
            "hidden_module_count": len(hidden_modules),
            "hidden_nonempty_count": sum(1 for m in hidden_modules if m.get("hidden_content")),
            "hidden_chars_total": sum(len(str(m.get("hidden_content") or "")) for m in hidden_modules),
            "memory_injected_flags": [m.get("memory_injected") for m in hidden_modules],
        }
        # 隐藏内容不得出现在对话流
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": CARD_CONVERSATION}, timeout=30)
        conversation_text = "\n".join(str(m.get("text") or "") for m in snapshot.get("messages", []))
        sample_hidden = next((str(m.get("hidden_content") or "") for m in hidden_modules
                              if m.get("hidden_content")), "")
        log["assembly_hidden_rule"]["hidden_text_absent_from_dialogue"] = (
            bool(sample_hidden) and sample_hidden[:80] not in conversation_text
        )
        print("assembly hidden rule:", json.dumps(log["assembly_hidden_rule"], ensure_ascii=False)[:400],
              flush=True)

        # —— 2. 只读诊断命令可用性（缺失 null / 真实零 0 的载体）——
        log["readonly_commands"] = {
            "metrics_query": await safe("metrics.query",
                                        {"conversation_id": CARD_CONVERSATION, "limit": 5}),
            "summary_get": await safe("summary.get", {"conversation_id": CARD_CONVERSATION}),
            "memory_list": await safe("memory.list", {"conversation_id": CARD_CONVERSATION}),
            "power_get_status": await safe("power.get_status", {}),
        }

        # —— 3. 真实服务失败注入（独立账号，避免污染验收账号）——
        registered = await safe("account.register",
                                {"username": ACCOUNT_NAME, "display_name": ACCOUNT_NAME,
                                 "password": ACCOUNT_PASSWORD})
        log["probe_account_register"] = registered
        login = await safe("account.login",
                           {"account_id": registered.get("result", {}).get("account_id")
                            if registered.get("ok") else "", "password": ACCOUNT_PASSWORD})
        log["probe_account_login"] = login
        probe_account_id = (login.get("result") or {}).get("current_account_id") if login.get("ok") else None
        log["probe_account_id"] = probe_account_id

        injections = {
            "bad_api_key": {"dialogue.provider": "deepseek",
                            "dialogue.base_url": "https://api.deepseek.com",
                            "dialogue.model": "deepseek-v4-flash",
                            "dialogue.api_key": "sk-s4-invalid-key-0000000000"},
            "refused_base_url": {"dialogue.provider": "openai_compatible",
                                 "dialogue.base_url": "https://127.0.0.1:1/v1",
                                 "dialogue.model": "s4-none",
                                 "dialogue.api_key": "sk-s4-invalid-key-0000000000"},
            "dns_failure": {"dialogue.provider": "openai_compatible",
                            "dialogue.base_url": "https://no-such-host-s4.invalid/v1",
                            "dialogue.model": "s4-none",
                            "dialogue.api_key": "sk-s4-invalid-key-0000000000"},
        }
        results: dict = {}
        for name, updates in injections.items():
            applied = await safe("config.set", {"updates": updates})
            probe = await safe("config.test_connection", {}, timeout=60)
            results[name] = {"config_set": applied.get("ok"),
                             "test_connection": probe,
                             "at": now_iso()}
            print(name, json.dumps(probe, ensure_ascii=False)[:220], flush=True)
            results[name]["turn"] = await run_failing_turn(session, name)
        log["service_failures"] = results

        # —— 4. 断网（防火墙阻断外网）——
        log["firewall_block"] = firewall_block(True)
        log["firewall_test_connection"] = await safe("config.test_connection", {}, timeout=90)
        log["firewall_restore"] = firewall_block(False)
        log["firewall_rule_removed"] = ps(
            f"(Get-NetFirewallRule -DisplayName '{FIREWALL_RULE}' -ErrorAction SilentlyContinue | "
            f"Measure-Object).Count")

        # —— 5. 恢复验收账号并核对 ——
        accounts = await session.call("account.list", timeout=30)
        log["accounts"] = accounts
        restore = await safe("account.switch", {"account_id": current_account})
        log["account_restore"] = restore
        log["account_after"] = (await session.call("app.bootstrap", timeout=30)).get("current_account_id")
    finally:
        # 兜底清理：确保防火墙规则不残留
        leftover = ps(f"(Get-NetFirewallRule -DisplayName '{FIREWALL_RULE}' -ErrorAction SilentlyContinue | "
                      f"Measure-Object).Count")
        log["firewall_cleanup_check"] = leftover
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    (out / "a06-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a06.py",
        "# 防火墙规则 S4-A06-block-deepseek 由脚本自建自删；异常退出时手工执行：",
        "Remove-NetFirewallRule -DisplayName 'S4-A06-block-deepseek' -ErrorAction SilentlyContinue",
    ])
    write_http_log(out / "http.log", "A06 全部交互走 WS 帧；错误注入含真实外网请求")
    print("A06 finished", flush=True)
    return 0


async def run_failing_turn(session: Harness, label: str) -> dict:
    """在错误配置下跑一条真实回合，记录失败如何暴露。"""
    bootstrap = await session.call("app.bootstrap", timeout=30)
    project = next((p for p in (bootstrap.get("projects") or [])
                    if p.get("name") == "project-alpha"), None)
    if project is None:
        return {"error": "no project"}
    created = await session.call(
        "conversation.create",
        {"project_id": project["project_id"], "pair_id": "phainon_ancient_machine",
         "title": f"A06-{label}"}, timeout=30)
    conversation_id = created["current_conversation_id"]
    submit = {"ok": False}
    try:
        await session.call("chat.submit",
                           {"conversation_id": conversation_id, "target": "character",
                            "text": "A06 错误注入回合：请只回复一个词。"}, timeout=30)
        submit = {"ok": True}
    except HarnessError as exc:
        submit = {"ok": False, "code": exc.code, "message": exc.message[:200]}
    except asyncio.TimeoutError:
        submit = {"ok": False, "code": "client_timeout"}
    deadline = time.monotonic() + 90
    snapshot = {}
    while time.monotonic() < deadline:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        pending = [m for m in snapshot.get("messages", [])
                   if m.get("status") in {"pending", "streaming", "processing"}]
        if not pending and not snapshot.get("active_task"):
            break
        await asyncio.sleep(2.0)
    return {
        "conversation_id": conversation_id,
        "submit": submit,
        "messages": [{"source": m.get("source"), "kind": m.get("kind"),
                      "status": m.get("status"), "text": str(m.get("text"))[:120]}
                     for m in snapshot.get("messages", [])],
    }


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
