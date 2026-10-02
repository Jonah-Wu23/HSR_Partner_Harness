# 编程助手引擎工厂：经打包的 DeepSeek-Reasonix（reasonix acp，出处见 THIRD_PARTY_NOTICES）
# 接入任意 OpenAI Chat Completions 兼容端点。端点、模型与密钥写进账号私有的 REASONIX_HOME，
# 装配期不联网，端点不可达由真实请求如实失败。

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import tomli_w
from dotenv import set_key

from pair_harness.adapters.acp.engine import AcpCodingEngine
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

# 引擎诊断告警（如回合无进展）的出口，由装配方注入。
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


def _reasonix_api_key_env(kind: ProviderKind) -> str:
    """``api_key_env`` 指向的变量名；Reasonix 只从 ``<REASONIX_HOME>/.env`` 取它的值。"""
    if kind is ProviderKind.DEEPSEEK:
        return "DEEPSEEK_API_KEY"
    return "PAIR_HARNESS_DIALOGUE_API_KEY"


def _reasonix_config_toml(
    *, kind: ProviderKind, base_url: str, model: str, effort: str
) -> str:
    """``REASONIX_HOME/config.toml`` 正文：一个 OpenAI 兼容供应商实例。

    Reasonix 的 ``kind = "openai"`` 即 OpenAI 兼容 ``/chat/completions``，
    供应商按 ``base_url`` 的 host 识别，实例 ``name`` 只是标签；
    ``default_model`` 接受 ``provider/model`` 形态。
    """
    instance = kind.value
    provider: dict[str, Any] = {
        "name": instance,
        "kind": "openai",
        "base_url": base_url,
        "model": model,
        "api_key_env": _reasonix_api_key_env(kind),
    }
    if kind is ProviderKind.DEEPSEEK:
        # DeepSeek 沿用实测上下文窗口；通用端点不写未证实的能力数字。
        provider["context_window"] = 1_000_000
    provider["effort"] = effort
    return tomli_w.dumps(
        {
            "default_model": f"{instance}/{model}",
            "providers": [provider],
            "tools": {"enabled": list(REASONIX_EXECUTION_TOOLS)},
        }
    )


def _atomic_write_text(path: Path, content: str) -> None:
    """同目录临时文件写入后原子替换。"""
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
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _write_reasonix_env(path: Path, key: str, value: str) -> None:
    """``.env`` 只放当前供应商的密钥变量；``value`` 为空时写空文件，内容未变时不改写。

    值由 python-dotenv 的 ``set_key`` 加单引号写出，换行留在引号内。Reasonix 用
    godotenv 读取，单引号值按原文取回；值含反斜杠或单引号时 godotenv 不还原
    ``set_key`` 加的转义。先写同目录临时文件，再原子替换。
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        if value:
            set_key(tmp_path, key, value)
        if path.exists() and path.read_bytes() == tmp_path.read_bytes():
            tmp_path.unlink()
        else:
            os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
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
    """为账号准备 ``REASONIX_HOME``（``config.toml`` 与 ``.env``），返回目录。

    Reasonix 只从 ``config.toml`` 读端点与模型，只从 ``<REASONIX_HOME>/.env``
    按 ``api_key_env`` 取密钥，不读进程环境里的这些值。目录按账号隔离
    （``base_dir/accounts/{account_id}/reasonix``），两个文件都经同目录临时
    文件原子替换。
    """
    home = codex_auth.base_dir / "accounts" / codex_auth.account_id / "reasonix"
    home.mkdir(parents=True, exist_ok=True)
    kind = detect_provider(base_url)
    effort = _normalize_reasonix_effort(base_url, model, reasoning_effort)
    toml = _reasonix_config_toml(
        kind=kind, base_url=base_url, model=model, effort=effort
    )
    config_path = home / "config.toml"
    if not config_path.exists() or config_path.read_text(encoding="utf-8") != toml:
        _atomic_write_text(config_path, toml)
    _write_reasonix_env(home / ".env", _reasonix_api_key_env(kind), api_key)
    return home


def _reasonix_executable() -> str:
    """reasonix 可执行文件：打包版由 Tauri 经 PAIR_HARNESS_BUNDLED_REASONIX_BIN 注入，
    源码运行可用 PAIR_HARNESS_REASONIX_BIN 指定，否则取 PATH 上的 reasonix。"""
    return (
        os.getenv("PAIR_HARNESS_BUNDLED_REASONIX_BIN")
        or os.getenv("PAIR_HARNESS_REASONIX_BIN")
        or "reasonix"
    )


def build_coding_engine(
    *,
    codex_auth: CodexAuthService,
    base_url: str,
    model: str,
    api_key: str,
    reasoning_effort: str = "auto",
    idle_timeout: float = 600.0,
    diagnostic_callback: DiagnosticCallback | None = None,
) -> AcpCodingEngine:
    """为 OpenAI Chat Completions 兼容端点构建编程助手引擎。

    端点只写进账号私有的 Reasonix 配置，装配期不建立连接；``base_url`` 与
    ``model`` 缺失时直接报错。``codex_auth`` 只用于定位账号目录。
    ``reasoning_effort`` 是账号级 ``dialogue.reasoning_effort``；``idle_timeout``
    是回合连续无事件后的空闲超时（秒）；``diagnostic_callback`` 接收引擎诊断
    告警（如回合无进展）。
    """
    if not base_url or not model:
        raise ValueError("编程助手需要对话服务的 Base URL 与模型")
    executable = _reasonix_executable()
    reasonix_home = ensure_reasonix_home(
        codex_auth,
        base_url=base_url,
        model=model,
        api_key=api_key,
        reasoning_effort=reasoning_effort,
    )
    engine_env = {"REASONIX_HOME": str(reasonix_home)}

    async def acp_connection() -> SubprocessJsonLineConnection:
        return await SubprocessJsonLineConnection.create(
            executable, args=["acp"], env=engine_env
        )

    return AcpCodingEngine(
        JsonlProcessTransport(acp_connection, request_timeout=3600.0),
        idle_timeout=idle_timeout,
        diagnostic_callback=diagnostic_callback,
    )
