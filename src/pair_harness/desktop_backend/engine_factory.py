"""编程助手引擎工厂——V0.2 M3（方案 §M3-4/§M3-5）。

按账号配置（``engine``：codex / deepseek）构建 CodingEngine：
- codex → CodexAppServerEngine（app-server JSONL）；
- deepseek → AcpCodingEngine（本地 DeepSeek-Reasonix 的 ``reasonix acp``，
  ACP v1，出处见 THIRD_PARTY_NOTICES）。

每个本地账号注入独立的 Codex 数据目录（CODEX_HOME），Token/Key/session
不串账号；环境变量覆盖顺序：显式传入 > PAIR_HARNESS_* 环境变量 > 默认命令。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import (
    JsonlProcessTransport,
    SubprocessJsonLineConnection,
)

logger = logging.getLogger(__name__)


def _provider_env(
    *, base_url: str | None, api_key: str | None, model: str | None
) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "PAIR_HARNESS_DIALOGUE_BASE_URL": base_url,
            "PAIR_HARNESS_DIALOGUE_API_KEY": api_key,
            "PAIR_HARNESS_DIALOGUE_MODEL": model,
            "DEEPSEEK_BASE_URL": base_url,
            "DEEPSEEK_API_KEY": api_key,
            "DEEPSEEK_MODEL": model,
        }.items()
        if value
    }


def build_codex_transport(
    *,
    codex_auth: CodexAuthService,
    codex_bin: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> JsonlProcessTransport:
    executable = resolve_codex_executable(codex_bin)
    env = {**codex_auth.env_overrides, **_provider_env(base_url=base_url, api_key=api_key, model=None)}
    if base_url:
        env["OPENAI_BASE_URL"] = base_url
    if api_key:
        env["OPENAI_API_KEY"] = api_key

    async def connection() -> SubprocessJsonLineConnection:
        return await SubprocessJsonLineConnection.create(
            executable, args=["app-server"], env=env
        )

    return JsonlProcessTransport(
        executable, connection_factory=connection, request_timeout=3600.0
    )


def build_codex_dialogue_model(
    *,
    codex_auth: CodexAuthService,
    model: str,
    codex_bin: str | None = None,
) -> "CodexDialogueModel":
    from pair_harness.adapters.codex.dialogue import CodexDialogueModel

    return CodexDialogueModel(
        build_codex_transport(codex_auth=codex_auth, codex_bin=codex_bin),
        model=model,
    )


def ensure_reasonix_home(
    codex_auth: CodexAuthService,
    *,
    base_url: str,
    model: str,
    api_key: str,
) -> Path:
    """为账号准备 reasonix 配置目录（``REASONIX_HOME/config.toml`` + ``.env``）。

    reasonix 不从进程环境变量读取 provider 的 base_url/model/密钥：
    - 模型与端点只经 ``config.toml`` 解析（``api_key_env`` 指向密钥名）；
    - 密钥运行期只从 ``<REASONIX_HOME>/.env`` 解析（``api_key_env`` 指定的
      变量名在此文件中取值），注入的子进程环境变量不参与。

    每个本地账号独立目录，与 CODEX_HOME 同构
    （``base_dir/accounts/{account_id}/reasonix``），配置与密钥不串账号。
    """
    home = codex_auth.base_dir / "accounts" / codex_auth.account_id / "reasonix"
    home.mkdir(parents=True, exist_ok=True)
    toml = (
        f'default_model = "deepseek/{model}"\n\n'
        "[[providers]]\n"
        'name = "deepseek"\n'
        'kind = "openai"\n'
        f'base_url = "{base_url}"\n'
        f'model = "{model}"\n'
        'api_key_env = "DEEPSEEK_API_KEY"\n'
        "context_window = 1000000\n"
        'effort = "high"\n'
    )
    env_body = f"DEEPSEEK_API_KEY={api_key}\n" if api_key else ""
    try:
        config_path = home / "config.toml"
        if not config_path.exists() or config_path.read_text(encoding="utf-8") != toml:
            config_path.write_text(toml, encoding="utf-8")
        env_path = home / ".env"
        if not env_path.exists() or env_path.read_text(encoding="utf-8") != env_body:
            env_path.write_text(env_body, encoding="utf-8")
    except OSError as exc:
        logger.warning("写入 reasonix 配置失败（%s），DeepSeek 编程助手可能无法启动：%s", home, exc)
    return home


def _resolve_executable(
    bundled_bin: str | None, env_names: tuple[str, ...], default: str
) -> str:
    """可执行文件：打包内置 > 环境变量 > PATH 默认名。"""
    for candidate in (bundled_bin, *(os.getenv(name) for name in env_names)):
        if candidate:
            return candidate
    return default


def resolve_codex_executable(bundled_bin: str | None = None) -> str:
    """codex 可执行文件：打包内置 > 环境变量 > PATH 默认。"""
    return _resolve_executable(
        bundled_bin, ("PAIR_HARNESS_BUNDLED_CODEX_BIN", "CODEX_BIN"), "codex"
    )


def resolve_reasonix_executable(bundled_bin: str | None = None) -> str:
    """reasonix 可执行文件（DeepSeek 编程助手）。

    Tauri 侧发现内置二进制后经 ``PAIR_HARNESS_BUNDLED_REASONIX_BIN``
    注入（见 main.rs packaged_reasonix）。
    """
    return _resolve_executable(
        bundled_bin,
        ("PAIR_HARNESS_BUNDLED_REASONIX_BIN", "PAIR_HARNESS_REASONIX_BIN"),
        "reasonix",
    )


def build_coding_engine(
    *,
    engine_choice: str,
    codex_auth: CodexAuthService,
    codex_bin: str | None = None,
    reasonix_bin: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> "CodexAppServerEngine | AcpCodingEngine":
    """按账号配置构建编程助手引擎；角色与助手共享模型参数。"""
    shared_env = _provider_env(base_url=base_url, api_key=api_key, model=model)
    if engine_choice == "deepseek":
        from pair_harness.adapters.acp.engine import AcpCodingEngine

        executable = resolve_reasonix_executable(reasonix_bin)
        engine_env = dict(shared_env)
        if base_url and (dialogue_model_name := (model or "")):
            reasonix_home = ensure_reasonix_home(
                codex_auth,
                base_url=base_url,
                model=dialogue_model_name,
                api_key=api_key or "",
            )
            engine_env["REASONIX_HOME"] = str(reasonix_home)

        async def acp_connection() -> SubprocessJsonLineConnection:
            return await SubprocessJsonLineConnection.create(
                executable, args=["acp"], env=engine_env
            )

        return AcpCodingEngine(
            JsonlProcessTransport(
                executable, connection_factory=acp_connection, request_timeout=3600.0
            ),
            model=model,
        )

    transport = build_codex_transport(
        codex_auth=codex_auth,
        codex_bin=codex_bin,
        base_url=base_url,
        api_key=api_key,
    )

    return CodexAppServerEngine(
        transport,
        model=model or "gpt-5.6-sol",
    )
