"""Codex 登录状态服务——V0.2 M3（方案 §M3-4）。

Codex app-server 的认证数据是 ``CODEX_HOME/auth.json``。每个本地账号使用
独立的 Codex 数据目录（``base_dir/accounts/{account_id}/codex``），使
OAuth Token、API Key 和 session 不会串账号（方案原文）。

认证模式（Codex 官方接口，不自实现 OAuth 协议）：
- ChatGPT 浏览器 OAuth：``start_login`` 置 waiting 态，提示用户完成
  官方登录流程；本服务轮询 auth.json 直到写入（logged_in）；
- OpenAI API Key 登录：``api_login`` 直接写 auth.json 的 openai token；
- ``logout`` 清空本账号 auth.json；token 过期（auth.json 缺失/空）→
  expired 态由上层按账号隔离刷新。

auth.json 格式与 codex CLI 一致：{"tokens": {...}, "current": "..."}。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class CodexAuthService:
    """每个本地账号独立的 Codex 认证状态（状态机）。"""

    def __init__(self, base_dir: Path, account_id: str) -> None:
        self.base_dir = Path(base_dir)
        self.account_id = account_id
        self.home = self.base_dir / "accounts" / account_id / "codex"
        self._auth_file = self.home / "auth.json"
        self._waiting_file = self.home / "login.waiting"
        self._login_process: subprocess.Popen[bytes] | None = None

    # ---- 路径与状态 ----

    @property
    def auth_file(self) -> Path:
        return self._auth_file

    @property
    def env_overrides(self) -> dict[str, str]:
        """注入 Codex 进程的环境变量（账号隔离数据目录）。"""
        # Codex app-server 在启动时会校验 CODEX_HOME 已存在。首次使用
        # 账号时这里通常还没有 auth.json，但运行目录必须先创建。
        self.home.mkdir(parents=True, exist_ok=True)
        return {"CODEX_HOME": str(self.home)}

    def status(self) -> dict[str, object]:
        """当前认证状态：logged_out / waiting / logged_in / expired。"""
        tokens = self._read_tokens()
        if self._waiting_file.exists() and not tokens:
            return {"status": "waiting", "account_label": None}
        if not tokens:
            return {"status": "logged_out", "account_label": None}
        self._waiting_file.unlink(missing_ok=True)
        current = tokens.get("current")
        account_label = None
        if current:
            entry = (tokens.get("tokens") or {}).get(current) or {}
            account_label = entry.get("account_label") or entry.get("email") or current
        if not account_label and tokens.get("tokens"):
            # 只有单个 token 时以键名作为账号标识
            account_label = next(iter(tokens["tokens"]))
        return {"status": "logged_in", "account_label": account_label}

    # ---- 登录流程 ----

    def start_login(self, executable: str | None = None) -> dict[str, object]:
        """启动 Codex 官方浏览器 OAuth；未传可执行文件时只进入等待态。"""
        self.home.mkdir(parents=True, exist_ok=True)
        self._waiting_file.touch()
        if executable:
            resolved = shutil.which(executable) or executable
            command = [resolved, "login"]
            if resolved.lower().endswith((".cmd", ".bat")):
                command = [os.environ.get("COMSPEC", "cmd.exe"), "/c", resolved, "login"]
            env = {**os.environ, **self.env_overrides}
            creationflags = 0x08000000 if os.name == "nt" else 0
            try:
                self._login_process = subprocess.Popen(
                    command,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
            except OSError as exc:
                logger.warning("启动 Codex OAuth 浏览器流程失败：%s", exc)
        return {"status": "waiting", "note": "请在浏览器中完成 Codex 登录"}

    def api_login(self, api_key: str) -> dict[str, object]:
        """OpenAI API Key 登录：写 auth.json（保留现有 chatgpt token）。"""
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("API Key 不能为空")
        self.home.mkdir(parents=True, exist_ok=True)
        tokens = self._read_tokens()
        tokens.setdefault("tokens", {})
        tokens["tokens"]["openai"] = {"api_key": key}
        tokens["current"] = "openai"
        self._auth_file.write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._waiting_file.unlink(missing_ok=True)
        logger.info("Codex API 登录完成（账号 %s）", self.account_id)
        return {"status": "logged_in", "account_label": "OpenAI API Key"}

    def _terminate_login_process(self) -> None:
        if self._login_process is not None and self._login_process.poll() is None:
            self._login_process.terminate()
        self._login_process = None
        self._waiting_file.unlink(missing_ok=True)

    def cancel_login(self) -> None:
        """取消 waiting 态（浏览器流程放弃后回到 logged_out）。"""
        self._terminate_login_process()

    def logout(self) -> dict[str, object]:
        """清空本账号认证数据（不删除会话记录）。"""
        self._terminate_login_process()
        self._auth_file.unlink(missing_ok=True)
        return {"status": "logged_out"}

    # ---- 内部 ----

    def _read_tokens(self) -> dict:
        if not self._auth_file.exists():
            return {}
        try:
            data = json.loads(self._auth_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logger.warning("Codex auth.json 损坏：%s", exc)
            return {}
        return data if isinstance(data, dict) else {}
