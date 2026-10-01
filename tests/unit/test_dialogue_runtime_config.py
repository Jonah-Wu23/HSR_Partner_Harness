from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pair_harness.adapters.acp.engine import AcpCodingEngine
from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import EngineSessionRef
from pair_harness.desktop_backend.application_service import (
    build_configured_service,
    build_demo_service,
)
from tests.service_helpers import EventLog, call, expect_service_error

ACCOUNT_ID = "default-local"
COMPLETIONS_PATH = "/v1/chat/completions"

# OpenAI 兼容端点的 Chat Completions 成功响应与 Key 无效时的错误响应。
CHAT_COMPLETION = {
    "id": "chatcmpl-probe",
    "object": "chat.completion",
    "created": 1759300000,
    "model": "compat-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "p"},
            "finish_reason": "length",
        }
    ],
    "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9},
}
INVALID_KEY_ERROR = {
    "error": {
        "message": "Incorrect API key provided",
        "type": "invalid_request_error",
        "param": None,
        "code": "invalid_api_key",
    }
}


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实模式会用环境变量补默认端点、密钥和语音 Key，清掉开发机上的值。"""
    for name in (
        "PAIR_HARNESS_DIALOGUE_BASE_URL",
        "PAIR_HARNESS_DIALOGUE_API_KEY",
        "PAIR_HARNESS_DIALOGUE_MODEL",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _database(tmp_path: Path) -> Path:
    return tmp_path / "data" / "pair_harness.db"


def _real_service(tmp_path: Path, log: EventLog | None = None):
    return build_configured_service(
        database=_database(tmp_path),
        project_root=tmp_path,
        event_sink=log or EventLog(),
        demo=False,
    )


async def _seed_config(tmp_path: Path, configs: dict[str, str]) -> None:
    """直接写入账号配置，构造 config.set 已不再接受的历史值。"""
    service = build_demo_service(database=_database(tmp_path), project_root=tmp_path)
    try:
        service.store.set_configs_and_secrets(ACCOUNT_ID, configs, {})
    finally:
        await service.shutdown()


def _endpoint(base_url: str, *, api_key: str | None = "sk-probe") -> dict[str, str]:
    updates = {
        "dialogue.provider": "openai_compatible",
        "dialogue.base_url": f"{base_url}/v1",
        "dialogue.model": "compat-model",
    }
    if api_key is not None:
        updates["dialogue.api_key"] = api_key
    return updates


async def test_unknown_dns_endpoint_starts_into_configurable_state(tmp_path: Path) -> None:
    """端点只写进账号的 Reasonix 配置，启动期不解析也不连接它。"""
    await _seed_config(
        tmp_path,
        {
            "dialogue.provider": "openai_compatible",
            "dialogue.base_url": "https://no-such-host-s4.invalid/v1",
            "dialogue.model": "compat-model",
            "engine": "reasonix",
        },
    )
    log = EventLog()
    service = _real_service(tmp_path, log)
    try:
        assert isinstance(service.coding_engine, AcpCodingEngine)
        config = await call(service, "get-1", "config.get")
        assert config["dialogue"]["provider"] == "openai_compatible"
        assert config["dialogue"]["provider_supported"] is True
        assert config["dialogue"]["base_url"] == "https://no-such-host-s4.invalid/v1"
        assert config["engine"] == "reasonix"
        home = tmp_path / "data" / "accounts" / ACCOUNT_ID / "reasonix"
        config_text = (home / "config.toml").read_text(encoding="utf-8")
        assert 'base_url = "https://no-such-host-s4.invalid/v1"' in config_text
        assert 'model = "compat-model"' in config_text
        assert [p for p in log.payloads("error.reported") if p["fatal"]] == []
    finally:
        await service.shutdown()


async def test_stored_oauth_config_starts_with_locatable_notice(tmp_path: Path) -> None:
    """历史 openai_oauth 与 engine=codex 配置原样保留，启动期发非致命提示。"""
    await _seed_config(
        tmp_path,
        {
            "dialogue.provider": "openai_oauth",
            "dialogue.base_url": "https://api.openai.com/v1",
            "dialogue.model": "gpt-5.6-sol",
            "engine": "codex",
        },
    )
    log = EventLog()
    service = _real_service(tmp_path, log)
    try:
        notices = {
            payload["code"]: payload for payload in log.payloads("error.reported")
        }
        for code in ("provider_unavailable", "engine_removed"):
            assert notices[code]["severity"] == "recoverable"
            assert notices[code]["fatal"] is False
            assert notices[code]["source"] == "sidecar"
            assert notices[code]["message"]

        config = await call(service, "get-1", "config.get")
        assert config["dialogue"]["provider"] == "openai_oauth"
        assert config["dialogue"]["provider_supported"] is False
        assert config["dialogue"]["provider_unavailable"]["code"] == "provider_unavailable"
        assert config["engine"] == "reasonix"
        assert service.store.get_config(ACCOUNT_ID, "dialogue.provider") == "openai_oauth"
        assert service.store.get_config(ACCOUNT_ID, "engine") == "codex"
    finally:
        await service.shutdown()


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        pytest.param(
            {
                "dialogue.provider": "openai oauth",
                "dialogue.base_url": "https://api.openai.com/v1",
                "dialogue.model": "gpt-5.6-sol",
            },
            "provider_unavailable",
            id="oauth-provider",
        ),
        pytest.param(
            {
                "dialogue.provider": "deepseek",
                "dialogue.base_url": "https://gateway.example.com/v1",
            },
            "provider_endpoint_mismatch",
            id="endpoint-mismatch",
        ),
        pytest.param(
            {
                "engine": "codex",
                "dialogue.provider": "deepseek",
                "dialogue.base_url": "https://api.deepseek.com",
            },
            "invalid_engine",
            id="legacy-engine",
        ),
    ],
)
async def test_rejected_config_set_keeps_saved_config(
    service, updates: dict[str, str], code: str
) -> None:
    """被拒绝的写入整次失败，账号已保存的配置保持原值。"""
    await call(
        service,
        "cfg-saved",
        "config.set",
        updates={
            "dialogue.provider": "deepseek",
            "dialogue.base_url": "https://api.deepseek.com",
            "dialogue.model": "deepseek-v4-flash",
            "dialogue.api_key": "sk-deepseek-test",
        },
    )
    before = await call(service, "get-before", "config.get")

    await expect_service_error(
        lambda: call(service, "cfg-rejected", "config.set", updates=updates), code
    )

    assert await call(service, "get-after", "config.get") == before
    assert service.store.get_config(ACCOUNT_ID, "engine") == "reasonix"
    assert service.store.get_secret(ACCOUNT_ID, "dialogue.api_key") == "sk-deepseek-test"


async def test_config_set_rebuilds_runtime_for_new_provider(tmp_path: Path) -> None:
    """保存新供应商后立即换入新的对话模型与编程助手，旧引擎会话失效。"""
    service = _real_service(tmp_path)
    try:
        conversation_id = service.current_conversation_id
        startup_model = service.dialogue_model
        assert isinstance(startup_model, OpenAICompatibleDialogueModel)
        # 角色卡装配经 resolver 进入对话模型，启动与每次重建都要挂上。
        assert startup_model.character_prompt_resolver == service._resolve_character_prompt
        service.store.save_engine_session(
            conversation_id,
            EngineSessionRef(
                engine_type=service.coding_engine.engine_type, opaque_ref="old-session"
            ),
        )

        await call(
            service,
            "cfg-compat",
            "config.set",
            updates={
                "dialogue.provider": "openai_compatible",
                "dialogue.base_url": "https://no-such-host-s4.invalid/v1",
                "dialogue.api_key": "sk-test",
                "dialogue.model": "gpt-5.6-sol",
            },
        )
        assert service.dialogue_model is not startup_model
        assert isinstance(service.coding_engine, AcpCodingEngine)
        assert service.store.load_conversation(conversation_id).engine_session is None

        await call(
            service,
            "cfg-deepseek",
            "config.set",
            updates={
                "dialogue.provider": "deepseek",
                "dialogue.base_url": "https://api.deepseek.com",
                "dialogue.api_key": "sk-deepseek-test",
                "dialogue.model": "deepseek-v4-flash",
                "dialogue.reasoning_effort": "max",
            },
        )
        assert service.dialogue_model.model == "deepseek-v4-flash"
        assert (
            service.dialogue_model.character_prompt_resolver
            == service._resolve_character_prompt
        )
        assert service.orchestrator.reviewer._model is service.dialogue_model
    finally:
        await service.shutdown()


async def test_config_set_rejects_failed_runtime_candidate_without_writing(
    tmp_path: Path,
) -> None:
    """候选运行时构建失败时整次保存被拒绝，原始错误随 config_rejected 返回。"""
    service = _real_service(tmp_path)
    try:
        # 账号的 Reasonix 配置目录被同名文件占用，候选引擎写不进配置。
        reasonix_home = tmp_path / "data" / "accounts" / ACCOUNT_ID / "reasonix"
        shutil.rmtree(reasonix_home)
        reasonix_home.write_text("", encoding="utf-8")

        await expect_service_error(
            lambda: call(
                service,
                "cfg-1",
                "config.set",
                updates={"dialogue.reasoning_effort": "high"},
            ),
            "config_rejected",
            contains="FileExistsError",
        )
        assert service.store.get_config(ACCOUNT_ID, "dialogue.reasoning_effort") is None
    finally:
        await service.shutdown()


async def test_cleared_api_key_blocks_environment_fallback(
    service, monkeypatch: pytest.MonkeyPatch
) -> None:
    """从未保存 Key 时用环境变量；用户显式清空后不再回落到环境变量。"""
    monkeypatch.setenv("PAIR_HARNESS_DIALOGUE_API_KEY", "sk-env-default")
    before = await call(service, "get-1", "config.get")
    assert before["dialogue"]["api_key_masked"] == "sk-e…ault"

    await call(service, "clear-key", "config.set", updates={"dialogue.api_key": ""})
    after = await call(service, "get-2", "config.get")
    assert after["dialogue"]["api_key_masked"] == ""


async def test_test_connection_probes_saved_endpoint_only_in_real_mode(
    tmp_path: Path, replay_http
) -> None:
    replay_http.reply(COMPLETIONS_PATH, 200, CHAT_COMPLETION)
    endpoint = _endpoint(replay_http.base_url)
    demo = build_demo_service(database=_database(tmp_path), project_root=tmp_path)
    try:
        await call(demo, "cfg-1", "config.set", updates=endpoint)
        result = await call(demo, "probe-demo", "config.test_connection")
        assert result["ok"] is False
        assert result["provider"] == "demo"
        assert "演示模式" in result["message"]
        assert replay_http.requests == []
    finally:
        await demo.shutdown()

    service = _real_service(tmp_path)
    try:
        result = await call(service, "probe-1", "config.test_connection")
        assert result["ok"] is True
        assert result["provider"] == "openai_compatible"
        assert result["base_url"] == endpoint["dialogue.base_url"]
        assert result["model"] == "compat-model"
        [request] = replay_http.requests
        assert request.path == COMPLETIONS_PATH
        assert request.headers["Authorization"] == "Bearer sk-probe"
        assert request.body["model"] == "compat-model"
    finally:
        await service.shutdown()


@pytest.mark.parametrize(
    ("failure", "prefix", "detail"),
    [
        pytest.param("missing_key", "缺少对话服务配置", "API Key", id="missing-key"),
        pytest.param(
            "invalid_key", "服务返回 401：", "Incorrect API key provided", id="http-401"
        ),
        pytest.param(
            "disconnect",
            "连接失败：",
            "Server disconnected without sending a response.",
            id="disconnect",
        ),
    ],
)
async def test_test_connection_reports_real_failure_reason(
    tmp_path: Path, replay_http, failure: str, prefix: str, detail: str
) -> None:
    if failure == "invalid_key":
        replay_http.reply(COMPLETIONS_PATH, 401, INVALID_KEY_ERROR)
    elif failure == "disconnect":
        replay_http.disconnect(COMPLETIONS_PATH)
    service = _real_service(tmp_path)
    try:
        await call(
            service,
            "cfg-1",
            "config.set",
            updates=_endpoint(
                replay_http.base_url,
                api_key=None if failure == "missing_key" else "sk-probe",
            ),
        )
        result = await call(service, "probe-1", "config.test_connection")
        assert result["ok"] is False
        assert result["message"].startswith(prefix)
        assert detail in result["message"]
    finally:
        await service.shutdown()


async def test_stored_oauth_config_test_connection_fails_without_probing(
    tmp_path: Path, replay_http
) -> None:
    await _seed_config(
        tmp_path,
        {
            "dialogue.provider": "openai_oauth",
            "dialogue.base_url": f"{replay_http.base_url}/v1",
            "dialogue.model": "gpt-5.6-sol",
        },
    )
    service = _real_service(tmp_path)
    try:
        result = await call(service, "probe-1", "config.test_connection")
        assert result["ok"] is False
        assert result["provider"] == "openai_oauth"
        assert result["provider_supported"] is False
        assert "不受支持" in result["message"]
        assert replay_http.requests == []
    finally:
        await service.shutdown()
