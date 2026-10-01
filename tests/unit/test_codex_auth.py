import json
from pathlib import Path

from pair_harness.adapters.codex.auth import CodexAuthService


def make_service(tmp_path: Path) -> CodexAuthService:
    return CodexAuthService(tmp_path / "runtime", "acc-1")


def write_legacy_auth(service: CodexAuthService, api_key: str) -> None:
    service.home.mkdir(parents=True, exist_ok=True)
    service.auth_file.write_text(
        json.dumps({"tokens": {"openai": {"api_key": api_key}}, "current": "openai"}),
        encoding="utf-8",
    )


def test_initial_state_is_logged_out(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    assert service.status() == {"status": "logged_out", "account_label": None}


def test_logout_clears_credentials(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    write_legacy_auth(service, "sk-secret")
    assert service.status()["status"] == "logged_in"
    service.logout()
    assert service.status()["status"] == "logged_out"
    assert not service.auth_file.exists()


def test_corrupt_auth_reports_auth_corrupt_and_preserves_file(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.home.mkdir(parents=True, exist_ok=True)
    service.auth_file.write_text("{broken json", encoding="utf-8")
    status = service.status()
    assert status["status"] == "auth_corrupt"
    assert "损坏" in status["error"]
    # 损坏文件保留供诊断，不被删除或覆盖。
    assert service.auth_file.exists()
    assert service.auth_file.read_text(encoding="utf-8") == "{broken json"
