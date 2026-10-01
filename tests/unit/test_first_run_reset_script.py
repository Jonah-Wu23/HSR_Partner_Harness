import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "desktop"
    / "scripts"
    / "tauri-with-first-run-reset.ps1"
)
APP_IDENTIFIER = "com.jonahwu.hsr-partner-harness"
LOG_NAME = "sidecar.stderr.log"


def _run_powershell(
    *args: str, env: dict[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.fail("Windows PowerShell 5.1 (powershell.exe) is unavailable on this machine.")
    return subprocess.run(
        [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        # Windows PowerShell 5.1 的管道输出使用系统 ANSI 代码页
        encoding="mbcs" if sys.platform == "win32" else "utf-8",
        errors="replace",
        timeout=120,
    )


class _Sandbox:
    """脚本副本放在临时打包目录里，LOCALAPPDATA 与 APPDATA 指向临时目录。

    node_modules/.bin/tauri.cmd 只记录调用并按给定退出码退出，不执行真实打包。
    """

    def __init__(self, root: Path, *, build_exit_code: int = 0) -> None:
        self.script = root / "scripts" / SCRIPT_PATH.name
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT_PATH, self.script)
        self.local_app_data = root / "localappdata"
        self.app_data = root / "appdata"
        self.log_root = self.app_data / APP_IDENTIFIER
        web_view = self.local_app_data / APP_IDENTIFIER / "EBWebView" / "Default"
        self.state_dirs = (
            self.local_app_data / "PairHarness",
            web_view / "Local Storage",
            web_view / "Session Storage",
        )
        self.logs = (self.log_root / LOG_NAME, self.log_root / f"{LOG_NAME}.1")
        self.unrelated = self.local_app_data / "OtherApp" / "data.txt"
        self.build_marker = root / "build-called.txt"
        tauri = root / "node_modules" / ".bin" / "tauri.cmd"
        tauri.parent.mkdir(parents=True)
        # 标记文件按 tauri.cmd 自身位置定位，临时目录含非 ASCII 字符时批处理内容仍是 ASCII
        tauri.write_text(
            '@echo off\necho called %*>>"%~dp0..\\..\\build-called.txt"\n'
            f"exit /b {build_exit_code}\n",
            encoding="ascii",
            newline="\r\n",
        )

    def seed_first_run_state(self) -> None:
        for directory in self.state_dirs:
            directory.mkdir(parents=True)
            (directory / "000003.log").write_text("previous build", encoding="utf-8")
        self.log_root.mkdir(parents=True)
        for log in self.logs:
            log.write_text("previous build traceback\n", encoding="utf-8")
        self.unrelated.parent.mkdir(parents=True)
        self.unrelated.write_text("keep", encoding="utf-8")

    def remaining_state(self) -> list[Path]:
        return [path for path in (*self.state_dirs, *self.logs) if path.exists()]

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "LOCALAPPDATA": str(self.local_app_data),
            "APPDATA": str(self.app_data),
        }
        return _run_powershell(
            "-File", str(self.script), *args, env=env, cwd=self.script.parent
        )

    def build_was_called(self) -> bool:
        return self.build_marker.exists()


def _deny_delete(path: Path) -> None:
    # Remove-Item -Force 能删除只读文件，只有 ACL 拒绝删除才能让清理真实失败
    result = _run_powershell(
        "-Command",
        "$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n"
        f"& icacls '{path}' /deny ('*' + $sid + ':(OI)(CI)(DE,DC)')\n"
        "exit $LASTEXITCODE\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _allow_delete(path: Path) -> None:
    _run_powershell(
        "-Command",
        "$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n"
        f"& icacls '{path}' /remove:d ('*' + $sid) | Out-Null\n"
        f"& icacls '{path}' /grant ('*' + $sid + ':(OI)(CI)F') | Out-Null\n",
    )


def test_reset_only_clears_first_run_state(tmp_path: Path) -> None:
    sandbox = _Sandbox(tmp_path)
    sandbox.seed_first_run_state()

    result = sandbox.run("-ResetOnly")

    assert result.returncode == 0, result.stdout + result.stderr
    assert sandbox.remaining_state() == []
    assert sandbox.unrelated.exists()
    assert sandbox.build_was_called() is False


def test_successful_build_clears_first_run_state(tmp_path: Path) -> None:
    sandbox = _Sandbox(tmp_path)
    sandbox.seed_first_run_state()

    result = sandbox.run("build", "--no-bundle")

    assert result.returncode == 0, result.stdout + result.stderr
    assert sandbox.build_was_called() is True
    assert sandbox.remaining_state() == []


def test_failed_build_exits_non_zero_and_keeps_state(tmp_path: Path) -> None:
    sandbox = _Sandbox(tmp_path, build_exit_code=7)
    sandbox.seed_first_run_state()

    result = sandbox.run("build", "--no-bundle")

    assert result.returncode != 0
    assert sandbox.build_was_called() is True
    assert len(sandbox.remaining_state()) == len(sandbox.state_dirs) + len(sandbox.logs)


@pytest.mark.parametrize("args", [("-ResetOnly",), ("build", "--no-bundle")])
def test_reset_failure_exits_non_zero_with_cause(tmp_path: Path, args: tuple[str, ...]) -> None:
    sandbox = _Sandbox(tmp_path)
    sandbox.seed_first_run_state()
    _deny_delete(sandbox.log_root)
    try:
        # 临时目录所在的文件系统不支持 ACL（例如 exFAT）时在这里失败
        with pytest.raises(PermissionError):
            sandbox.logs[0].unlink()
        result = sandbox.run(*args)
    finally:
        _allow_delete(sandbox.log_root)

    assert result.returncode != 0
    assert result.stderr.strip()
    assert all(log.exists() for log in sandbox.logs)
