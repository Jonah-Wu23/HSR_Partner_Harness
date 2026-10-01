import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DESKTOP_ROOT = Path(__file__).resolve().parents[2] / "desktop"
SCRIPT_PATH = DESKTOP_ROOT / "scripts" / "build-android.ps1"
TAURI_CONF_PATH = DESKTOP_ROOT / "src-tauri" / "tauri.conf.json"


def _write_cmd(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "@echo off\n" + "\n".join(lines) + "\nexit /b 0\n", encoding="ascii", newline="\r\n"
    )


def _properties(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="ascii").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


class _AndroidBuildSandbox:
    """desktop 目录布局放在临时目录里，tauri.conf.json 的 version 换成给定值。

    工具链只需通过脚本的存在性检查，用空文件占位；npm、cargo、gradlew 换成只记录
    调用的批处理，gradlew 额外保存它运行时看到的 app/tauri.properties。
    """

    def __init__(self, root: Path, version: str | None) -> None:
        self.root = root
        desktop = root / "desktop"
        self.script = desktop / "scripts" / SCRIPT_PATH.name
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT_PATH, self.script)

        config = json.loads(TAURI_CONF_PATH.read_text(encoding="utf-8"))
        if version is None:
            config.pop("version", None)
        else:
            config["version"] = version
        tauri_root = desktop / "src-tauri"
        tauri_root.mkdir()
        (tauri_root / "tauri.conf.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        dist = desktop / "mobile" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")

        self.java_home = root / "java"
        self.ndk_home = root / "ndk"
        self.android_home = root / "sdk"
        ndk_bin = self.ndk_home / "toolchains" / "llvm" / "prebuilt" / "windows-x86_64" / "bin"
        for placeholder in (
            self.java_home / "bin" / "java.exe",
            ndk_bin / "aarch64-linux-android24-clang.cmd",
            ndk_bin / "aarch64-linux-android24-clang++.cmd",
            ndk_bin / "llvm-ar.exe",
            self.android_home / "platforms" / "android-36" / "android.jar",
        ):
            placeholder.parent.mkdir(parents=True, exist_ok=True)
            placeholder.write_bytes(b"")

        # 批处理按自身位置定位输出文件，临时目录含非 ASCII 字符时内容仍是 ASCII
        self.bin_dir = root / "bin"
        _write_cmd(self.bin_dir / "npm.cmd", ['>>"%~dp0..\\calls.txt" echo npm'])
        _write_cmd(
            self.bin_dir / "cargo.cmd",
            [
                '>>"%~dp0..\\calls.txt" echo cargo',
                'set "OUT=%~dp0..\\desktop\\src-tauri\\target\\aarch64-linux-android\\debug"',
                'md "%OUT%" 2>nul',
                '>"%OUT%\\libhsr_partner_harness_lib.so" echo stub-library',
            ],
        )
        _write_cmd(
            tauri_root / "gen" / "android" / "gradlew.bat",
            [
                '>>"%~dp0..\\..\\..\\..\\calls.txt" echo gradlew',
                'if exist "%~dp0app\\tauri.properties" copy /y "%~dp0app\\tauri.properties" '
                '"%~dp0..\\..\\..\\..\\properties-at-gradle-time.txt" >nul',
            ],
        )
        self.properties_at_gradle_time = root / "properties-at-gradle-time.txt"

    def run(self) -> subprocess.CompletedProcess[str]:
        executable = shutil.which("powershell.exe")
        if executable is None:
            pytest.fail("Windows PowerShell 5.1 (powershell.exe) is unavailable on this machine.")
        env = {
            **os.environ,
            "PATH": str(self.bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "JAVA_HOME": str(self.java_home),
            "NDK_HOME": str(self.ndk_home),
            "ANDROID_HOME": str(self.android_home),
        }
        # 让脚本使用自己的 WRY 缺省值，不受宿主环境影响
        for name in ("WRY_ANDROID_PACKAGE", "WRY_ANDROID_LIBRARY", "WRY_ANDROID_KOTLIN_FILES_OUT_DIR"):
            env.pop(name, None)
        return subprocess.run(
            [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.script)],
            cwd=self.script.parent.parent,
            env=env,
            capture_output=True,
            # Windows PowerShell 5.1 的管道输出使用系统 ANSI 代码页
            encoding="mbcs" if sys.platform == "win32" else "utf-8",
            errors="replace",
            timeout=120,
        )

    def recorded_calls(self) -> list[str]:
        calls = self.root / "calls.txt"
        return calls.read_text(encoding="ascii").split() if calls.exists() else []


# 与 tauri CLI 相同的派生式 major * 1000000 + minor * 1000 + patch，预发布后缀不参与
@pytest.mark.parametrize(
    ("version", "version_code"),
    [("1.2.3", 1002003), ("0.3.2-patch1", 3002)],
)
def test_version_properties_are_written_before_gradle(
    tmp_path: Path, version: str, version_code: int
) -> None:
    sandbox = _AndroidBuildSandbox(tmp_path, version)

    result = sandbox.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert sandbox.recorded_calls() == ["npm", "cargo", "gradlew"]
    assert _properties(sandbox.properties_at_gradle_time) == {
        "tauri.android.versionName": version,
        "tauri.android.versionCode": str(version_code),
    }


@pytest.mark.parametrize("version", [None, "0.3", "not-a-version", "0.0.0", "2101.0.0"])
def test_unusable_version_fails_before_packaging(tmp_path: Path, version: str | None) -> None:
    sandbox = _AndroidBuildSandbox(tmp_path, version)

    result = sandbox.run()

    assert result.returncode != 0
    assert "gradlew" not in sandbox.recorded_calls()
    assert "version" in result.stderr.lower(), result.stderr
