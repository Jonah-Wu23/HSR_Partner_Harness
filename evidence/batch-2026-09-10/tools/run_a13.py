"""A13：角色库主路径 + 393KB 长世界书的导入导出与长字段操作（协议级）。

- card.import_json 导入 fix-c（v3 卡的 character_book 承载 393KB 世界书）；
- card.get 核对长字段与条目数；
- card.export_json 导出并做导回比对（条目数、正文总字节）；
- card.update 写入长字段并回读，验证长字段可操作；
- 重复导入（as_duplicate）验证去重/复制路径。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

from ph_client import Harness, HarnessError, now_iso
from s4common import (
    WS_URL,
    case_dir,
    load_token,
    sidecar_log_mark,
    sidecar_tail,
    write_commands,
    write_http_log,
)

CASE = "A13"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def book_stats(book: dict | None) -> dict:
    if not book:
        return {"entries": 0, "content_bytes": 0}
    entries = book.get("entries") or []
    return {
        "entries": len(entries),
        "content_bytes": sum(len(str(e.get("content", "")).encode("utf-8")) for e in entries),
    }


async def main() -> int:
    out = case_dir(CASE)
    token = load_token()
    sidecar_log_mark()
    log: dict = {"started_at": now_iso()}

    card_path = FIXTURES / "fix-c-worldbook-card.json"
    source = json.loads(card_path.read_text(encoding="utf-8"))
    log["fixture"] = {"path": str(card_path), "sha256": sha256(card_path),
                      "size": card_path.stat().st_size,
                      "source_book": book_stats(source["data"]["character_book"])}

    session = Harness(WS_URL, token, frames_log=out / "ws-frames.log",
                      events_log=out / "events.log", device_name="s4-a13")
    await session.connect()
    try:
        imported = await session.call("card.import_json", {"path": str(card_path)}, timeout=60)
        card_id = imported["card_id"]
        log["import"] = {
            "card_id": card_id, "name": imported.get("name"), "state": imported.get("state"),
            "report": imported.get("report"),
            "at": now_iso(),
        }
        print("imported", card_id, imported.get("name"), flush=True)

        fetched = await session.call("card.get", {"card_id": card_id}, timeout=30)
        card = fetched.get("card") or {}
        log["card_get"] = {
            "name": card.get("name"),
            "book": book_stats(card.get("character_book")),
            "field_lengths": {
                key: len(str(card.get(key) or ""))
                for key in ("description", "personality", "scenario", "creator_notes", "first_mes")
            },
            "keys": sorted(card.keys())[:30],
        }

        export_path = out / "exported-card.json"
        await session.call("card.export_json",
                           {"card_id": card_id, "path": str(export_path)}, timeout=60)
        exported = json.loads(export_path.read_text(encoding="utf-8"))
        exported_data = exported.get("data") or {}
        log["export"] = {
            "path": str(export_path), "sha256": sha256(export_path),
            "size": export_path.stat().st_size,
            "book": book_stats(exported_data.get("character_book")),
            "roundtrip_entries_equal": (
                book_stats(exported_data.get("character_book"))["entries"]
                == log["fixture"]["source_book"]["entries"]
            ),
        }

        # 长字段操作：写入 393KB 原文到 creator_notes 并回读
        long_text = (FIXTURES / "fix-a-single-msg.txt").read_text(encoding="utf-8")
        try:
            await session.call("card.update",
                               {"card_id": card_id, "fields": {"creator_notes": long_text}},
                               timeout=60)
            update_ok = True
            update_error = None
        except HarnessError as exc:
            update_ok = False
            update_error = {"code": exc.code, "message": exc.message[:200]}
        after = await session.call("card.get", {"card_id": card_id}, timeout=30)
        after_card = after.get("card") or {}
        log["long_field"] = {
            "update_ok": update_ok, "update_error": update_error,
            "written_chars": len(long_text),
            "readback_chars": len(str(after_card.get("creator_notes") or "")),
            "readback_matches": str(after_card.get("creator_notes") or "") == long_text,
        }

        duplicate = await session.call("card.import_json",
                                       {"path": str(card_path), "as_duplicate": True}, timeout=60)
        log["duplicate_import"] = {"card_id": duplicate.get("card_id"),
                                   "name": duplicate.get("name"),
                                   "same_as_first": duplicate.get("card_id") == card_id}

        cards = await session.call("card.list", {"include_archived": True}, timeout=30)
        log["card_list"] = {
            "count": len(cards.get("cards") or []),
            "names": [c.get("name") for c in (cards.get("cards") or [])],
        }
        print(json.dumps({"long_field": log["long_field"],
                          "duplicate": log["duplicate_import"]},
                         ensure_ascii=False)[:400], flush=True)
        log["imported_card_id"] = card_id
    finally:
        await session.close()

    log["finished_at"] = now_iso()
    log["sidecar_new_lines"] = sidecar_tail(out / "sidecar.log")
    (out / "a13-run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_commands(out / "commands.ps1", [
        "cd E:\\AI\\HSR-Partner-Harness-v0.3.9-logic\\evidence\\batch-2026-09-10\\tools",
        "$env:PYTHONPATH=(Get-Location).Path",
        "& 'E:\\AI\\HSR Partner Harness\\.venv\\Scripts\\python.exe' run_a13.py",
    ])
    write_http_log(out / "http.log", "A13 全部交互走 WS 帧（角色卡导入导出经候选命令）")
    print("A13 finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
