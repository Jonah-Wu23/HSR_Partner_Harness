"""V0.2 M3：Codex 登录状态服务（方案 §M3-4，账号隔离）。"""

import json
import os
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


def test_start_login_surfaces_process_start_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(tmp_path)

    def fail_start(*_args, **_kwargs):
        raise OSError("codex not found")

    monkeypatch.setattr("pair_harness.adapters.codex.auth.subprocess.Popen", fail_start)
    with pytest.raises(RuntimeError, match="启动 Codex OAuth 浏览器流程失败：codex not found"):
        service.start_login("codex.exe")
    assert service.status()["status"] == "logged_out"


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


def test_corrupt_auth_reports_auth_corrupt_and_preserves_file(tmp_path: Path) -> None:
    """M3.4：auth.json 解析失败必须报告 auth_corrupt，不能静默变 logged_out。"""
    service = make_service(tmp_path)
    service.home.mkdir(parents=True, exist_ok=True)
    service.auth_file.write_text("{broken json", encoding="utf-8")
    status = service.status()
    assert status["status"] == "auth_corrupt"
    assert "损坏" in status["error"]
    # 损坏文件保留供诊断，不被删除或覆盖。
    assert service.auth_file.exists()
    assert service.auth_file.read_text(encoding="utf-8") == "{broken json"


class _RecordingPopen:
    def __init__(self, command, **kwargs) -> None:
        del kwargs
        self.command = command
        self.pid = 12345
        self.poll_result: int | None = None
        self.terminated = False
        self.killed = False
        self.waited = 0

    def poll(self) -> int | None:
        return self.poll_result

    def terminate(self) -> None:
        self.terminated = True
        self.poll_result = 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.waited += 1
        return self.poll_result or 0

    def kill(self) -> None:
        self.killed = True
        self.poll_result = 0


def test_repeated_start_login_terminates_and_waits_old_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3.4：重复 start_login 必须先终止并等待旧登录进程，再创建新进程。"""
    service = make_service(tmp_path)
    processes: list[_RecordingPopen] = []

    def record_popen(command, **kwargs) -> _RecordingPopen:
        process = _RecordingPopen(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("pair_harness.adapters.codex.auth.subprocess.Popen", record_popen)
    service.start_login("codex.exe")
    service.start_login("codex.exe")

    assert len(processes) == 2
    assert processes[0].terminated is True
    assert processes[0].waited >= 1
    assert processes[1].terminated is False


def test_start_login_quotes_cmd_shim_path_with_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3.4：.cmd/.bat 登录命令对含空格路径使用 Windows 正确引用。"""
    service = make_service(tmp_path)
    captured: list[list[str]] = []

    def record_popen(command, **kwargs):
        del kwargs
        captured.append(command)
        return _RecordingPopen(command)

    monkeypatch.setattr("pair_harness.adapters.codex.auth.subprocess.Popen", record_popen)
    service.start_login(r"C:\Program Files\Codex\codex.cmd")

    assert len(captured) == 1
    command = captured[0]
    assert command[0] == os.environ.get("COMSPEC", "cmd.exe")
    assert command[1] == "/c"
    assert '"C:\\Program Files\\Codex\\codex.cmd"' in command[2]
    assert command[2].endswith("login")


def test_waiting_is_not_cleared_until_token_complete_and_process_terminal(
    tmp_path: Path,
) -> None:
    """M3.4：waiting 只在完整 token 可读且登录进程终态明确后清除。"""
    service = make_service(tmp_path)
    service.home.mkdir(parents=True, exist_ok=True)
    service._waiting_file.touch()
    service.auth_file.write_text(
        json.dumps(
            {
                "tokens": {"openai": {"api_key": "sk-test-123"}},
                "current": "openai",
            }
        ),
        encoding="utf-8",
    )

    class Running:
        def poll(self) -> None:
            return None

    service._login_process = Running()  # type: ignore[assignment]
    assert service.status()["status"] == "waiting"
    assert service._waiting_file.exists()

    class Exited:
        def poll(self) -> int:
            return 0

    service._login_process = Exited()  # type: ignore[assignment]
    assert service.status()["status"] == "logged_in"
    assert not service._waiting_file.exists()


def test_api_login_writes_atomically_without_temp_leftovers(tmp_path: Path) -> None:
    """M3.4：auth.json 经同目录临时文件原子替换，不残留半写临时文件。"""
    service = make_service(tmp_path)
    service.api_login("sk-atomic-123")
    assert service.auth_file.exists()
    assert not list(service.home.glob(".auth.json.*.tmp"))
