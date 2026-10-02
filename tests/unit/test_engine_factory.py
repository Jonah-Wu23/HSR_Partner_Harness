from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from dotenv import dotenv_values

from pair_harness.adapters.acp.engine import AcpCodingEngine
from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.desktop_backend.engine_factory import (
    REASONIX_EXECUTION_TOOLS,
    build_coding_engine,
    ensure_reasonix_home,
)


def test_build_coding_engine_assembles_acp_engine_without_connecting(tmp_path: Path) -> None:
    """装配只写账号私有的 Reasonix 配置，不解析端点，也不启动 reasonix 进程。"""
    diagnostics: list[dict] = []
    engine = build_coding_engine(
        codex_auth=CodexAuthService(tmp_path, "default-local"),
        base_url="https://no-such-host.invalid/v1",
        model="glm-4.6",
        api_key="sk-test",
        idle_timeout=123.0,
        diagnostic_callback=diagnostics.append,
    )

    assert isinstance(engine, AcpCodingEngine)
    assert not engine.transport.is_running
    assert (tmp_path / "accounts" / "default-local" / "reasonix" / "config.toml").is_file()
    assert engine.idle_timeout == 123.0
    engine.diagnostic_callback({"code": "engine_no_progress"})
    assert diagnostics == [{"code": "engine_no_progress"}]


@pytest.mark.parametrize(
    ("base_url", "model", "provider", "env"),
    [
        (
            "https://no-such-host.invalid/v1",
            "glm-4.6",
            # 通用端点不写未证实的上下文窗口，也没有可用的深度档位
            {
                "name": "openai_compatible",
                "kind": "openai",
                "base_url": "https://no-such-host.invalid/v1",
                "model": "glm-4.6",
                "api_key_env": "PAIR_HARNESS_DIALOGUE_API_KEY",
                "effort": "auto",
            },
            {"PAIR_HARNESS_DIALOGUE_API_KEY": "sk-test"},
        ),
        (
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            {
                "name": "deepseek",
                "kind": "openai",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "context_window": 1000000,
                "effort": "max",
            },
            {"DEEPSEEK_API_KEY": "sk-test"},
        ),
    ],
)
def test_reasonix_home_writes_endpoint_provider_and_key(
    tmp_path: Path, base_url: str, model: str, provider: dict, env: dict
) -> None:
    home = ensure_reasonix_home(
        CodexAuthService(tmp_path, "default-local"),
        base_url=base_url,
        model=model,
        api_key="sk-test",
        reasoning_effort="max",
    )

    assert home == tmp_path / "accounts" / "default-local" / "reasonix"
    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert config["default_model"] == f"{provider['name']}/{model}"
    assert config["providers"] == [provider]
    assert dotenv_values(home / ".env") == env


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
    """含引号、反斜杠、换行的配置按 TOML 转义写出；.env 原子替换后不留临时文件。"""
    home = ensure_reasonix_home(
        CodexAuthService(tmp_path, "default-local"),
        base_url='https://api.deepseek.com/v1?x="a"\\b\nline2',
        model='deepseek-v4-flash"',
        api_key="sk-line1\nsk-line2",
    )

    config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    assert config["providers"][0]["base_url"] == 'https://api.deepseek.com/v1?x="a"\\b\nline2'
    assert config["providers"][0]["model"] == 'deepseek-v4-flash"'
    assert dotenv_values(home / ".env") == {"DEEPSEEK_API_KEY": "sk-line1\nsk-line2"}
    assert not list(home.glob(".*.tmp"))
