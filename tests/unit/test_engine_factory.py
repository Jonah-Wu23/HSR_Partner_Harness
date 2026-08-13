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
