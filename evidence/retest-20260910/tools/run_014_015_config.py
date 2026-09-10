"""V039-S4-014 / V039-S4-015 复验：配置结论归属与失败原因。

V039-S4-014（证据更正后按 §13.3 判定）：
 (a) 端点写入被拒（base_url 指向不可达/错误域）必须是**可定位的明确拒绝**；
 (b) 引擎与端点不兼容导致的「候选运行时构建失败」必须回结构化错误码
     （修复前落成 internal_error，调用方无从判断配置是否写入）；
 (c) ``config.test_connection`` 一律回传实际探测的 provider/base_url/model。

V039-S4-015：真实失败回合的失败原因不得是「本次回复失败：」空壳，必须携带
真实可得的原因；本用例保留该回合的未过滤 sidecar 日志以坐实成因。

错误注入在独立账号上进行，结束时切回验收账号。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso
from r1common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell,
)

CASE14 = "V039-S4-014"
CASE15 = "V039-S4-015"
PROBE_ACCOUNT = "R1-error-probe"
PROBE_PASSWORD = "r1probe2026"


async def safe(session: Harness, method: str, params: dict, timeout: float = 40.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:600],
                "details": exc.details}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout", "note": f"{method} 无响应"}


async def wait_settled(session: Harness, conversation_id: str,
                       timeout: float = 180.0) -> tuple[dict, list[dict]]:
    """轮询会话直到失败回合结束；返回快照与逐次状态轨迹。

    失败回合的「可见提示」是 015 的判定对象，因此这里既不能提前返回
    （只看到用户消息），也不能只看终态：轨迹本身是证据。
    """
    deadline = asyncio.get_running_loop().time() + timeout
    snapshot: dict = {}
    history: list[dict] = []
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await session.call("conversation.open",
                                      {"conversation_id": conversation_id}, timeout=30)
        messages = snapshot.get("messages", [])
        non_user = [m for m in messages if m.get("source") != "user"]
        history.append({
            "at": now_iso(),
            "message_count": len(messages),
            "sources": [f"{m.get('source')}/{m.get('kind')}/{m.get('status')}"
                        for m in messages],
            "active_task": bool(snapshot.get("active_task")),
            "has_failure_notice": any(
                "失败" in str(m.get("text") or "") for m in messages),
        })
        if non_user and not snapshot.get("active_task"):
            break
        await asyncio.sleep(2.0)
    return snapshot, history


async def main() -> int:
    out14 = case_dir(CASE14)
    out15 = case_dir(CASE15)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out14 / "ws-frames.log",
                      events_log=out14 / "events.log", device_name="r1-config")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        original_account = bootstrap.get("current_account_id")
        log["account_before"] = original_account
        log["config_before"] = await safe(session, "config.get", {})

        # —— 1. 端点拒绝：base_url 指向本机不可达端口 ——
        log["inject_refused_base_url"] = {
            "config_set": await safe(session, "config.set", {"updates": {
                "dialogue.provider": "openai_compatible",
                "dialogue.base_url": "https://127.0.0.1:1/v1",
                "dialogue.model": "s4-none",
                "dialogue.api_key": "sk-r1-invalid-0000"}}),
        }
        log["inject_refused_base_url"]["config_after"] = await safe(
            session, "config.get", {})

        # —— 2. 引擎与端点不兼容 → 候选运行时构建失败（修复前 internal_error）——
        log["inject_provider_switch"] = {
            "config_set": await safe(session, "config.set", {"updates": {
                "engine": "codex",
                "dialogue.provider": "openai_compatible",
                "dialogue.base_url": "https://api.deepseek.com",
                "dialogue.model": "deepseek-v4-flash",
                "dialogue.api_key": "sk-r1-invalid-0000"}}),
        }
        log["inject_provider_switch"]["config_after"] = await safe(
            session, "config.get", {})

        # —— 3. test_connection 结论可归属 ——
        log["test_connection_active"] = await safe(
            session, "config.test_connection", {}, timeout=60)

        # —— 4. 真实失败回合（错误 Key）→ 失败原因必须非空 ——
        accounts = await safe(session, "account.list", {})
        existing_probe = next(
            (a for a in ((accounts.get("result") or {}).get("accounts") or [])
             if a.get("username") == PROBE_ACCOUNT), None)
        registered = await safe(session, "account.register", {
            "username": PROBE_ACCOUNT, "display_name": PROBE_ACCOUNT,
            "password": PROBE_PASSWORD})
        log["probe_account_register"] = registered
        probe_account_id = ((existing_probe or {}).get("account_id")
                            or (registered.get("result") or {}).get("account_id"))
        login = await safe(session, "account.login", {
            "account_id": probe_account_id or "", "password": PROBE_PASSWORD})
        log["probe_account_login"] = login
        log["probe_account_id"] = (login.get("result") or {}).get("current_account_id")
        if login.get("ok") is not True or not log["probe_account_id"]:
            # 已处于登录态的账号再走 account.login 不成立时，用账号切换达成同一目标；
            # 上面那次真实结果照原样留在证据里。
            switched = await safe(session, "account.switch",
                                  {"account_id": probe_account_id or ""})
            log["probe_account_switch"] = switched
            current = (await session.call("app.bootstrap", timeout=30)).get("current_account_id")
            log["probe_account_id"] = current
            if current != probe_account_id:
                raise RuntimeError("探测账号切换失败，无法执行 015 的真实失败回合")

        # 探测账号需要自己的项目（项目按账号隔离，不能复用验收账号的目录）
        probe_root = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-probe-project"
        Path(probe_root).mkdir(parents=True, exist_ok=True)
        probe_bootstrap = await safe(session, "project.create", {
            "root_path": probe_root, "name": "retest-probe-project",
            "pair_id": "phainon_ancient_machine"})
        log["probe_project"] = {
            "ok": probe_bootstrap.get("ok"), "code": probe_bootstrap.get("code"),
            "message": probe_bootstrap.get("message"),
            "projects": [
                {k: p.get(k) for k in ("project_id", "name")}
                for p in ((probe_bootstrap.get("result") or {}).get("projects") or [])],
        }

        bad_key = await safe(session, "config.set", {"updates": {
            "dialogue.provider": "deepseek",
            "dialogue.base_url": "https://api.deepseek.com",
            "dialogue.model": "deepseek-v4-flash",
            "dialogue.api_key": "sk-r1-invalid-key-0000000000000000"}})
        log["bad_key_config_set"] = bad_key
        log["bad_key_test_connection"] = await safe(
            session, "config.test_connection", {}, timeout=60)

        bootstrap2 = await session.call("app.bootstrap", timeout=30)
        project = next((p for p in (bootstrap2.get("projects") or [])
                        if p.get("name") == "retest-probe-project"), None)
        failing_turn: dict = {"project_id": (project or {}).get("project_id")}
        if project:
            created = await session.call("conversation.create", {
                "project_id": project["project_id"],
                "pair_id": "phainon_ancient_machine", "title": "R1-015-badkey"},
                timeout=30)
            conversation_id = created["current_conversation_id"]
            failing_turn["conversation_id"] = conversation_id
            try:
                await session.call("chat.submit", {
                    "conversation_id": conversation_id, "target": "character",
                    "text": "复测 015：请只回复一个词。"}, timeout=60)
                failing_turn["submit"] = {"ok": True}
            except HarnessError as exc:
                failing_turn["submit"] = {"ok": False, "code": exc.code,
                                          "message": exc.message[:300]}
            snapshot, history = await wait_settled(session, conversation_id, timeout=200)
            failing_turn["poll_history"] = history
            failing_turn["messages"] = [
                {"source": m.get("source"), "kind": m.get("kind"),
                 "status": m.get("status"), "text": str(m.get("text") or "")[:400],
                 "has_text": bool(str(m.get("text") or "").strip())}
                for m in snapshot.get("messages", [])]
        log["failing_turn_bad_key"] = failing_turn

        # —— 5. 恢复验收账号并核对 ——
        restore = await safe(session, "account.switch", {"account_id": original_account})
        log["account_restore"] = restore
        log["account_after"] = (await session.call("app.bootstrap", timeout=30)
                                ).get("current_account_id")
        log["config_restored"] = await safe(session, "config.get", {})
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out14 / "sidecar.log")
    try:
        info_lines = (out14 / "sidecar.log").read_text(encoding="utf-8").splitlines()
        write_info_log(CASE14, info_lines)
        # 015 需要同一段未过滤日志（错误 Key 回合的成因）
        (out15 / "sidecar.log").write_text(
            "\n".join(info_lines) + ("\n" if info_lines else ""), encoding="utf-8")
        write_info_log(CASE15, info_lines)
    except OSError:
        pass
    payload = json.dumps(log, ensure_ascii=False, indent=2) + "\n"
    (out14 / "config-run.json").write_text(payload, encoding="utf-8")
    (out15 / "failure-run.json").write_text(payload, encoding="utf-8")

    # 014 结果壳（结论在收敛阶段统一判定）
    r14 = result_shell(CASE14, title="配置结论归属复验（端点拒绝/候选拒绝/探测目标）")
    r14["status"] = "待判定"
    r14["actual"] = json.dumps({
        "refused_base_url": log["inject_refused_base_url"],
        "provider_switch": log["inject_provider_switch"],
        "test_connection_active": log["test_connection_active"],
    }, ensure_ascii=False)[:4000]
    r14["timestamps"]["finished_at"] = now_iso()
    r14["evidence"] = ["config-run.json", "ws-frames.log", "events.log",
                       "sidecar.log", "sidecar-info.log"]
    save_result(CASE14, r14)

    r15 = result_shell(CASE15, title="回合失败原因非空复验")
    r15["status"] = "待判定"
    r15["actual"] = json.dumps({
        "bad_key_config_set": log["bad_key_config_set"],
        "failing_turn": log["failing_turn_bad_key"],
    }, ensure_ascii=False)[:4000]
    r15["timestamps"]["finished_at"] = now_iso()
    r15["evidence"] = ["failure-run.json", "sidecar.log", "sidecar-info.log"]
    save_result(CASE15, r15)

    write_http_log(out14 / "http.log", "V039-S4-014/015 全部交互走 WS 帧；含真实失败回合")
    write_http_log(out15 / "http.log", "V039-S4-015 证据与 014 同批采集")
    write_commands(out14 / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_014_015_config.py",
    ])
    print(json.dumps(log, ensure_ascii=False, indent=2)[:5000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
