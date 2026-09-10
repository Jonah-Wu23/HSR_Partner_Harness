"""CI 临时诊断脚本：定位 PowerShell 命令解析在沙箱 env 下失败的原因。

用后即删，不进入最终提交。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

PROBE = "\n".join(
    [
        "foreach ($n in @('Get-FileHash','Get-Item','Write-Host','Get-CimInstance','ConvertFrom-Json')) {",
        "  $c = Get-Command $n -ErrorAction SilentlyContinue",
        "  if ($c) { Write-Output ('CMD ' + $n + ' -> ' + $c.ModuleName) } else { Write-Output ('CMD ' + $n + ' -> MISSING') }",
        "}",
        "Write-Output ('PSHOME=' + $PSHOME)",
        "Write-Output ('PSModulePath=' + $env:PSModulePath)",
        "Write-Output ('PATHlen=' + ($env:PATH | Measure-Object -Character).Characters)",
    ]
)


def env_block_len(env: dict[str, str]) -> int:
    return sum(len(k) + len(v) + 2 for k, v in env.items())


def probe(label: str, env: dict[str, str], script: Path) -> None:
    print(f"--- {label} (env vars={len(env)}, block={env_block_len(env)}) ---")
    try:
        result = subprocess.run(
            [
                "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        print("returncode:", result.returncode)
        print("stdout:")
        print(result.stdout)
        print("stderr:")
        print(result.stderr)
    except Exception as exc:  # noqa: BLE001 - 诊断脚本，任何异常都要打印出来
        print("EXCEPTION:", type(exc).__name__, exc)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="ci_ps_diag_"))
    script = root / "probe.ps1"
    script.write_text(PROBE + "\n", encoding="ascii", newline="\n")

    print("python:", os.sys.version)
    print("env count:", len(os.environ))
    print("env block bytes:", env_block_len(dict(os.environ)))
    print("'PATH' in os.environ:", "PATH" in os.environ, "| 'Path' in os.environ:", "Path" in os.environ)
    print("os.environ['PATH'] length:", len(os.environ.get("PATH", "")))
    keys = [k for k in os.environ if k.upper() == "PATH"]
    print("PATH-ish keys:", keys)

    probe("plain os.environ", dict(os.environ), script)

    prepended = {**os.environ, "PATH": str(root) + os.pathsep + os.environ.get("PATH", "")}
    probe("PATH prepended", prepended, script)

    sandbox_like = {
        **os.environ,
        "PATH": str(root) + os.pathsep + os.environ.get("PATH", ""),
        "JAVA_HOME": str(root / "java"),
        "NDK_HOME": str(root / "ndk"),
        "ANDROID_HOME": str(root / "sdk"),
        "WRY_ANDROID_PACKAGE": "",
        "WRY_ANDROID_LIBRARY": "",
        "WRY_ANDROID_KOTLIN_FILES_OUT_DIR": "",
    }
    probe("sandbox-like", sandbox_like, script)

    for name in sorted(os.environ):
        if "PSMODULE" in name.upper() or "POWERSHELL" in name.upper():
            print(f"env[{name}]={os.environ[name]!r}")


if __name__ == "__main__":
    main()
