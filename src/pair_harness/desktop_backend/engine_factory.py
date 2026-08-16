"""编程助手引擎工厂——V0.2 M3（方案 §M3-4/§M3-5）。

按统一供应商配置（``engine`` 由 ``dialogue.provider`` 推导）构建 CodingEngine：
- codex → CodexAppServerEngine（app-server JSONL）；
- deepseek → AcpCodingEngine（本地 DeepSeek-Reasonix 的 ``reasonix acp``，
  ACP v1，出处见 THIRD_PARTY_NOTICES）。

每个本地账号注入独立的 Codex 数据目录（CODEX_HOME），Token/Key/session
不串账号；环境变量覆盖顺序：显式传入 > PAIR_HARNESS_* 环境变量 > 默认命令。
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.codex.engine import CodexAppServerEngine
from pair_harness.adapters.codex.transport import (
    JsonlProcessTransport,
    SubprocessJsonLineConnection,
)
from pair_harness.config.providers import load_reasoning_preset, normalize_effort


# 古代机械只需要项目文件和命令执行工具。工作流控制工具属于宿主会话，
# 不应进入委派任务，否则模型会在没有 Goal 的 ACP 会话里调用它。
REASONIX_EXECUTION_TOOLS = (
    "bash",
    "code_index",
    "delete_range",
    "delete_symbol",
    "edit_file",
    "glob",
    "grep",
    "ls",
    "move_file",
    "multi_edit",
    "notebook_edit",
    "read_file",
    "web_fetch",
    "write_file",
)


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
    reasoning_effort: str = "auto",
) -> "CodexDialogueModel":
    from pair_harness.adapters.codex.dialogue import CodexDialogueModel

    return CodexDialogueModel(
        build_codex_transport(codex_auth=codex_auth, codex_bin=codex_bin),
        model=model,
        reasoning_effort=reasoning_effort,
    )


def _toml_quote(value: str) -> str:
    """TOML basic string 严格转义，防止引号/换行/反斜杠破坏配置。"""
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\f", "\\f")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _atomic_write_text(path: Path, content: str) -> None:
    """同目录临时文件写入后原子替换（.env/config.toml 共用）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _normalize_reasonix_effort(base_url: str, model: str, effort: str) -> str:
    """把角色模型配置的档位归一化为 Reasonix 支持的 effort 值。

    Reasonix 的 provider ``effort`` 接受 ``auto`` 或后端支持的深度档位；
    不支持的输入回落到 ``auto``（服务端默认），绝不硬塞非法值。
    """
    preset = load_reasoning_preset(base_url, model)
    normalized = normalize_effort(effort, preset)
    return normalized or "auto"


def ensure_reasonix_home(
    codex_auth: CodexAuthService,
    *,
    base_url: str,
    model: str,
    api_key: str,
    reasoning_effort: str = "auto",
) -> Path:
    """为账号准备 reasonix 配置目录（``REASONIX_HOME/config.toml`` + ``.env``）。

    reasonix 不从进程环境变量读取 provider 的 base_url/model/密钥：
    - 模型与端点只经 ``config.toml`` 解析（``api_key_env`` 指向密钥名）；
    - 密钥运行期只从 ``<REASONIX_HOME>/.env`` 解析（``api_key_env`` 指定的
      变量名在此文件中取值），注入的子进程环境变量不参与。

    每个本地账号独立目录，与 CODEX_HOME 同构
    （``base_dir/accounts/{account_id}/reasonix``），配置与密钥不串账号。
    TOML 使用正式字符串转义，``.env``/``config.toml`` 都经同目录临时文件
    原子替换，异常配置不会留下半写文件。
    """
    home = codex_auth.base_dir / "accounts" / codex_auth.account_id / "reasonix"
    home.mkdir(parents=True, exist_ok=True)
    effort = _normalize_reasonix_effort(base_url, model, reasoning_effort)
    toml = (
        f"default_model = {_toml_quote(f'deepseek/{model}')}\n\n"
        "[[providers]]\n"
        f"name = {_toml_quote('deepseek')}\n"
        f"kind = {_toml_quote('openai')}\n"
        f"base_url = {_toml_quote(base_url)}\n"
        f"model = {_toml_quote(model)}\n"
        f"api_key_env = {_toml_quote('DEEPSEEK_API_KEY')}\n"
        "context_window = 1000000\n"
        f"effort = {_toml_quote(effort)}\n"
        "\n[tools]\n"
        f"enabled = [{', '.join(_toml_quote(name) for name in REASONIX_EXECUTION_TOOLS)}]\n"
    )
    env_body = f"DEEPSEEK_API_KEY={api_key}\n" if api_key else ""
    config_path = home / "config.toml"
    if not config_path.exists() or config_path.read_text(encoding="utf-8") != toml:
        _atomic_write_text(config_path, toml)
    env_path = home / ".env"
    if not env_path.exists() or env_path.read_text(encoding="utf-8") != env_body:
        _atomic_write_text(env_path, env_body)
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
        bundled_bin,
        ("PAIR_HARNESS_BUNDLED_CODEX_BIN", "PAIR_HARNESS_CODEX_BIN", "CODEX_BIN"),
        "codex",
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
    reasoning_effort: str = "auto",
    codex_idle_timeout: float = 600.0,
) -> "CodexAppServerEngine | AcpCodingEngine":
    """按统一供应商构建编程助手引擎；角色与助手共享模型参数。

    ``reasoning_effort`` 是账号级 ``dialogue.reasoning_effort``，用于
    Reasonix 生成配置与 Codex 回合请求。``codex_idle_timeout`` 是 Codex
    app-server 回合连续无事件后的空闲超时（秒），默认 10 分钟。
    """
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
                reasoning_effort=reasoning_effort,
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
        reasoning_effort=reasoning_effort,
        idle_timeout=codex_idle_timeout,
    )
