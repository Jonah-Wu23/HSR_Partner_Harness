"""编程助手引擎工厂——V0.2 M3（方案 §M3-4/§M3-5）。

B-03（V0.3.9）：产品只支持 OpenAI Chat Completions 兼容端点，编程助手引擎
只剩一条路径——``AcpCodingEngine``（本地 DeepSeek-Reasonix 的
``reasonix acp``，ACP v1，出处见 THIRD_PARTY_NOTICES）。任意 http(s) 端点
都被写成账号私有的 ``REASONIX_HOME`` 供应商实例（见
:func:`ensure_reasonix_home`），Reasonix 按 ``base_url`` 自行识别供应商；
装配期不联网、不校验端点协议形态，端点不可达由真实请求如实失败。

每个本地账号使用独立的 Reasonix 配置目录
（``base_dir/accounts/{account_id}/reasonix``），端点、模型与密钥不串账号；
环境变量覆盖顺序：显式传入 > PAIR_HARNESS_* 环境变量 > 默认命令。
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pair_harness.adapters.codex.auth import CodexAuthService
from pair_harness.adapters.codex.transport import (
    JsonlProcessTransport,
    SubprocessJsonLineConnection,
)
from pair_harness.config.providers import (
    ProviderKind,
    detect_provider,
    load_reasoning_preset,
    normalize_effort,
)

# V0.3.8 T4：引擎的诊断告警出口（引擎无进展等），由装配方注入。
DiagnosticCallback = Callable[[dict[str, Any]], None]


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


def _reasonix_api_key_env(kind: ProviderKind) -> str:
    """``api_key_env`` 指向的变量名（Reasonix 从 ``<REASONIX_HOME>/.env`` 取值）。

    DeepSeek 端点沿用既有 ``DEEPSEEK_API_KEY``；通用兼容端点使用
    ``PAIR_HARNESS_DIALOGUE_API_KEY``——该名同时由 ``_provider_env`` 注入
    子进程环境，两处同名同值，不另造一套凭据命名。
    """
    if kind is ProviderKind.DEEPSEEK:
        return "DEEPSEEK_API_KEY"
    return "PAIR_HARNESS_DIALOGUE_API_KEY"


def _reasonix_config_toml(
    *, kind: ProviderKind, base_url: str, model: str, effort: str
) -> str:
    """``REASONIX_HOME/config.toml`` 正文：一个 OpenAI 兼容供应商实例。

    依据（本机 Reasonix 二进制内嵌文档 §3.1 与 REASONING_PROVIDERS）：
    ``kind = "openai"`` 就是 OpenAI 兼容 ``/chat/completions`` 实现，
    “OpenAI-compatible vendors are config instances of kind = "openai",
    differing only in base_url / model / api_key_env”；供应商识别按
    ``base_url`` 的 host 判定（``matchesVendorHost``），实例 ``name`` 只是
    标签（文档示例 `"my-glm-proxy"`）；``default_model`` 经
    ``Config.ResolveModel`` 接受 ``provider/model`` 形态。
    """
    instance = kind.value
    lines = [
        f"default_model = {_toml_quote(f'{instance}/{model}')}",
        "",
        "[[providers]]",
        f"name = {_toml_quote(instance)}",
        f"kind = {_toml_quote('openai')}",
        f"base_url = {_toml_quote(base_url)}",
        f"model = {_toml_quote(model)}",
        f"api_key_env = {_toml_quote(_reasonix_api_key_env(kind))}",
    ]
    if kind is ProviderKind.DEEPSEEK:
        # DeepSeek 沿用既有实测值；通用端点不写未证实的能力数字。
        lines.append("context_window = 1000000")
    lines += [
        f"effort = {_toml_quote(effort)}",
        "",
        "[tools]",
        f"enabled = [{', '.join(_toml_quote(name) for name in REASONIX_EXECUTION_TOOLS)}]",
    ]
    return "\n".join(lines) + "\n"


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
    kind = detect_provider(base_url)
    effort = _normalize_reasonix_effort(base_url, model, reasoning_effort)
    toml = _reasonix_config_toml(
        kind=kind, base_url=base_url, model=model, effort=effort
    )
    api_key_env = _reasonix_api_key_env(kind)
    env_body = f"{api_key_env}={api_key}\n" if api_key else ""
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
    codex_auth: CodexAuthService,
    reasonix_bin: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    reasoning_effort: str = "auto",
    idle_timeout: float = 600.0,
    diagnostic_callback: DiagnosticCallback | None = None,
) -> "AcpCodingEngine":
    """为任意 OpenAI Chat Completions 兼容端点构建编程助手引擎。

    B-03：产品只有 reasonix ACP 一条引擎路径，端点（包括解析不了的域名）
    只被写进账号私有的 Reasonix 配置，不建立任何连接，因此装配不会因为
    端点的协议形态或可达性失败；连接失败一律发生在真实请求上并由调用方
    如实暴露。

    ``reasoning_effort`` 是账号级 ``dialogue.reasoning_effort``，写进
    Reasonix 供应商配置。``idle_timeout`` 是回合连续无事件后的空闲超时
    （秒），默认 10 分钟。``diagnostic_callback`` 接收引擎诊断告警（如
    回合无进展），由装配方转发到客户端事件通道（V0.3.8 T4，契约 §14.6）。

    ``codex_auth`` 只承担账号定位（``base_dir/accounts/{account_id}/reasonix``），
    与 Codex 登录态无关。
    """
    from pair_harness.adapters.acp.engine import AcpCodingEngine

    executable = resolve_reasonix_executable(reasonix_bin)
    engine_env = _provider_env(base_url=base_url, api_key=api_key, model=model)
    if base_url and model:
        reasonix_home = ensure_reasonix_home(
            codex_auth,
            base_url=base_url,
            model=model,
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
        idle_timeout=idle_timeout,
        diagnostic_callback=diagnostic_callback,
    )
