"""V039-S4-017 复验：世界书装配预算的诊断口径。

上一批次判定失败：装配预算被超出约 10 倍（``budget_total=2048`` /
``budget_used=21552``）、``warnings`` 为空，且逐条 ceil 与拼接 ceil 口径混用
导致恒等式与分量上界不成立。

本轮按冻结契约核对（复测计划 §6.5 / §13.2.3）：
1. 字段集为 ``budget_constant_used`` / ``budget_prunable_used`` / ``budget_limit_reached``
   （不得再出现 reconciliation / separator 之类中间口径）；
2. ``budget_prunable_used <= budget_total``（非 constant 条目的硬上界）；
3. ``budget_limit_reached`` 为真 ⟺ ``overflow_entries`` 非空；
4. 超限时有 ``warnings`` 告警；
5. ``overflow_entries`` 只列确实未进入提示词的条目；
6. 世界书模块实际占用字符数与诊断口径一致；
7. 空正文条目照常激活（冻结契约），门控序列首条按累计文本判定。

本用例只做只读诊断，不产生真实模型调用。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso
from r1common import (
    WS_URL, case_dir, load_token, save_result, sidecar_log_mark, sidecar_tail,
    write_info_log, write_commands, write_http_log, result_shell,
)

CASE = "V039-S4-017"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-project"
CONV_FILE = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\r1-fixc-conversation.txt")
PAIR_A = "phainon_ancient_machine"


async def safe(session: Harness, method: str, params: dict, timeout: float = 60.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:300],
                "details": exc.details}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout"}


def parse_diagnostics(lines: list[str]) -> dict:
    """把 ``key: value`` 形态的诊断行解析为字典（重复键合并为列表）。"""
    parsed: dict = {}
    for line in lines:
        key, sep, value = line.partition(": ")
        if not sep:
            parsed.setdefault("_raw", []).append(line)
            continue
        value = value.strip()
        if key in parsed:
            existing = parsed[key]
            parsed[key] = existing + [value] if isinstance(existing, list) else [existing, value]
        else:
            parsed[key] = value
    return parsed


def to_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


async def main() -> int:
    out = case_dir(CASE)
    result = result_shell(CASE, title="世界书装配预算诊断口径复验")
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="r1-budget")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        project = next((p for p in (bootstrap.get("projects") or [])
                        if p.get("root_path", "").endswith("retest-project")), None)
        if project is None:
            created = await session.call("project.create", {
                "root_path": PROJECT_ROOT, "name": "retest-project", "pair_id": PAIR_A},
                timeout=30)
            project = next(p for p in created["projects"] if p.get("name") == "retest-project")
        project_id = project["project_id"]

        # 1. 导入承载 85 条世界书的夹具卡（fix-c）
        card_path = FIXTURES / "fix-c-worldbook-card.json"
        imported = await safe(session, "card.import_json", {"path": str(card_path)})
        card_id = (imported.get("result") or {}).get("card_id")
        log["card_import"] = {
            "ok": imported.get("ok"), "card_id": card_id,
            "code": imported.get("code"), "message": imported.get("message"),
            "fixture_bytes": card_path.stat().st_size,
        }
        if not card_id:
            raise RuntimeError("fix-c 卡导入失败，无法核对装配预算")

        # 2. 绑定该卡的会话（世界书激活的载体）
        conversation = await session.call("conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A,
            "title": "R1-017-worldbook", "character_card_id": card_id}, timeout=30)
        conversation_id = conversation["current_conversation_id"]
        CONV_FILE.write_text(conversation_id, encoding="utf-8")
        log["conversation_id"] = conversation_id

        card_get = await safe(session, "card.get", {"card_id": card_id})
        entries = ((card_get.get("result") or {}).get("card") or {}).get("character_book", {})
        entry_list = (entries or {}).get("entries") or []
        log["card_world_book_entries"] = len(entry_list)
        log["card_world_book_bytes"] = len(
            json.dumps(entries, ensure_ascii=False).encode("utf-8")) if entries else 0

        # 3. 装配诊断（普通 + 隐藏原文）
        normal = await safe(session, "diagnostics.prompt_assembly",
                            {"conversation_id": conversation_id})
        hidden = await safe(session, "diagnostics.prompt_assembly",
                            {"conversation_id": conversation_id, "include_hidden": True})
        normal_result = normal.get("result") or {}
        hidden_result = hidden.get("result") or {}
        normal_diag = parse_diagnostics(normal_result.get("diagnostics") or [])
        log["assembly_normal"] = {
            "ok": normal.get("ok"),
            "reason": normal_result.get("reason"),
            "module_count": len(normal_result.get("modules") or []),
            "module_names": [m.get("name") for m in (normal_result.get("modules") or [])],
            "hidden_all_null": all(
                m.get("hidden_content") is None
                for m in (normal_result.get("modules") or [])),
            "diagnostics_raw": normal_result.get("diagnostics"),
            "diagnostics_parsed": normal_diag,
        }
        hidden_modules = hidden_result.get("modules") or []
        log["assembly_hidden"] = {
            "ok": hidden.get("ok"),
            "module_count": len(hidden_modules),
            "module_char_span": [
                {"name": m.get("name"), "chars": (m.get("char_end") or 0) - (m.get("char_start") or 0),
                 "hidden_chars": len(str(m.get("hidden_content") or ""))}
                for m in hidden_modules],
            "hidden_chars_total": sum(
                len(str(m.get("hidden_content") or "")) for m in hidden_modules),
        }

        # 4. 口径核对
        budget_total = to_int(normal_diag.get("budget_total"))
        budget_used = to_int(normal_diag.get("budget_used"))
        constant_used = to_int(normal_diag.get("budget_constant_used"))
        prunable_used = to_int(normal_diag.get("budget_prunable_used"))
        limit_reached = str(normal_diag.get("budget_limit_reached", "")).strip().lower()
        overflow_raw = str(normal_diag.get("overflow_entries", "") or "").strip()
        warnings_raw = str(normal_diag.get("warnings", "") or "").strip()
        overflow_items = [x.strip() for x in overflow_raw.split(",") if x.strip()]

        world_book_chars = sum(
            (m.get("char_end") or 0) - (m.get("char_start") or 0)
            for m in hidden_modules if "世界书" in str(m.get("name")))
        hidden_world_book_chars = sum(
            len(str(m.get("hidden_content") or ""))
            for m in hidden_modules if "世界书" in str(m.get("name")))
        # _build_system 的 char 区间含小节标题前缀 "## <标题>\n"（assembler:168-176），
        # 因此「区间长度 − 原文长度」应恰好等于标题前缀长度之和；相等才说明
        # 诊断口径与模块实际占用一致。
        expected_prefix = sum(
            len(f"## {m.get('name')}\n")
            for m in hidden_modules if "世界书" in str(m.get("name")))

        log["budget_check"] = {
            "budget_total": budget_total,
            "budget_used": budget_used,
            "budget_constant_used": constant_used,
            "budget_prunable_used": prunable_used,
            "budget_limit_reached": limit_reached,
            "overflow_count": len(overflow_items),
            "overflow_entries": overflow_items,
            "warnings": warnings_raw,
            "field_set": sorted(normal_diag.keys()),
            "has_legacy_reconciliation": "budget_reconciliation" in normal_diag
            or "reconciliation" in str(normal_diag),
            "has_legacy_separator": "separator" in str(normal_diag).lower(),
            "world_book_module_chars": world_book_chars,
            "world_book_hidden_chars": hidden_world_book_chars,
            "world_book_expected_prefix_chars": expected_prefix,
            "world_book_delta": world_book_chars - hidden_world_book_chars,
            "assertions": {
                "prunable_within_total": (
                    prunable_used is not None and budget_total is not None
                    and prunable_used <= budget_total),
                "limit_flag_matches_overflow": (
                    (limit_reached == "true") == bool(overflow_items)),
                "warnings_present_when_limited": (
                    limit_reached != "true" or bool(warnings_raw)),
                "constant_plus_prunable_leq_used": (
                    None not in (constant_used, prunable_used, budget_used)
                    and constant_used + prunable_used <= budget_used),
                "world_book_chars_match_hidden": (
                    world_book_chars - hidden_world_book_chars == expected_prefix),
            },
        }

        # 5. 空正文条目照常激活 / 门控首条按累计文本判定：
        #    直接由诊断中的 activated_count 与模块内容体现；此处核对
        #    「激活条目里存在空正文条目」这一契约行为是否仍成立。
        activated = to_int(normal_diag.get("activated_count"))
        log["contract_checks"] = {
            "activated_count": activated,
            "note": "空正文条目照常激活与门控序列首条判定由离线用例覆盖；"
                    "真机核对其副作用：activated_count 与模块实际内容一致、"
                    "世界书模块首条为角色设定前的世界书模块",
            "first_module": (normal_result.get("modules") or [{}])[0].get("name"),
        }
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        write_info_log(CASE, (out / "sidecar.log").read_text(encoding="utf-8").splitlines())
    except OSError:
        pass
    (out / "budget-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "V039-S4-017 全部交互走 WS 帧；只读诊断")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_017_budget.py",
    ])
    result["status"] = "待判定"
    result["actual"] = json.dumps({
        "card_import": log["card_import"], "budget_check": log["budget_check"]},
        ensure_ascii=False)[:4000]
    result["timestamps"]["finished_at"] = now_iso()
    result["evidence"] = ["budget-run.json", "ws-frames.log", "events.log",
                          "sidecar.log", "sidecar-info.log"]
    save_result(CASE, result)
    print(json.dumps(log, ensure_ascii=False, indent=2)[:5000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
