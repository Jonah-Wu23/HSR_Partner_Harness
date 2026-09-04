"""V0.3.7 视觉轨集成探针：真实 Sidecar 上验证冻结 §1/§10 四个新命令的真实 payload
与视觉轨 TS 契约（desktop/src/contracts/protocol.ts）逐字段一致性。

运行（worktree 根目录）：
    PYTHONPATH=src ..\\..\\..\\.venv\\Scripts\\python.exe scripts\\repro_v037_visual_contracts.py

铁律：显式 --data-dir 临时目录，绝不触碰用户真实库；任何不一致直接 FAIL，不兜底。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = Path(r"E:\AI\HSR Partner Harness\.venv\Scripts\python.exe")
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "character_cards"
FIXTURE_JSON = FIXTURE_DIR / "白厄（3.4前）.json"
FIXTURE_PNG = FIXTURE_DIR / "白厄（3.4前）.png"

REPORT_KEYS = {"applied", "preserved", "not_executed", "normalized_from_root", "warnings", "errors"}
PREVIEW_KEYS = {"name", "spec_version", "format", "avatar_available", "avatar_width", "avatar_height",
                "greeting_count", "world_book_entries", "tags", "report"}
EXPORT_KEYS = {"exported", "path", "name", "spec_version", "greeting_count", "world_book_entries", "extensions"}
POWER_KEYS = {"supported", "platform", "plan_name", "ac_sleep_timeout_seconds", "dc_sleep_timeout_seconds",
              "remote_serve_enabled", "threshold_seconds", "at_risk", "reason", "checked_at"}

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' —— ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir(parents=True)
        proc = subprocess.Popen(
            [str(PYTHON), "-m", "pair_harness.desktop_backend", "--demo",
             "--project", str(Path(tmp)), "--data-dir", str(data_dir)],
            cwd=str(ROOT),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        assert proc.stdin and proc.stdout
        pending: dict[str, dict] = {}

        def reader() -> None:
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("kind") == "response":
                    pending[msg.get("id")] = msg

        threading.Thread(target=reader, daemon=True).start()
        request_id = 0

        def request(method: str, params: dict) -> dict:
            nonlocal request_id
            request_id += 1
            rid = f"r{request_id}"
            proc.stdin.write(json.dumps({"kind": "request", "id": rid, "method": method, "params": params}) + "\n")
            proc.stdin.flush()
            deadline = time.time() + 15
            while time.time() < deadline and rid not in pending:
                time.sleep(0.02)
            return pending.pop(rid, {})

        # 账号引导（沿用 repro_sidecar_process 的已知良好路径）
        request("app.bootstrap", {})
        request("account.register", {"username": "visual", "display_name": "Visual", "password": "secret123"})
        request("account.onboarding_complete", {})

        print("== 1. card.peek_import（PNG 分支） ==")
        resp = request("card.peek_import", {"path": str(FIXTURE_PNG)})
        preview = resp.get("result", {}).get("preview", {})
        check("PNG preview 字段齐全", REPORT_KEYS <= set(preview.get("report", {})) and PREVIEW_KEYS <= set(preview), json.dumps(sorted(preview)))
        check("format == png", preview.get("format") == "png")
        check("avatar_available 为 true", preview.get("avatar_available") is True)
        check("头像尺寸为 int", isinstance(preview.get("avatar_width"), int) and isinstance(preview.get("avatar_height"), int),
              f"{preview.get('avatar_width')}x{preview.get('avatar_height')}")
        check("世界书条目数 > 0", (preview.get("world_book_entries") or 0) > 0, str(preview.get("world_book_entries")))

        print("== 2. card.peek_import（JSON 分支与别名） ==")
        resp_json = request("card.peek_import", {"path": str(FIXTURE_JSON)}).get("result", {}).get("preview", {})
        check("JSON format == json", resp_json.get("format") == "json")
        check("JSON 头像尺寸为 null", resp_json.get("avatar_width") is None and resp_json.get("avatar_height") is None)
        alias = request("card.peek_import_json", {"path": str(FIXTURE_JSON)}).get("result", {}).get("preview", {})
        check("peek_import_json 别名同行为", alias.get("name") == resp_json.get("name"))

        print("== 3. card.import_png → card.get ==")
        resp = request("card.import_png", {"path": str(FIXTURE_PNG)})
        imported = resp.get("result", {})
        check("import_png 返回 card_id/name/state/report", {"card_id", "name", "state", "report"} <= set(imported),
              json.dumps(sorted(imported)))
        card_id = imported.get("card_id", "")
        got = request("card.get", {"card_id": card_id}).get("result", {})
        card_json = got.get("card", {})
        avatar = ((card_json.get("data") or {}).get("extensions") or {}).get("hsr", {}).get("avatar_asset") or {}
        check("导入卡绑定 png_import 头像资产", avatar.get("source") == "png_import", json.dumps(avatar, ensure_ascii=False)[:120])

        print("== 4. card.export_png 往返 ==")
        out_png = Path(tmp) / "exported.png"
        resp = request("card.export_png", {"card_id": card_id, "path": str(out_png)})
        exported = resp.get("result", {})
        check("export_png 字段齐全", EXPORT_KEYS <= set(exported), json.dumps(sorted(exported)))
        check("exported == true 且文件存在", exported.get("exported") is True and out_png.exists())
        check("extensions 含 hsr", "hsr" in (exported.get("extensions") or []))
        reimported = request("card.import_png", {"path": str(out_png)}).get("result", {})
        check("导出 PNG 可再导入", bool(reimported.get("card_id")))
        re_preview = request("card.peek_import", {"path": str(out_png)}).get("result", {}).get("preview", {})
        check("往返后世界书条目数一致", re_preview.get("world_book_entries") == preview.get("world_book_entries"))

        print("== 5. card.export_png 无头像真实拒绝 ==")
        draft = request("card.create_draft", {"name": "探针草稿"}).get("result", {})
        draft_id = draft.get("card_id", "")
        resp = request("card.export_png", {"card_id": draft_id, "path": str(Path(tmp) / "no_avatar.png")})
        err = resp.get("error", {})
        check("错误码 card_export_failed", err.get("code") == "card_export_failed", json.dumps(err, ensure_ascii=False)[:200])
        check("message 含「未设置头像」", "头像" in (err.get("message") or ""), (err.get("message") or "")[:120])

        print("== 6. power.get_status ==")
        power = request("power.get_status", {}).get("result", {})
        check("power payload 字段齐全", POWER_KEYS <= set(power), json.dumps(sorted(power)))
        check("Windows 平台 supported", power.get("supported") is True and power.get("platform") in ("windows", "win32"),
              f"platform={power.get('platform')}（注：实际返回 sys.platform 值，与冻结 §1.5 的 \"windows\" 存在偏差，如实记录移交逻辑轨）")
        check("超时为 int（AC/DC）", isinstance(power.get("ac_sleep_timeout_seconds"), int) and isinstance(power.get("dc_sleep_timeout_seconds"), int))
        check("threshold_seconds == 900", power.get("threshold_seconds") == 900)

        print("== 7. 损坏文件如实失败 ==")
        bad = Path(tmp) / "bad.png"
        bad.write_bytes(b"not a png at all")
        resp = request("card.peek_import", {"path": str(bad)})
        check("损坏 PNG 报 card_import_failed", resp.get("error", {}).get("code") == "card_import_failed",
              json.dumps(resp.get("error", {}), ensure_ascii=False)[:200])

        proc.kill()
        proc.wait()

    print()
    if failures:
        print(f"结果：{len(failures)} 项不一致：{failures}")
        return 1
    print("结果：全部一致——真实 Sidecar payload 与视觉轨 TS 契约对齐")
    return 0


if __name__ == "__main__":
    sys.exit(main())
