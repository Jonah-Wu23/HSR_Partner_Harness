# 账号数据目录定位，以及本地遗留 Codex 登录数据（auth.json、login.waiting）的
# 只读与清理。产品不再提供 Codex 登录，引擎工厂用 base_dir 与 account_id
# 定位账号私有的 Reasonix 配置目录。

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class CodexAuthService:
    def __init__(self, base_dir: Path, account_id: str) -> None:
        self.base_dir = Path(base_dir)
        self.account_id = account_id
        self.home = self.base_dir / "accounts" / account_id / "codex"
        self.auth_file = self.home / "auth.json"
        self._waiting_file = self.home / "login.waiting"

    def status(self) -> dict[str, object]:
        """遗留登录状态：logged_out / logged_in / auth_corrupt。

        auth.json 格式与 codex CLI 一致：{"tokens": {...}, "current": "..."}。
        解析失败时报告 auth_corrupt 并保留原文件供诊断。
        """
        if not self.auth_file.exists():
            return {"status": "logged_out", "account_label": None}
        try:
            tokens = json.loads(self.auth_file.read_text(encoding="utf-8"))
        except ValueError as exc:
            logger.warning("Codex auth.json 损坏（保留文件供诊断）：%s", exc)
            return {
                "status": "auth_corrupt",
                "account_label": None,
                "error": f"auth.json 损坏：{exc}",
            }
        if not isinstance(tokens, dict):
            logger.warning("Codex auth.json 内容不是对象（保留文件供诊断）")
            return {
                "status": "auth_corrupt",
                "account_label": None,
                "error": "auth.json 内容不是对象",
            }
        if not tokens:
            return {"status": "logged_out", "account_label": None}
        return self._logged_in_payload(tokens)

    def _logged_in_payload(self, tokens: dict) -> dict[str, object]:
        current = tokens.get("current")
        account_label = None
        if current:
            entry = (tokens.get("tokens") or {}).get(current) or {}
            account_label = entry.get("account_label") or entry.get("email") or current
        if not account_label and tokens.get("tokens"):
            account_label = next(iter(tokens["tokens"]))
        return {"status": "logged_in", "account_label": account_label}

    def logout(self) -> dict[str, object]:
        """删除本账号的遗留登录文件，会话记录不受影响。"""
        self.auth_file.unlink(missing_ok=True)
        self._waiting_file.unlink(missing_ok=True)
        return {"status": "logged_out"}
