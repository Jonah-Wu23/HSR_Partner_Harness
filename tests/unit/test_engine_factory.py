from __future__ import annotations

import tomllib
from pathlib import Path

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.desktop_backend.engine_factory import (
    REASONIX_EXECUTION_TOOLS,
    ensure_reasonix_home,
)


def test_reasonix_home_exposes_only_execution_tools(tmp_path: Path) -> None:
    home = ensure_reasonix_home(
        CodexAuthService(tmp_path, "default-local"),
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key="sk-test",
    )

    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))

    assert tuple(config["tools"]["enabled"]) == REASONIX_EXECUTION_TOOLS
    assert "update_goal" not in config["tools"]["enabled"]
    assert "todo_write" not in config["tools"]["enabled"]


def test_reasonix_home_writes_configured_supported_effort(tmp_path: Path) -> None:
    home = ensure_reasonix_home(
        CodexAuthService(tmp_path, "default-local"),
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key="sk-test",
        reasoning_effort="max",
    )

    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert config["providers"][0]["effort"] == "max"


def test_reasonix_home_normalizes_unsupported_effort_to_auto(tmp_path: Path) -> None:
    home = ensure_reasonix_home(
        CodexAuthService(tmp_path, "default-local"),
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key="sk-test",
        reasoning_effort="ultra",
    )

    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert config["providers"][0]["effort"] == "auto"


def test_reasonix_home_strictly_escapes_toml_and_writes_atomic_env(
    tmp_path: Path,
) -> None:
    """M3.3：含引号/反斜杠/换行的配置不能破坏 TOML；.env 原子替换无残留。"""
    home = ensure_reasonix_home(
        CodexAuthService(tmp_path, "default-local"),
        base_url='https://api.deepseek.com/v1?x="a"\\b\nline2',
        model='deepseek-v4-flash"',
        api_key="sk-line1\nsk-line2",
    )

    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert config["providers"][0]["base_url"] == 'https://api.deepseek.com/v1?x="a"\\b\nline2'
    assert config["providers"][0]["model"] == 'deepseek-v4-flash"'
    env_text = (home / ".env").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-line1\nsk-line2" in env_text
    assert not list(home.glob(".*.tmp"))
