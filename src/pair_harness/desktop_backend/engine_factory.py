"""编程助手引擎工厂——V0.2 M3（方案 §M3-4/§M3-5）。

按账号配置（``engine``：codex / deepseek）构建 CodingEngine：
- codex → CodexAppServerEngine（app-server JSONL）；
- deepseek → AcpCodingEngine（本地 DeepSeek-Reasonix 的 ``reasonix acp``，
  ACP v1，出处见 THIRD_PARTY_NOTICES）。

每个本地账号注入独立的 Codex 数据目录（CODEX_HOME），Token/Key/session
不串账号；环境变量覆盖顺序：显式传入 > PAIR_HARNESS_* 环境变量 > 默认命令。
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import (
    JsonlProcessTransport,
    SubprocessJsonLineConnection,
)


def resolve_codex_executable(bundled_bin: str | None = None) -> str:
    """codex 可执行文件：打包内置 > 环境变量 > PATH 默认。"""
    for candidate in (
        bundled_bin,
        os.getenv("PAIR_HARNESS_BUNDLED_CODEX_BIN"),
        os.getenv("CODEX_BIN"),
    ):
        if candidate:
            return candidate
    return "codex"


def resolve_reasonix_executable(bundled_bin: str | None = None) -> str:
    """reasonix 可执行文件（DeepSeek 编程助手）：环境变量 > PATH 默认。"""
    for candidate in (
        bundled_bin,
        os.getenv("PAIR_HARNESS_REASONIX_BIN"),
    ):
        if candidate:
            return candidate
    return "reasonix"


def build_coding_engine(
    *,
    engine_choice: str,
    codex_auth: CodexAuthService,
    codex_bin: str | None = None,
    reasonix_bin: str | None = None,
) -> "CodexAppServerEngine | AcpCodingEngine":
    """按账号配置构建编程助手引擎；认证数据目录按账号隔离注入。"""
    if engine_choice == "deepseek":
        from pair_harness.adapters.acp.engine import AcpCodingEngine

        executable = resolve_reasonix_executable(reasonix_bin)

        async def acp_connection() -> SubprocessJsonLineConnection:
            return await SubprocessJsonLineConnection.create(executable, args=["acp"])

        return AcpCodingEngine(
            JsonlProcessTransport(
                executable, connection_factory=acp_connection, request_timeout=3600.0
            )
        )

    executable = resolve_codex_executable(codex_bin)
    env = codex_auth.env_overrides

    async def codex_connection() -> SubprocessJsonLineConnection:
        return await SubprocessJsonLineConnection.create(
            executable, args=["app-server"], env=env
        )

    return CodexAppServerEngine(
        JsonlProcessTransport(
            executable, connection_factory=codex_connection, request_timeout=3600.0
        )
    )
