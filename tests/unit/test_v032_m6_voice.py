"""V0.3.2 M6 语音契约测试。

这些测试只覆盖本地 manifest、请求 payload、响应解析和错误映射；不访问
DashScope，也不把注入传输层的协议测试当成真实联调结果。
"""

from __future__ import annotations

import json

import pytest

from pair_harness.adapters.audio.qwen_voice_customization import (
    QwenVoiceCustomizationClient,
    VoiceCustomizationError,
    audio_file_to_data_uri,
    build_clone_payload,
    build_design_payload,
    extract_voice_id,
)
from pair_harness.config.voices import REFERENCE_SPEAKER_ORDER, load_reference_voice_manifest
from pair_harness.voice_models import VOICE_ASR_MODEL, VOICE_TTS_MODEL


def test_fixed_voice_models_and_manifest_order() -> None:
    manifest = load_reference_voice_manifest()

    assert VOICE_ASR_MODEL == "qwen-audio-3.0-asr-flash-streaming"
    assert VOICE_TTS_MODEL == "qwen-audio-3.0-tts-flash"
    assert tuple(entry.speaker_id for entry in manifest) == REFERENCE_SPEAKER_ORDER
    assert all(entry.target_model == VOICE_TTS_MODEL for entry in manifest)
    assert sum(entry.method == "clone" for entry in manifest) == 5
    assert sum(entry.method == "design" for entry in manifest) == 1


def test_clone_payload_accepts_remote_and_local_data_uri(tmp_path) -> None:
    payload = build_clone_payload(
        prefix="phainon",
        url="https://example.com/releases/voice-assets-v1/phainon.wav",
    )

    assert payload == {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": VOICE_TTS_MODEL,
            "prefix": "phainon",
            "url": "https://example.com/releases/voice-assets-v1/phainon.wav",
        },
    }
    local = tmp_path / "voice.wav"
    local.write_bytes(b"RIFF-test")
    data_uri = audio_file_to_data_uri(local)
    local_payload = build_clone_payload(prefix="phainon", url=data_uri)
    assert local_payload["input"]["url"] == data_uri
    with pytest.raises(VoiceCustomizationError, match=r"HTTP\(S\).+data:audio"):
        build_clone_payload(prefix="phainon", url=str(local))


def test_design_payload_uses_same_fixed_enrollment_contract() -> None:
    payload = build_design_payload(
        prefix="ancientmac",
        voice_prompt="神秘、低沉、带有机械共鸣的声音",
        preview_text="你好，我是神秘的古代机械。",
    )

    assert payload["model"] == "voice-enrollment"
    assert payload["input"] == {
        "action": "create_voice",
        "target_model": VOICE_TTS_MODEL,
        "prefix": "ancientmac",
        "voice_prompt": "神秘、低沉、带有机械共鸣的声音",
        "preview_text": "你好，我是神秘的古代机械。",
    }
    assert payload["parameters"] == {"sample_rate": 24000, "response_format": "wav"}


def test_customization_client_sends_auth_and_returns_server_voice_id() -> None:
    calls: list[tuple[str, dict[str, str], dict, float]] = []

    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float):
        calls.append((url, headers, json.loads(body), timeout))
        return 200, b'{"output":{"voice_id":"account-owned-voice-001"}}'

    client = QwenVoiceCustomizationClient(
        api_key="user-key-for-test",
        http_base_url="https://dashscope.example/api/v1",
        timeout=7.5,
        transport=transport,
    )
    result = client.create_cloned_voice(
        prefix="phainon",
        url="https://example.com/releases/voice-assets-v1/phainon.wav",
    )

    assert result.voice_id == "account-owned-voice-001"
    assert calls[0][0] == "https://dashscope.example/api/v1/services/audio/tts/customization"
    assert calls[0][1]["Authorization"] == "Bearer user-key-for-test"
    assert calls[0][2]["input"]["target_model"] == VOICE_TTS_MODEL
    assert calls[0][3] == 7.5


def test_customization_client_redacts_key_in_dashscope_error() -> None:
    def transport(url: str, headers: dict[str, str], body: bytes, timeout: float):
        del url, headers, body, timeout
        return 401, json.dumps(
            {
                "code": "InvalidApiKey",
                "message": "rejected user-key-for-test",
            }
        ).encode("utf-8")

    client = QwenVoiceCustomizationClient(
        api_key="user-key-for-test",
        http_base_url="https://dashscope.example/api/v1",
        transport=transport,
    )

    with pytest.raises(VoiceCustomizationError) as exc_info:
        client.create_designed_voice(
            prefix="ancientmac",
            voice_prompt="神秘机械",
            preview_text="你好",
        )

    assert "user-key-for-test" not in str(exc_info.value)
    assert "<REDACTED_API_KEY>" in str(exc_info.value)
    assert exc_info.value.http_status == 401
    assert exc_info.value.dashscope_code == "InvalidApiKey"


def test_extract_voice_id_does_not_invent_missing_result() -> None:
    with pytest.raises(VoiceCustomizationError, match="output.voice_id"):
        extract_voice_id({"output": {"status": "pending"}})
