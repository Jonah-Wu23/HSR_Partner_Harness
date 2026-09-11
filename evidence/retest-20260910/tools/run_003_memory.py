"""V039-S4-003 复验：长期记忆的写入、作用域、增删改与入口（协议级）。

上一批次判定失败的原因是「无写入路径且无入口」。本轮复验四件事：
1. memory.create 真实落库并广播 memory.updated；
2. 作用域以会话权威解析（同 pair 跨聊天共享、不同 pair 隔离）；
3. 增删改（create / update / delete）实际生效，非法输入按真实错误拒绝；
4. 无项目会话按真实错误拒绝，且不产生部分写入。

不调用真实模型（除「模型产出 memory」子项外，该子项由 B-05 的真实委派回合覆盖）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ph_client import Harness, HarnessError, event_fields, now_iso
from r1common import (
    WS_URL,
    case_dir,
    load_token,
    poll_conversation,
    save_result,
    sidecar_log_mark,
    sidecar_tail,
    write_info_log,
    write_commands,
    write_http_log,
    result_shell,
)

CASE = "V039-S4-003"
PROJECT_ROOT = r"E:\AI\HSR-Partner-Harness-v0.3.9-logic\.tmp\retest-project"
PAIR_A = "phainon_ancient_machine"


async def safe(session: Harness, method: str, params: dict, timeout: float = 30.0) -> dict:
    try:
        return {"ok": True, "result": await session.call(method, params, timeout=timeout)}
    except HarnessError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message[:400],
                "details": exc.details}
    except asyncio.TimeoutError:
        return {"ok": False, "code": "client_timeout", "message": f"{method} 无响应"}


async def main() -> int:
    out = case_dir(CASE)
    result = result_shell(CASE, title="长期记忆写入、作用域、增删改与入口复验")
    result["preconditions"] = {
        "candidate": "工作树快照（含 memory.create / MemoryDraft / memory_enabled 修复）",
        "data": "首次运行清理后的干净数据库（本用例自建项目与会话）",
    }
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}
    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="r1-memory")
    await session.connect()
    try:
        bootstrap = await session.call("app.bootstrap", timeout=30)
        account_id = bootstrap.get("current_account_id")
        log["account_id"] = account_id

        # 1. 建项目（记忆作用域的载体）与两个聊天
        Path(PROJECT_ROOT).mkdir(parents=True, exist_ok=True)
        created_project = await safe(session, "project.create", {
            "root_path": PROJECT_ROOT, "name": "retest-project",
            "pair_id": PAIR_A,
        })
        log["project_create"] = {
            "ok": created_project.get("ok"),
            "code": created_project.get("code"),
            "message": created_project.get("message"),
            "projects": [
                {k: p.get(k) for k in ("project_id", "name", "root_path")}
                for p in ((created_project.get("result") or {}).get("projects") or [])
            ],
            "conversations": [
                {k: c.get(k) for k in ("conversation_id", "title", "pair_id")}
                for c in ((created_project.get("result") or {}).get("conversations") or [])
            ],
        }
        project_id = next(
            (p["project_id"] for p in ((created_project.get("result") or {}).get("projects") or [])
             if p.get("name") == "retest-project"), None)
        log["project_id"] = project_id
        # project.create 返回的 conversations 在本候选上为空数组（未复现出复用行为），
        # 因此显式新建两个聊天作为作用域载体，不依赖其返回值。
        chat1 = await safe(session, "conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A, "title": "R1-memory-chat1"})
        conv1 = (chat1.get("result") or {}).get("current_conversation_id")
        log["conversation_1"] = conv1
        log["conversation_create_1"] = {"ok": chat1.get("ok"), "code": chat1.get("code"),
                                        "message": chat1.get("message")}

        chat2 = await safe(session, "conversation.create", {
            "project_id": project_id, "pair_id": PAIR_A, "title": "R1-memory-chat2"})
        conv2 = (chat2.get("result") or {}).get("current_conversation_id")
        log["conversation_2"] = conv2

        # 2. memory.create 落库 + 事件
        mark = len(session.events)
        first = await safe(session, "memory.create", {
            "conversation_id": conv1,
            "content": {"fact": "复测批次写入的记忆 A", "source": "r1-memory"},
        })
        log["memory_create"] = {
            "ok": first.get("ok"), "code": first.get("code"),
            "message": first.get("message"),
            "result": first.get("result"),
        }
        try:
            envelope = await session.wait_event(
                "memory.updated", timeout=10,
                predicate=lambda e: event_fields(e).get("conversation_id") == conv1)
            log["memory_updated_event"] = {
                "received": True, "payload": event_fields(envelope)}
        except asyncio.TimeoutError:
            log["memory_updated_event"] = {"received": False}
        memory_id = ((first.get("result") or {}).get("memory") or {}).get("memory_id")

        # 3. 幂等：同内容重复 create
        second = await safe(session, "memory.create", {
            "conversation_id": conv1,
            "content": {"fact": "复测批次写入的记忆 A", "source": "r1-memory"},
        })
        log["memory_create_repeat"] = {
            "ok": second.get("ok"), "code": second.get("code"),
            "memory_id": ((second.get("result") or {}).get("memory") or {}).get("memory_id"),
            "same_id_as_first": (
                ((second.get("result") or {}).get("memory") or {}).get("memory_id")
                == memory_id),
        }

        # 4. 作用域：同 pair 跨聊天可见
        listed_chat2 = await safe(session, "memory.list", {"conversation_id": conv2})
        items_chat2 = (listed_chat2.get("result") or {}).get("memories") or []
        log["scope_cross_chat"] = {
            "chat2_ok": listed_chat2.get("ok"),
            "chat2_count": len(items_chat2),
            "contains_first": any(
                (m.get("content") or {}).get("fact") == "复测批次写入的记忆 A"
                if isinstance(m.get("content"), dict)
                else ("复测批次写入的记忆 A" in str(m.get("content")))
                for m in items_chat2),
            "scopes": [m.get("scope") or {
                k: m.get(k) for k in ("project_id", "pair_id", "character_ref",
                                      "assistant_identity")} for m in items_chat2],
        }

        # 5. 不同 pair 隔离（用从未写入过记忆的 firefly_sam，避免历史残留干扰）
        other_pair = await safe(session, "conversation.create", {
            "project_id": project_id, "pair_id": "firefly_sam",
            "title": "R1-memory-other-pair"})
        conv_other = (other_pair.get("result") or {}).get("current_conversation_id")
        list_other = await safe(session, "memory.list", {"conversation_id": conv_other})
        log["scope_other_pair"] = {
            "conversation_id": conv_other,
            "ok": list_other.get("ok"),
            "code": list_other.get("code"),
            "message": list_other.get("message"),
            "count": len((list_other.get("result") or {}).get("memories") or []),
        }

        # 6. 幂等/非法输入的显式拒绝
        log["invalid_inputs"] = {
            "no_conversation": await safe(session, "memory.create", {"content": {"a": 1}}),
            "content_not_object": await safe(session, "memory.create", {
                "conversation_id": conv1, "content": "不是对象"}),
            "content_empty_object": await safe(session, "memory.create", {
                "conversation_id": conv1, "content": {}}),
            "unknown_conversation": await safe(session, "memory.create", {
                "conversation_id": "00000000-0000-0000-0000-000000000000",
                "content": {"a": 1}}),
        }

        # 7. update / delete 实际生效
        if memory_id:
            updated = await safe(session, "memory.update", {
                "conversation_id": conv1, "memory_id": memory_id,
                "content": {"fact": "复测批次改写后的记忆 A", "source": "r1-memory"}})
            log["memory_update"] = {"ok": updated.get("ok"), "code": updated.get("code"),
                                    "result": updated.get("result")}
            listed_after = await safe(session, "memory.list", {"conversation_id": conv1})
            log["memory_update_visible"] = any(
                "改写后" in str(m.get("content"))
                for m in ((listed_after.get("result") or {}).get("memories") or []))
            deleted = await safe(session, "memory.delete", {
                "conversation_id": conv1, "memory_id": memory_id})
            log["memory_delete"] = {"ok": deleted.get("ok"), "code": deleted.get("code"),
                                    "result": deleted.get("result")}
            listed_final = await safe(session, "memory.list", {"conversation_id": conv1})
            log["memory_delete_visible"] = [
                m.get("memory_id")
                for m in ((listed_final.get("result") or {}).get("memories") or [])]
        else:
            log["memory_update"] = {"skipped": "create 未返回 memory_id"}

        # 8. 无项目会话拒绝
        # 说明：conversation.create 未给 project_id 时回落到 current_project_id
        # （_conversation_create），当前账号始终有当前项目，因此在真实数据上
        # 无法构造「日常聊天（无项目）」。此处如实记录该构造尝试的结果，
        # 不把「没构造出来」当作通过。
        daily = await safe(session, "conversation.create", {
            "title": "R1-daily-no-project", "project_id": None})
        conv_daily = (daily.get("result") or {}).get("current_conversation_id")
        log["no_project_conversation"] = {
            "attempted": "conversation.create 不带 project_id（并显式传 null）",
            "constructed": conv_daily,
            "note": "当前账号有 current_project_id，协议回落到该项目，未能构造无项目会话",
            "memory_create": await safe(session, "memory.create", {
                "conversation_id": conv_daily, "content": {"a": 1}}),
            "memory_list": await safe(session, "memory.list", {
                "conversation_id": conv_daily}),
        }
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    try:
        write_info_log(CASE, (out / "sidecar.log").read_text(
            encoding="utf-8").splitlines())
    except OSError:
        pass
    (out / "memory-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_http_log(out / "http.log", "V039-S4-003 全部交互走 WS 帧")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\retest-20260910\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\.venv\\Scripts\\python.exe' run_003_memory.py",
    ])
    result["status"] = "待判定"
    result["actual"] = json.dumps(log, ensure_ascii=False)[:4000]
    result["timestamps"]["finished_at"] = now_iso()
    result["evidence"] = ["memory-run.json", "ws-frames.log", "events.log",
                          "sidecar.log", "sidecar-info.log"]
    save_result(CASE, result)
    print(json.dumps(log, ensure_ascii=False, indent=2)[:4000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
