import subprocess
import sys
from pathlib import Path

import pytest

VALIDATE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "desktop" / "scripts" / "validate-pwa-dist.ps1"
)


def _validate(dist: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(VALIDATE_SCRIPT),
            "-DistPath",
            str(dist),
        ],
        capture_output=True,
        # Windows PowerShell 5.1 的管道输出使用系统 ANSI 代码页
        encoding="mbcs" if sys.platform == "win32" else "utf-8",
        errors="replace",
        timeout=120,
    )


def _write_files(root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")


def test_static_build_output_passes(tmp_path: Path) -> None:
    _write_files(
        tmp_path,
        (
            "index.html",
            "assets/index-abc12345.js",
            "assets/index-abc12345.js.map",
            "assets/index-def67890.css",
            "icon.svg",
            "manifest.webmanifest",
        ),
    )

    result = _validate(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("files", "offending"),
    [
        (("index.html", "server.py"), "server.py"),
        (("index.html", "assets/source.ts"), "source.ts"),
        (("index.html", "data/pair_harness.db"), "pair_harness.db"),
        (("index.html", ".env"), ".env"),
        (("assets/app.js",), "index.html"),
    ],
)
def test_invalid_dist_fails_and_names_the_offending_file(
    tmp_path: Path, files: tuple[str, ...], offending: str
) -> None:
    _write_files(tmp_path, files)

    result = _validate(tmp_path)

    assert result.returncode != 0
    assert offending in result.stdout + result.stderr
