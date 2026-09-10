"""B-03（V0.3.9）：产品只支持 OpenAI Chat Completions 兼容端点。

复测证据 evidence/retest-20260910/B-03/result.json 的负向三条全部失败：
(1) ``_require_responses_backend`` 仍在校验 Responses 后端；
(2) 供应商切换仍被 Responses 拒绝；
(3) OpenAI OAuth 入口仍可选。
本文件覆盖修复后的离线行为：

- 任意 http(s) 端点（含不可解析域名）都装配 reasonix ACP 引擎，端点真实
  写入账号私有的 Reasonix 配置，装配期不联网、不校验端点可达性；
- 供应商切换不再因 Responses 被拒；engine 由后端推导（恒为 reasonix），
  客户端发来的旧值按可定位 invalid_engine 拒绝；
- OpenAI OAuth 供应商不能被写入（provider_unavailable），OAuth 登录命令
  一律 codex_login_removed，且不写配置、不启动登录进程；
- 历史账号配置（openai_oauth / engine=codex）不静默改写、不导致启动期退出：
  启动期发非致命 error.reported，应用仍可进入设置页重新配置。

全部断言离线完成：不联网、不启动 reasonix 子进程、不调用真实模型。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pair_harness.adapters.acp.engine import AcpCodingEngine
from pair_harness.adapters.demo import ScriptedCodingEngine
from pair_harness.desktop_backend.application_service import (
    ServiceError,
    _build_service,
    build_demo_service,
)
from pair_harness.desktop_backend.commands import DesktopCommand

ACCOUNT_ID = "default-local"


class EventLog:
    """事件订阅器（event_sink）：按事件名过滤 payload。"""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def __call__(self, envelope: dict[str, Any]) -> None:
        self.items.append(envelope)

    def payloads(self, event: str) -> list[dict[str, Any]]:
        return [item["payload"] for item in self.items if item["event"] == event]


def command(request_id: str, method: str, **params: Any) -> DesktopCommand:
    return DesktopCommand(request_id=request_id, method=method, params=params)


def _isolate_dialogue_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉开发机环境，避免 .env/进程环境把测试端点混进来。"""
    for name in (
        "PAIR_HARNESS_DIALOGUE_BASE_URL",
        "PAIR_HARNESS_DIALOGUE_API_KEY",
        "PAIR_HARNESS_DIALOGUE_MODEL",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


async def _seed_config(
    database: Path, project_root: Path, configs: dict[str, str]
) -> None:
    """直接写入账号配置（用于构造历史遗留值，绕过 config.set 的校验）。"""
    service = build_demo_service(database=database, project_root=project_root)
    try:
        service.store.set_configs_and_secrets(ACCOUNT_ID, configs, {})
    finally:
        await service.shutdown()


async def _start_real_service(
    database: Path, project_root: Path, events: EventLog
):
    service = _build_service(
        database=database,
        project_root=project_root,
        pair_id="phainon_ancient_machine",
        event_sink=events,
        demo=False,
    )
    service.event_log = events  # type: ignore[attr-defined]
    return service


async def test_unknown_dns_endpoint_starts_into_configurable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-01 名称解析形态的前提：不可解析端点不再让 Sidecar 启动期失败。

    B-03 之前：非 openai.com 端点 × codex 引擎在装配层抛
    「codex 引擎要求 Responses API 后端」，候选无法启动。
    现在：端点只写进 Reasonix 配置，应用启动进入可用配置态。
    """
    _isolate_dialogue_env(monkeypatch)
    database = tmp_path / "data" / "pair_harness.db"
    await _seed_config(
        database,
        tmp_path,
        {
            "dialogue.provider": "openai_compatible",
            "dialogue.base_url": "https://no-such-host-s4.invalid/v1",
            "dialogue.model": "compat-model",
            "engine": "reasonix",
        },
    )
    events = EventLog()
    service = await _start_real_service(database, tmp_path, events)
    try:
        assert isinstance(service.coding_engine, AcpCodingEngine)
        assert isinstance(service.orchestrator.coding_engine, AcpCodingEngine)
        config = await service.handle_command(command("get-1", "config.get"))
        assert config["dialogue"]["provider"] == "openai_compatible"
        assert config["dialogue"]["provider_supported"] is True
        assert config["dialogue"]["base_url"] == "https://no-such-host-s4.invalid/v1"
        assert config["engine"] == "reasonix"

        # 端点必须真的写进账号私有的 Reasonix 配置（而不是删校验后走别的引擎）。
        home = (
            database.parent / "accounts" / ACCOUNT_ID / "reasonix"
        )
        config_text = (home / "config.toml").read_text(encoding="utf-8")
        assert 'base_url = "https://no-such-host-s4.invalid/v1"' in config_text
        assert 'model = "compat-model"' in config_text
        assert 'kind = "openai"' in config_text
        # 启动期不因端点可达性报致命错误。
        assert [
            payload
            for payload in events.payloads("error.reported")
            if payload.get("fatal")
        ] == []
    finally:
        await service.shutdown()


async def test_stored_oauth_config_starts_with_locatable_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """历史 openai_oauth / engine=codex 配置：不改写、不退出，只如实提示。"""
    _isolate_dialogue_env(monkeypatch)
    database = tmp_path / "data" / "pair_harness.db"
    legacy = {
        "dialogue.provider": "openai_oauth",
        "dialogue.base_url": "https://api.openai.com/v1",
        "dialogue.model": "gpt-5.6-sol",
        "engine": "codex",
    }
    await _seed_config(database, tmp_path, legacy)
    events = EventLog()
    service = await _start_real_service(database, tmp_path, events)
    try:
        notices = events.payloads("error.reported")
        codes = {payload["code"] for payload in notices}
        assert {"provider_unavailable", "engine_removed"} <= codes
        for payload in notices:
            if payload["code"] in {"provider_unavailable", "engine_removed"}:
                # 非致命：应用仍可用，用户能进设置页修复。
                assert payload["severity"] == "recoverable"
                assert payload["fatal"] is False
                assert payload["source"] == "sidecar"
                assert payload["message"]

        config = await service.handle_command(command("get-1", "config.get"))
        # 存储值原样回显，不静默迁移。
        assert config["dialogue"]["provider"] == "openai_oauth"
        assert config["dialogue"]["provider_supported"] is False
        assert (
            config["dialogue"]["provider_unavailable"]["code"] == "provider_unavailable"
        )
        assert config["engine"] == "reasonix"

        # 未经用户显式选择前，数据库里的旧值一字不动。
        assert (
            service.store.get_config(ACCOUNT_ID, "dialogue.provider") == "openai_oauth"
        )
        assert service.store.get_config(ACCOUNT_ID, "engine") == "codex"
    finally:
        await service.shutdown()


async def test_stored_oauth_test_connection_fails_without_probing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """历史 OAuth 配置绝不再给出「连接正常」，也不向该端点发探测请求。"""
    _isolate_dialogue_env(monkeypatch)
    database = tmp_path / "data" / "pair_harness.db"
    await _seed_config(
        database,
        tmp_path,
        {
            "dialogue.provider": "openai_oauth",
            "dialogue.base_url": "https://api.openai.com/v1",
            "dialogue.model": "gpt-5.6-sol",
        },
    )
    events = EventLog()
    service = await _start_real_service(database, tmp_path, events)
    probed: list[tuple[str, str, str]] = []

    async def fake_probe(base_url: str, api_key: str, model: str) -> dict:
        probed.append((base_url, api_key, model))
        return {"ok": True, "message": "连接正常（不应出现）"}

    monkeypatch.setattr(service, "_probe_dialogue_connection", fake_probe)
    try:
        result = await service.handle_command(command("probe-1", "config.test_connection"))
        assert result["ok"] is False
        assert result["provider"] == "openai_oauth"
        assert result["provider_supported"] is False
        assert "不受支持" in result["message"]
        assert probed == [], "不受支持的供应商不得发起真实探测"
    finally:
        await service.shutdown()


async def test_provider_switch_is_no_longer_rejected_by_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """供应商切换不再因 Responses 被拒：通用端点在真实模式下也能落盘生效。"""
    _isolate_dialogue_env(monkeypatch)
    events = EventLog()
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events,
    )
    probed: list[tuple[str, str, str]] = []

    async def fake_probe(base_url: str, api_key: str, model: str) -> dict:
        probed.append((base_url, api_key, model))
        return {"ok": True, "message": "连接正常（延迟 1 ms）"}

    monkeypatch.setattr(service, "_probe_dialogue_connection", fake_probe)
    try:
        service._demo = False
        result = await service.handle_command(
            command(
                "switch-1",
                "config.set",
                updates={
                    "dialogue.provider": "openai_compatible",
                    "dialogue.base_url": "https://no-such-host-s4.invalid/v1",
                    "dialogue.model": "compat-model",
                    "dialogue.api_key": "sk-compat",
                },
            )
        )
        assert result["config"]["dialogue"]["provider"] == "openai_compatible"
        assert result["config"]["engine"] == "reasonix"
        assert isinstance(service.coding_engine, AcpCodingEngine)

        probe = await service.handle_command(command("probe-1", "config.test_connection"))
        assert probe["provider"] == "openai_compatible"
        assert probe["base_url"] == "https://no-such-host-s4.invalid/v1"
        assert probed == [("https://no-such-host-s4.invalid/v1", "sk-compat", "compat-model")]
    finally:
        service._demo = True
        await service.shutdown()


async def test_legacy_engine_value_is_rejected_and_engine_is_derived(
    tmp_path: Path,
) -> None:
    """旧 engine 值按可定位错误拒绝；不发送 engine 时由后端推导。"""
    events = EventLog()
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events,
    )
    try:
        for legacy in ("codex", "deepseek"):
            with pytest.raises(ServiceError) as exc:
                await service.handle_command(
                    command(
                        "engine-legacy",
                        "config.set",
                        updates={
                            "engine": legacy,
                            "dialogue.provider": "deepseek",
                            "dialogue.base_url": "https://api.deepseek.com",
                            "dialogue.model": "deepseek-v4-flash",
                        },
                    )
                )
            assert exc.value.code == "invalid_engine"
            assert "reasonix" in str(exc.value)
        assert service.store.get_config(ACCOUNT_ID, "engine") is None

        accepted = await service.handle_command(
            command(
                "engine-ok",
                "config.set",
                updates={
                    "engine": "reasonix",
                    "dialogue.provider": "deepseek",
                    "dialogue.base_url": "https://api.deepseek.com",
                    "dialogue.model": "deepseek-v4-flash",
                },
            )
        )
        assert accepted["config"]["engine"] == "reasonix"
        assert service.store.get_config(ACCOUNT_ID, "engine") == "reasonix"
    finally:
        await service.shutdown()


async def test_supported_providers_report_supported_flag(tmp_path: Path) -> None:
    """受支持供应商（deepseek / openai_compatible）如实标注 supported。"""
    events: list[dict] = []
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=events.append,
    )
    try:
        for provider, base_url, model in (
            ("deepseek", "https://api.deepseek.com", "deepseek-v4-flash"),
            ("openai_compatible", "https://gateway.example.com/v1", "glm-4.6"),
        ):
            written = await service.handle_command(
                command(
                    f"set-{provider}",
                    "config.set",
                    updates={
                        "dialogue.provider": provider,
                        "dialogue.base_url": base_url,
                        "dialogue.model": model,
                        "dialogue.api_key": "sk-test",
                    },
                )
            )
            dialogue = written["config"]["dialogue"]
            assert dialogue["provider"] == provider
            assert dialogue["provider_supported"] is True
            assert dialogue["provider_unavailable"] is None
    finally:
        await service.shutdown()


async def test_demo_service_engine_is_still_scripted(tmp_path: Path) -> None:
    """演示模式接线不受影响（B-03 只改真实装配路径）。"""
    service = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
    )
    try:
        assert isinstance(service.coding_engine, ScriptedCodingEngine)
    finally:
        await service.shutdown()
