"""PWA 静态目录构建期校验（D7 / T10）自动化测试。

验证规则（决策稿 D7 / 实施计划 T10）：
1. PWA 静态目录仅允许前端构建产物（html/js/css/字体/图片/manifest/service worker）。
2. 严禁混入任何用户数据（accounts/user_data/history/session/pairing_state 等）。
3. 严禁混入凭据与私钥（.env/key/pem/token/password 等）。
4. 严禁混入源代码或临时文件（ts/tsx/py/rs/db/sqlite/log/tmp 等）。
5. 脚本自身语法合规、LF 换行、纯 ASCII 或带 BOM。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_SCRIPT = REPO_ROOT / "desktop" / "scripts" / "validate-pwa-dist.ps1"
BUILD_SIDECAR_SCRIPT = REPO_ROOT / "desktop" / "scripts" / "build-sidecar.ps1"
MOBILE_DIST = REPO_ROOT / "desktop" / "mobile" / "dist"


def _run_ps1(script_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        *args,
    ]
    # PowerShell 5.1 管道输出跟随系统 ANSI 代码页（中文 Windows 为 GBK），
    # 按系统 ANSI 解码，避免 PYTHONUTF8=1 环境下 UTF-8 解码崩溃。
    return subprocess.run(
        cmd,
        capture_output=True,
        text=False,
        encoding="mbcs" if sys.platform == "win32" else "utf-8",
        errors="replace",
        cwd=REPO_ROOT,
    )


def test_validator_script_exists_and_format_clean() -> None:
    """校验脚本存在、无 CR 行尾且符合编码约定。"""
    assert VALIDATE_SCRIPT.is_file(), f"未找到校验脚本：{VALIDATE_SCRIPT}"
    raw = VALIDATE_SCRIPT.read_bytes()
    assert b"\r" not in raw, "validate-pwa-dist.ps1 包含 CR 行尾，必须按 LF 保存"
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    non_ascii = [idx for idx, byte in enumerate(raw) if byte > 0x7F]
    assert has_bom or non_ascii == [], (
        f"validate-pwa-dist.ps1 含非 ASCII 字节且无 BOM：偏移 {non_ascii[:8]}"
    )


def test_validator_script_powershell_parse() -> None:
    """PowerShell AST 解析检查，确保脚本在 5.1/Core 下无语法错误。"""
    script = (
        "$tokens = $null; $errors = $null;\n"
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{VALIDATE_SCRIPT}', [ref]$tokens, [ref]$errors);\n"
        "Write-Output ('errors=' + @($errors).Count);\n"
        "foreach ($e in @($errors)) { Write-Output ('ERR ' + $e.Message) }\n"
    )
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    lines = res.stdout.strip().splitlines()
    assert lines and lines[0].startswith("errors="), res.stdout
    error_count = int(lines[0].split("=", 1)[1])
    assert error_count == 0, f"validate-pwa-dist.ps1 解析报错：\n{res.stdout}"


def test_build_sidecar_wires_pwa_validation() -> None:
    """build-sidecar.ps1 必须在复制前后调用 validate-pwa-dist.ps1 强制执行 D7 门禁。"""
    text = BUILD_SIDECAR_SCRIPT.read_text(encoding="utf-8")
    assert "validate-pwa-dist.ps1" in text, (
        "build-sidecar.ps1 未接入 validate-pwa-dist.ps1 校验逻辑"
    )
    assert "-DistPath $mobileDist" in text
    assert "-DistPath $mobileResourceRoot" in text


def test_real_mobile_dist_passes_validation() -> None:
    """仓库现有的 desktop/mobile/dist 目录必须通过校验。"""
    if not MOBILE_DIST.is_dir():
        pytest.skip(f"未找到 {MOBILE_DIST}，可能尚未构建 mobile")
    res = _run_ps1(VALIDATE_SCRIPT, "-DistPath", str(MOBILE_DIST))
    assert res.returncode == 0, f"真实 mobile/dist 校验失败：{res.stderr}\n{res.stdout}"
    assert "PWA static directory validation passed (D7)" in res.stdout


def test_clean_fixture_passes(tmp_path: Path) -> None:
    """标准构建产物（html/js/css/map/svg/webmanifest）通过校验。"""
    (tmp_path / "index.html").write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc12345.js").write_text("console.log('pwa');", encoding="utf-8")
    (assets / "index-abc12345.js.map").write_text("{}", encoding="utf-8")
    (assets / "index-def67890.css").write_text("body { margin: 0; }", encoding="utf-8")
    (tmp_path / "icon.svg").write_text("<svg></svg>", encoding="utf-8")
    (tmp_path / "manifest.webmanifest").write_text('{"name": "App"}', encoding="utf-8")

    res = _run_ps1(VALIDATE_SCRIPT, "-DistPath", str(tmp_path))
    assert res.returncode == 0, f"标准产物被误判为失败：{res.stderr}\n{res.stdout}"
    assert "PWA static directory validation passed (D7)" in res.stdout


def test_reject_missing_index_html(tmp_path: Path) -> None:
    """缺少 index.html 必须非零退出。"""
    (tmp_path / "app.js").write_text("console.log(1);", encoding="utf-8")
    res = _run_ps1(VALIDATE_SCRIPT, "-DistPath", str(tmp_path))
    assert res.returncode != 0
    assert "missing required index.html" in (res.stderr + res.stdout)


@pytest.mark.parametrize(
    "leaked_filename",
    [
        "accounts.json",
        "account.db",
        "accounts_store.sqlite",
        "user_data.json",
        "userdata.txt",
        "session.json",
        "history.json",
        "pairing_state.json",
        ".env",
        ".env.local",
        "id_rsa",
        "server.key",
        "cert.pem",
        "auth_token.txt",
        "credentials.json",
        "password.txt",
        "device_token.json",
    ],
)
def test_reject_user_data_and_credentials(tmp_path: Path, leaked_filename: str) -> None:
    """混入任何用户数据、账号信息、临时文件或凭证时必须非零退出（D7）。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / leaked_filename).write_text("secret_leak_payload", encoding="utf-8")

    res = _run_ps1(VALIDATE_SCRIPT, "-DistPath", str(tmp_path))
    assert res.returncode != 0, (
        f"混入敏感文件 {leaked_filename} 但校验未拦截（返回码 {res.returncode}）：\n{res.stdout}"
    )


@pytest.mark.parametrize(
    "forbidden_extension_file",
    [
        "source.ts",
        "component.tsx",
        "server.py",
        "lib.rs",
        "database.db",
        "storage.sqlite",
        "debug.log",
        "temp.tmp",
        "backup.bak",
        "dump.tar",
    ],
)
def test_reject_unauthorized_file_extensions(tmp_path: Path, forbidden_extension_file: str) -> None:
    """非允许的构建产物扩展名一律拦截（D7 白名单约束）。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / forbidden_extension_file).write_text("content", encoding="utf-8")

    res = _run_ps1(VALIDATE_SCRIPT, "-DistPath", str(tmp_path))
    assert res.returncode != 0, (
        f"混入非法文件扩展 {forbidden_extension_file} 但校验未拦截（返回码 {res.returncode}）：\n{res.stdout}"
    )


def test_reject_sensitive_content_in_json(tmp_path: Path) -> None:
    """即使文件名看似合法，若包含敏感字段（如 password_hash / api_key）也必须拦截。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "config.json").write_text(
        '{"name": "test", "password_hash": "sha256$deadbeef"}',
        encoding="utf-8",
    )

    res = _run_ps1(VALIDATE_SCRIPT, "-DistPath", str(tmp_path))
    assert res.returncode != 0
    assert "password_hash" in (res.stderr + res.stdout)


def test_reject_sensitive_content_in_js(tmp_path: Path) -> None:
    """打包主体是 minified JS：内嵌敏感关键词（如 api_key）必须被内容扫描拦截。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc12345.js").write_text(
        "const cfg={api_key:'sk-leak'};export default cfg;",
        encoding="utf-8",
    )

    res = _run_ps1(VALIDATE_SCRIPT, "-DistPath", str(tmp_path))
    assert res.returncode != 0, "JS 内嵌 api_key 未被内容扫描拦截"
    assert "api_key" in (res.stderr + res.stdout)


def test_forbidden_extension_reported_with_explicit_reason(tmp_path: Path) -> None:
    """forbidden 扩展必须报 Forbidden file extension 而非笼统的白名单拒绝。"""
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "server.py").write_text("print('hi')", encoding="utf-8")

    res = _run_ps1(VALIDATE_SCRIPT, "-DistPath", str(tmp_path))
    output = res.stderr + res.stdout
    assert res.returncode != 0
    assert "Forbidden file extension 'py'" in output
