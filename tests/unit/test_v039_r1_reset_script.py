r"""V039-R1-001 / V039-S4-010：首启清理脚本的编码与失败传播测试（离线）。

复测批次的现场结论（`evidence/retest-20260910/V039-S4-010/`）：

1. 脚本是 UTF-8 无 BOM + 中文注释。Windows PowerShell 5.1 对无 BOM 脚本按系统
   ANSI 代码页（本机 CP936）解码时吞掉 2 个换行，把中文注释与下一行的
   `$logRoot = ...` 合并成一行注释，`$logRoot` 恒为 null，日志删除代码从未执行；
   受控实验证明「加 BOM」与「注释改 ASCII」都能修复。
2. 该失败在打包流程里静默：清理抛错后 `npm run tauri -- build --no-bundle`
   仍以 exit 0 结束。

因此这里断言两件事，缺一不算通过：

- **编码稳健性**：脚本必须能在 PowerShell 5.1 的真实解码路径下保持完整——
  文件纯 ASCII、无 BOM、LF 行尾，且按 CP936 解码后的行数与 UTF-8 一致、
  `$logRoot` 赋值行不与注释合并；同时 PowerShell 5.1 的解析器（AST）对该文件
  报 0 个语法错误。
- **失败必须上抛**：清理真失败时包装脚本以非零退出，并且**不调用构建命令**；
  清理成功时构建命令被调用、退出码为 0。

全部测试只操作 `tempfile` 下的隔离目录：`LOCALAPPDATA` 与 `APPDATA` 都指向
临时根，构建命令用同目录内的替身 `tauri.cmd`（只写标记文件），不解析、不执行
真实打包命令，不触碰真实的 `%LOCALAPPDATA%\PairHarness` /
`%APPDATA%\com.jonahwu.hsr-partner-harness`。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "desktop" / "scripts" / "tauri-with-first-run-reset.ps1"
POWERSHELL = shutil.which("powershell.exe")

APP_IDENTIFIER = "com.jonahwu.hsr-partner-harness"
LOG_NAME = "sidecar.stderr.log"
CP936 = "cp936"

# 清理失败时包装脚本必须打印的标记（Write-Failure 的前缀）。
FAILURE_PREFIX = "tauri-with-first-run-reset:"


def _require_powershell() -> str:
    if not POWERSHELL:
        pytest.fail("Windows PowerShell 5.1 (powershell.exe) is unavailable on this machine.")
    return POWERSHELL


def _run_script(
    script: Path,
    *,
    env: dict[str, str],
    args: tuple[str, ...],
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    """在给定环境里运行包装脚本，真实收集退出码与输出。"""
    return subprocess.run(
        [
            _require_powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *args,
        ],
        cwd=str(script.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class _Sandbox:
    """隔离的打包环境：临时 shell 根 + 临时 LOCALAPPDATA/APPDATA + 替身构建命令。"""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="v039_r1_reset_"))
        self.scripts = self.root / "scripts"
        self.bin = self.root / "node_modules" / ".bin"
        self.scripts.mkdir(parents=True)
        self.bin.mkdir(parents=True)
        self.script = self.scripts / SCRIPT_PATH.name
        shutil.copyfile(SCRIPT_PATH, self.script)

        self.local_app_data = self.root / "localappdata"
        self.app_data = self.root / "appdata"
        self.log_root = self.app_data / APP_IDENTIFIER
        self.build_marker = self.root / "build-called.txt"
        self.build_exit_code = 0
        self._write_fake_tauri()

    @property
    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "LOCALAPPDATA": str(self.local_app_data),
            "APPDATA": str(self.app_data),
        }

    def _write_fake_tauri(self) -> None:
        """替身构建命令：只留调用痕迹与可配置退出码，不执行真实打包。"""
        command = self.bin / "tauri.cmd"
        command.write_text(
            "@echo off\r\n"
            f'echo called %*>>"{self.build_marker}"\r\n'
            f"exit /b {self.build_exit_code}\r\n",
            encoding="ascii",
            newline="\r\n",
        )

    def set_build_exit_code(self, code: int) -> None:
        self.build_exit_code = code
        self._write_fake_tauri()

    def seed_first_run_state(self) -> None:
        """铺一份与真机同构的首启状态：业务数据 + WebView 存储 + sidecar stderr 日志。"""
        webview_default = (
            self.local_app_data / APP_IDENTIFIER / "EBWebView" / "Default"
        )
        (self.local_app_data / "PairHarness").mkdir(parents=True)
        (webview_default / "Local Storage").mkdir(parents=True)
        (webview_default / "Session Storage").mkdir(parents=True)
        self.log_root.mkdir(parents=True)
        (self.log_root / LOG_NAME).write_text("previous batch traceback\n", encoding="utf-8")
        (self.log_root / f"{LOG_NAME}.1").write_text("rolled\n", encoding="utf-8")

    def remaining_logs(self) -> list[str]:
        if not self.log_root.exists():
            return []
        return sorted(path.name for path in self.log_root.iterdir())

    def build_was_called(self) -> bool:
        return self.build_marker.exists()

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


@pytest.fixture
def sandbox() -> _Sandbox:
    box = _Sandbox()
    try:
        yield box
    finally:
        box.cleanup()


def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_require_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120.0,
    )


def _current_user_sid() -> str:
    result = _run_powershell("[Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n")
    assert result.returncode == 0 and result.stdout.strip(), (
        f"读取当前用户 SID 失败：{result.stdout}\n{result.stderr}"
    )
    return result.stdout.strip()


def _apply_deny_delete_ace(path: Path) -> None:
    """给目录加继承的 Deny(Delete, DeleteSubdirectoriesAndFiles) ACE。

    真机上让 `Remove-Item -Force` 失败需要权限层面的拒绝：只读属性与共享句柄都
    拦不住 `-Force`。这里用 `icacls` 而不是 `Get-Acl`/`Set-Acl`——后两者属于
    Microsoft.PowerShell.Security，在受限语言模式下无法自动加载。ACE 只作用于
    临时目录，测试结束必须调用 _reset_acl 复位，否则目录删不掉。
    """
    sid = _current_user_sid()
    script = (
        f"$sid = '{sid}'\n"
        f"$target = '{path}'\n"
        "$out = & icacls $target /deny ('*' + $sid + ':(OI)(CI)(DE,DC)') 2>&1\n"
        "if ($LASTEXITCODE -ne 0) { Write-Output ($out -join [string][char]10); exit 1 }\n"
    )
    result = _run_powershell(script)
    assert result.returncode == 0, f"注入删除失败的前置条件失败：{result.stdout}\n{result.stderr}"


def _reset_acl(path: Path) -> None:
    sid = _current_user_sid()
    script = (
        f"$sid = '{sid}'\n"
        f"$target = '{path}'\n"
        "if (Test-Path -LiteralPath $target) {\n"
        "  & icacls $target /remove:d ('*' + $sid) 2>&1 | Out-Null\n"
        "  & icacls $target /grant ('*' + $sid + ':(OI)(CI)F') 2>&1 | Out-Null\n"
        "}\n"
    )
    _run_powershell(script)


# --- 编码稳健性（V039-R1-001 的根因） -------------------------------------------------


def test_script_is_pure_ascii_without_bom_and_with_lf_endings() -> None:
    """脚本必须纯 ASCII、无 BOM、LF 行尾：这样 5.1 无论按哪种代码页解码都不变。"""
    raw = SCRIPT_PATH.read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf"), "脚本带 UTF-8 BOM；本项目的文本约定是无 BOM"
    non_ascii = [index for index, byte in enumerate(raw) if byte > 0x7F]
    assert non_ascii == [], f"脚本含非 ASCII 字节（偏移 {non_ascii[:8]}），5.1 会按 ANSI 代码页解码"
    assert b"\r" not in raw, "脚本含 CR；.gitattributes 约定 LF"


def test_cp936_decoding_preserves_every_line() -> None:
    """按系统 ANSI 代码页（CP936）解码时行数不变，`$logRoot` 赋值行不被注释吞并。

    V039-S4-010 的现场根因正是这条不成立：UTF-8 解码 116 行、CP936 解码 114 行。
    """
    raw = SCRIPT_PATH.read_bytes()
    utf8_lines = raw.decode("utf-8").splitlines()
    ansi_lines = raw.decode(CP936).splitlines()

    assert len(ansi_lines) == len(utf8_lines)
    assignments = [line for line in ansi_lines if line.strip().startswith("$logRoot =")]
    assert len(assignments) == 1, f"CP936 解码后 $logRoot 赋值行数异常：{assignments}"
    assert not [line for line in ansi_lines if "#" in line and "$logRoot =" in line], (
        "CP936 解码后有注释与 $logRoot 赋值合并成同一行（换行被吞）"
    )


def test_both_scripts_decode_identically_under_utf8_and_ansi() -> None:
    """重置脚本与打包脚本：UTF-8 解码与 CP936 解码必须逐字符相同。

    这是 5.1 实际走的那条解码路径（无 BOM → 系统 ANSI 代码页）；两者只要出现差异，
    就说明文件依赖了「5.1 会按 UTF-8 读」这个不成立的假设。
    """
    for script_path in (SCRIPT_PATH, BUILD_SIDECAR_PATH):
        result = _run_powershell(
            "$utf8 = New-Object Text.UTF8Encoding($false)" + chr(10)
            + f"$b = [IO.File]::ReadAllBytes('{script_path}')" + chr(10)
            + "$u = $utf8.GetString($b)" + chr(10)
            + "$a = [Text.Encoding]::GetEncoding(936).GetString($b)" + chr(10)
            + "if ($u -ceq $a) { Write-Output 'identical' } else {" + chr(10)
            + "  Write-Output 'differ'" + chr(10)
            + "  Write-Output ('utf8Length=' + $u.Length + ' ansiLength=' + $a.Length)" + chr(10)
            + "}" + chr(10)
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[0].strip() == "identical", (
            f"{script_path.name} 在 UTF-8 与 CP936 下解码不一致：{result.stdout.strip()}"
        )


def test_powershell_51_parser_reports_no_syntax_error() -> None:
    """用 PowerShell 5.1 自己的解析器读真实文件：0 语法错误，赋值语句都在。"""
    script = (
        "$tokens = $null; $errors = $null\n"
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT_PATH}', [ref]$tokens, [ref]$errors)\n"
        "Write-Output ('errors=' + @($errors).Count)\n"
        "foreach ($e in @($errors)) { Write-Output ('ERR ' + $e.Message) }\n"
    )
    result = subprocess.run(
        [_require_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120.0,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].strip() == "errors=0", result.stdout


# --- 隔离性：清理只动临时根 -----------------------------------------------------------


def test_isolated_cleanup_clears_webview_state_and_sidecar_logs(sandbox: _Sandbox) -> None:
    """-ResetOnly：业务数据、WebView 存储与 sidecar stderr 日志及其滚动副本全部清空。"""
    sandbox.seed_first_run_state()

    result = _run_script(sandbox.script, env=sandbox.env, args=("-ResetOnly",))

    assert result.returncode == 0, result.stderr
    assert not (sandbox.local_app_data / "PairHarness").exists()
    assert not (
        sandbox.local_app_data / APP_IDENTIFIER / "EBWebView" / "Default" / "Local Storage"
    ).exists()
    assert sandbox.remaining_logs() == []
    # PowerShell 会把 8.3 短名（CI 上 %TEMP% 是 C:\Users\RUNNER~1\...）规范成长名，
    # 因此按规范化后的路径比对，而不是按字符串直接比对。
    expected_log = sandbox.root.resolve() / "appdata" / APP_IDENTIFIER / LOG_NAME
    cleared = {
        Path(line.split("Cleared:", 1)[1].strip()).resolve()
        for line in result.stdout.splitlines()
        if line.startswith("Cleared:")
    }
    assert expected_log in cleared, result.stdout
    assert sandbox.build_was_called() is False


def test_cleanup_targets_stay_inside_the_isolated_roots(sandbox: _Sandbox) -> None:
    """所有 `Cleared:` 目标都在临时根内：测试不可能碰到真实用户目录。"""
    sandbox.seed_first_run_state()

    result = _run_script(sandbox.script, env=sandbox.env, args=("-ResetOnly",))
    cleared = [
        Path(line.split("Cleared:", 1)[1].strip())
        for line in result.stdout.splitlines()
        if line.startswith("Cleared:")
    ]

    assert cleared, result.stdout
    root = sandbox.root.resolve()
    for target in cleared:
        assert root in target.resolve().parents or target.resolve() == root, target


# --- 失败传播：清理失败必须非零退出且不构建 -------------------------------------------


def test_reset_only_failure_exits_non_zero_and_reports_the_cause(sandbox: _Sandbox) -> None:
    """注入真实删除失败后，-ResetOnly 必须非零退出并打印失败原因，日志保持原样。"""
    sandbox.seed_first_run_state()
    _apply_deny_delete_ace(sandbox.log_root)
    try:
        # 前置条件自检：确认注入真的阻止了删除，否则本用例没有验证价值。
        assert not _delete_succeeds(sandbox.log_root / LOG_NAME)
        result = _run_script(sandbox.script, env=sandbox.env, args=("-ResetOnly",))
    finally:
        _reset_acl(sandbox.log_root)

    assert result.returncode != 0, f"清理失败却以 {result.returncode} 退出\n{result.stdout}"
    assert FAILURE_PREFIX in result.stderr, result.stderr
    # 系统错误文本随 OS 语言本地化：英文 "denied" 与中文「访问被拒绝」都算原因已打印。
    assert "denied" in result.stderr.lower() or "拒绝" in result.stderr, result.stderr
    assert sandbox.remaining_logs() == [LOG_NAME, f"{LOG_NAME}.1"]


def test_reset_failure_after_build_blocks_further_steps(sandbox: _Sandbox) -> None:
    """构建成功后清理失败：非零退出，且失败不会再往下走（不出现成功收尾）。"""
    sandbox.seed_first_run_state()
    _apply_deny_delete_ace(sandbox.log_root)
    try:
        assert not _delete_succeeds(sandbox.log_root / LOG_NAME)
        result = _run_script(
            sandbox.script, env=sandbox.env, args=("build", "--no-bundle")
        )
    finally:
        _reset_acl(sandbox.log_root)

    assert sandbox.build_was_called() is True
    assert result.returncode != 0, f"清理失败却以 {result.returncode} 退出\n{result.stdout}"
    assert FAILURE_PREFIX in result.stderr, result.stderr
    assert sandbox.remaining_logs() == [LOG_NAME, f"{LOG_NAME}.1"]


def test_no_arguments_fails_without_calling_build(sandbox: _Sandbox) -> None:
    """缺参数是用法错误：非零退出，且不能调用构建命令。"""
    result = _run_script(sandbox.script, env=sandbox.env, args=())

    assert result.returncode != 0
    assert sandbox.build_was_called() is False
    assert "Provide Tauri arguments" in result.stderr


def test_successful_build_runs_cleanup_and_exits_zero(sandbox: _Sandbox) -> None:
    """正常路径：构建被调用、退出码 0、首启状态被清空。"""
    sandbox.seed_first_run_state()

    result = _run_script(sandbox.script, env=sandbox.env, args=("build", "--no-bundle"))

    assert result.returncode == 0, result.stderr
    assert sandbox.build_was_called() is True
    assert sandbox.remaining_logs() == []
    assert not (sandbox.local_app_data / "PairHarness").exists()


def test_failing_build_is_reported_and_cleanup_is_skipped(sandbox: _Sandbox) -> None:
    """构建失败必须如实上报，且不执行首启清理（失败构建不产生「已清理」的假象）。"""
    sandbox.seed_first_run_state()
    sandbox.set_build_exit_code(7)

    result = _run_script(sandbox.script, env=sandbox.env, args=("build", "--no-bundle"))

    assert result.returncode != 0
    assert sandbox.build_was_called() is True
    assert "exit code 7" in result.stderr
    assert sandbox.remaining_logs() == [LOG_NAME, f"{LOG_NAME}.1"]


def _delete_succeeds(path: Path) -> bool:
    """前置条件自检：该路径当前能不能被 `Remove-Item -Force` 删除。"""
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        f"try {{ Remove-Item -LiteralPath '{path}' -Force -ErrorAction Stop; 'deleted' }} "
        "catch { 'blocked' }\n"
    )
    result = subprocess.run(
        [_require_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120.0,
    )
    return "deleted" in result.stdout

# --- 打包脚本不再以 Codex 原生分发为先决（B-03 剥离，父任务追加范围） -------------------
#
# 依据产品决策 B-03：只支持 OpenAI Chat Completions 兼容端点，Codex 要求彻底剥离。
# 所以打包不得再因为找不到 `@openai/codex` 而失败，也不得再把它拷进 resources；
# Reasonix（DeepSeek 编程助手）是保留的必需资源，它的查找与构建失败路径必须原样保留。

BUILD_SIDECAR_PATH = REPO_ROOT / "desktop" / "scripts" / "build-sidecar.ps1"

# Codex 特有的查找路径与失败文案：剥离后一个都不应留下。
CODEX_BUILD_MARKERS = (
    "PAIR_HARNESS_CODEX_NATIVE_ROOT",
    "PAIR_HARNESS_CODEX_BIN",
    "PAIR_HARNESS_BUNDLED_CODEX_BIN",
    "@openai",
    "codex.exe",
    "Codex native Windows distribution not found",
)

# Reasonix 是保留的必需资源：这些锚点必须原样存在。
REASONIX_BUILD_ANCHORS = (
    "PAIR_HARNESS_REASONIX_NATIVE_ROOT",
    'Join-Path $repoRoot "DeepSeek-Reasonix"',
    "./cmd/reasonix",
    "Reasonix Windows native binary not found",
    "reasonix acp",
    # npm 与 shim 两条回落路径（保留全局 npm 根探测就是为了它们）
    'Join-Path $npmRoot "reasonix\\node_modules\\@reasonix\\cli-win32-x64\\bin\\reasonix.exe"',
    'Get-Command reasonix.cmd',
)


def _parse_errors(script_path: Path) -> tuple[int, str]:
    """用 PowerShell 5.1 自己的解析器解析脚本，返回 (错误数, 输出)。"""
    script = (
        "$tokens = $null; $errors = $null" + chr(10)
        + f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$errors)" + chr(10)
        + "Write-Output ('errors=' + @($errors).Count)" + chr(10)
        + "foreach ($e in @($errors)) { Write-Output ('ERR ' + $e.Message) }" + chr(10)
    )
    result = _run_powershell(script)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines and lines[0].strip().startswith("errors="), result.stdout
    return int(lines[0].strip().split("=", 1)[1]), result.stdout


def test_reset_script_parses_under_powershell_51() -> None:
    """固定文件路径上的解析检查（与下面按路径参数化的检查互为回归锚点）。"""
    errors, output = _parse_errors(SCRIPT_PATH)
    assert errors == 0, output


def test_scripts_decode_identically_under_utf8_and_ansi() -> None:
    """两个打包脚本都必须「纯 ASCII 或带 BOM」：5.1 才会按 UTF-8 解码。

    纯 ASCII 时两种代码页解码结果相同；带 BOM 时 5.1 明确按 UTF-8 读。
    不带 BOM 又含非 ASCII 才是 V039-R1-001 的危险形态。
    """
    for script_path in (SCRIPT_PATH, BUILD_SIDECAR_PATH):
        raw = script_path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        non_ascii = [index for index, byte in enumerate(raw) if byte > 0x7F]
        assert has_bom or non_ascii == [], (
            f"{script_path.name} 既无 BOM 又含非 ASCII 字节（偏移 {non_ascii[:8]}）："
            "5.1 会按 ANSI 代码页解码，可能吞掉换行"
        )
        assert b"\r" not in raw, f"{script_path.name} 含 CR 行尾：.gitattributes 约定 LF"
        errors, output = _parse_errors(script_path)
        assert errors == 0, f"{script_path.name} 解析报错：{output}"


def test_build_sidecar_no_longer_requires_the_codex_native_distribution() -> None:
    """打包脚本里不应再有任何 Codex 原生分发的查找、拷贝或失败条件。"""
    text = BUILD_SIDECAR_PATH.read_text(encoding="utf-8")
    leftovers = [marker for marker in CODEX_BUILD_MARKERS if marker in text]

    assert leftovers == [], f"build-sidecar.ps1 仍依赖 Codex：{leftovers}"


def test_build_sidecar_still_requires_reasonix() -> None:
    """剥离 Codex 不得顺手删掉 Reasonix：必需资源的查找与失败路径必须保留。"""
    text = BUILD_SIDECAR_PATH.read_text(encoding="utf-8")
    missing = [anchor for anchor in REASONIX_BUILD_ANCHORS if anchor not in text]

    assert missing == [], f"build-sidecar.ps1 丢失 Reasonix 能力：{missing}"
