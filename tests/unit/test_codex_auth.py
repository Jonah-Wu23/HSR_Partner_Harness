"""V0.2 M3：Codex 登录状态服务（方案 §M3-4，账号隔离）。"""

from pathlib import Path

import pytest

from pair_harness.adapters.codex.auth import CodexAuthService


def make_service(tmp_path: Path, account_id: str = "acc-1") -> CodexAuthService:
    return CodexAuthService(tmp_path / "runtime", account_id)


def test_initial_state_is_logged_out(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    assert service.status() == {"status": "logged_out", "account_label": None}


def test_api_login_writes_auth_json_and_status(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    result = service.api_login("sk-test-123")
    assert result["status"] == "logged_in"
    assert service.status()["status"] == "logged_in"
    assert service.auth_file.exists()
    data = service.auth_file.read_text(encoding="utf-8")
    assert "sk-test-123" in data
    # 环境注入指向账号隔离目录
    assert service.env_overrides["CODEX_HOME"] == str(service.home)
    assert service.home.is_dir()


def test_start_login_waiting_then_api_login_clears_waiting(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    started = service.start_login()
    assert started["status"] == "waiting"
    assert service.status()["status"] == "waiting"
    service.api_login("sk-abc")
    assert service.status()["status"] == "logged_in"
    assert not service.home.joinpath("login.waiting").exists()


def test_cancel_login_returns_to_logged_out(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.start_login()
    service.cancel_login()
    assert service.status()["status"] == "logged_out"


def test_logout_clears_credentials(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.api_login("sk-secret")
    assert service.status()["status"] == "logged_in"
    service.logout()
    assert service.status()["status"] == "logged_out"
    assert not service.auth_file.exists()


def test_accounts_do_not_share_codex_home(tmp_path: Path) -> None:
    alice = make_service(tmp_path, "alice")
    bob = make_service(tmp_path, "bob")
    alice.api_login("sk-alice")
    assert alice.status()["status"] == "logged_in"
    assert bob.status()["status"] == "logged_out"
    assert alice.home != bob.home


def test_expired_token_handled_by_missing_or_corrupt_auth(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.home.mkdir(parents=True, exist_ok=True)
    service.auth_file.write_text("{broken json", encoding="utf-8")
    assert service.status()["status"] == "logged_out"
