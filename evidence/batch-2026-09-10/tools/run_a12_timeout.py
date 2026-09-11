"""A12（超时部分）：制造一个真实审批并挂机等待真实 600 秒超时。

要点：
- 审批超时常量 `APPROVAL_TIMEOUT_S = 600.0` 是硬编码，不可配置，
  因此不存在"短超时等效"路径；本脚本按真实 600 秒挂机执行。
- 等待期间不裁决该审批，改由服务端产生 timeout 终态。
- 记录：approval.requested → 等待时长 → approval.resolved(timeout) → 回合终态。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone

from ph_client import Harness, HarnessError, event_fields, now_iso
from s4common import case_dir, load_token, sidecar_log_mark, sidecar_tail, WS_URL

CASE = "A12"
APPROVAL_TIMEOUT_S = 600.0


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    timeline: list[dict] = []

    def note(event: str, **fields: object) -> None:
        record = {"ts": now_iso(), "event": event, **fields}
        timeline.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)

    async with Harness(
        WS_URL, token, frames_log=out / "ws-frames-timeout.log",
        events_log=out / "events-timeout.log", device_name="s4-a12-timeout",
    ) as h:
        bootstrap = await h.call("app.bootstrap", timeout=30)
        projects = bootstrap.get("projects") or []
        project = next(p for p in projects if p.get("name") == "project-alpha")
        project_id = project["project_id"]

        existing = next(
            (
                c
                for p in projects
                for c in (p.get("conversations") or [])
                if c.get("title") == "A12-approval-timeout"
            ),
            None,
        )
        if existing is not None:
            conversation_id = existing["conversation_id"]
            note("conversation.reused", conversation_id=conversation_id)
        else:
            created = await h.call(
                "conversation.create",
                {"project_id": project_id, "pair_id": "phainon_ancient_machine",
                 "title": "A12-approval-timeout"},
                timeout=30,
            )
            conversation_id = created["current_conversation_id"]
            note("conversation.created", conversation_id=conversation_id,
                 project_id=project_id)
        await h.call("conversation.set_mode",
                     {"conversation_id": conversation_id, "mode": "collaboration"}, timeout=30)

        task_text = (
            "请让神秘的古代机械在项目根目录新建文件 a12-timeout.md，"
            "内容写一行：S4-A12-审批超时挂机样本。写完后回报结果。"
        )
        submitted = await h.call(
            "chat.submit",
            {"conversation_id": conversation_id, "target": "assistant", "text": task_text},
            timeout=60,
        )
        note("chat.submit.accepted", conversation_id=conversation_id,
             message_id=submitted.get("message_id") if isinstance(submitted, dict) else None)

        requested = await h.wait_event(
            "approval.requested",
            timeout=300,
            predicate=lambda e: event_fields(e).get("conversation_id") == conversation_id,
        )
        approval_fields = event_fields(requested)
        approval_id = approval_fields.get("approval_id")
        requested_at = time.monotonic()
        note("approval.requested", approval_id=approval_id,
             conversation_id=approval_fields.get("conversation_id"),
             task_id=approval_fields.get("task_id"),
             operation=approval_fields.get("operation"),
             reason=approval_fields.get("reason"))
        print(f"WAITING {APPROVAL_TIMEOUT_S:.0f}s for server-side timeout…", flush=True)

        resolved = await h.wait_event(
            "approval.resolved",
            timeout=APPROVAL_TIMEOUT_S + 180,
            predicate=lambda e: event_fields(e).get("approval_id") == approval_id,
        )
        waited = time.monotonic() - requested_at
        resolved_fields = event_fields(resolved)
        note("approval.resolved", approval_id=approval_id,
             decision=resolved_fields.get("decision"),
             resolved_by=resolved_fields.get("resolved_by"),
             actor=resolved_fields.get("actor"), reason=resolved_fields.get("reason"),
             error_code=resolved_fields.get("error_code"),
             waited_s=round(waited, 3))

        # 生成 600 秒后迟到的裁决：应被拒且携带真实终态
        late_error = None
        try:
            await h.call("approval.resolve",
                         {"approval_id": approval_id, "decision": "allow"}, timeout=30)
        except HarnessError as exc:
            late_error = {"code": exc.code, "message": exc.message, "details": exc.details}
        note("late_decision", approval_id=approval_id, error=late_error)

        await asyncio.sleep(20)
        snapshot = await h.call("conversation.open",
                                {"conversation_id": conversation_id}, timeout=60)
        note("conversation.final",
             messages=[{"source": m.get("source"), "kind": m.get("kind"),
                        "status": m.get("status"), "text": str(m.get("text"))[:120]}
                       for m in snapshot.get("messages", [])],
             turns=snapshot.get("turns"), active_task=snapshot.get("active_task"))

    new_lines = sidecar_tail(out / "sidecar.log")
    (out / "timer-timeline.json").write_text(
        json.dumps(
            {
                "approval_timeout_s_constant": APPROVAL_TIMEOUT_S,
                "configurable": False,
                "note": "常量硬编码于 application_service.py:335，无可配置入口，故无短超时等效路径",
                "timeline": timeline,
                "sidecar_new_lines": new_lines,
            },
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print("A12 timeout probe finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
