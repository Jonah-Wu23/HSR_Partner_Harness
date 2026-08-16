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
损坏的 auth.json 保持原位供诊断，状态返回 ``auth_corrupt``，不会静默
降级成 logged_out。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
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
        """当前认证状态：logged_out / waiting / logged_in / expired / auth_corrupt。

        waiting 只在“完整 token 可读 **且** 登录进程已进入明确终态”后清除；
        auth.json 解析失败时报告 ``auth_corrupt`` 并保留原文件。
        """
        tokens, corrupt_error = self._load_auth_data()
        if corrupt_error is not None:
            return {
                "status": "auth_corrupt",
                "account_label": None,
                "error": corrupt_error,
            }
        if self._waiting_file.exists():
            if self._tokens_complete(tokens) and self._login_process_terminal():
                self._waiting_file.unlink(missing_ok=True)
                return self._logged_in_payload(tokens)
            return {"status": "waiting", "account_label": None}
        if not tokens:
            return {"status": "logged_out", "account_label": None}
        return self._logged_in_payload(tokens)

    @staticmethod
    def _tokens_complete(tokens: dict) -> bool:
        """auth.json 是否包含可用的完整 token（Codex CLI 形状）。"""
        token_map = tokens.get("tokens")
        current = tokens.get("current")
        if not isinstance(token_map, dict) or not token_map:
            return False
        if not current or current not in token_map:
            return False
        entry = token_map.get(current) or {}
        # 兼容 API Key 登录（openai token）与 OAuth 完整 entry。
        if not isinstance(entry, dict):
            return False
        return bool(entry.get("api_key") or entry.get("access_token") or entry.get("account_label") or entry.get("email"))

    def _logged_in_payload(self, tokens: dict) -> dict[str, object]:
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
        """启动 Codex 官方浏览器 OAuth；未传可执行文件时只进入等待态。

        重复调用会先终止并等待旧登录进程退出，再创建新进程，避免多个
        OAuth 浏览器进程同时写同一份 auth.json。
        """
        self._terminate_login_process()
        self.home.mkdir(parents=True, exist_ok=True)
        self._waiting_file.touch()
        if executable:
            resolved = shutil.which(executable) or executable
            env = {**os.environ, **self.env_overrides}
            creationflags = 0x08000000 if os.name == "nt" else 0
            if resolved.lower().endswith((".cmd", ".bat")):
                # Windows 批处理 shim 必须经 cmd.exe 启动，且路径含空格时
                # 需要用 list2cmdline 把整条命令行正确加引号，不能直接把
                # 未引用的路径拼到 "/c" 后面。
                command_line = subprocess.list2cmdline([resolved, "login"])
                command = [os.environ.get("COMSPEC", "cmd.exe"), "/c", command_line]
            else:
                command = [resolved, "login"]
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
                self._waiting_file.unlink(missing_ok=True)
                raise RuntimeError(f"启动 Codex OAuth 浏览器流程失败：{exc}") from exc
        return {"status": "waiting", "note": "请在浏览器中完成 Codex 登录"}

    def api_login(self, api_key: str) -> dict[str, object]:
        """OpenAI API Key 登录：写 auth.json（保留现有 chatgpt token）。"""
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("API Key 不能为空")
        self.home.mkdir(parents=True, exist_ok=True)
        tokens, _ = self._load_auth_data()
        tokens.setdefault("tokens", {})
        tokens["tokens"]["openai"] = {"api_key": key}
        tokens["current"] = "openai"
        self._write_auth_file(tokens)
        self._waiting_file.unlink(missing_ok=True)
        logger.info("Codex API 登录完成（账号 %s）", self.account_id)
        return {"status": "logged_in", "account_label": "OpenAI API Key"}

    def _write_auth_file(self, tokens: dict) -> None:
        """同目录临时文件写入后原子替换，避免 auth.json 半写。"""
        self.home.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.home), prefix=".auth.json.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(tokens, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self._auth_file)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _login_process_terminal(self) -> bool:
        return self._login_process is None or self._login_process.poll() is not None

    def _terminate_login_process(self, wait_timeout: float = 5.0) -> None:
        """终止旧登录进程并等待其退出；普通 terminate 无效时强制结束。"""
        process = self._login_process
        self._login_process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=wait_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=wait_timeout)
                except subprocess.TimeoutExpired:
                    logger.error("Codex OAuth 登录进程无法终止 (pid=%s)", process.pid)
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

    def _load_auth_data(self) -> tuple[dict, str | None]:
        """读取 auth.json；解析失败时返回空 dict 和保留的错误说明。"""
        if not self._auth_file.exists():
            return {}, None
        try:
            data = json.loads(self._auth_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logger.warning("Codex auth.json 损坏（保留文件供诊断）：%s", exc)
            return {}, f"auth.json 损坏：{exc}"
        if not isinstance(data, dict):
            logger.warning("Codex auth.json 内容不是对象（保留文件供诊断）")
            return {}, "auth.json 内容不是对象"
        return data, None

    def _read_tokens(self) -> dict:
        tokens, _ = self._load_auth_data()
        return tokens
