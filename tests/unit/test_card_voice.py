from __future__ import annotations

import asyncio
import base64
import io
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pair_harness.voice_models import (
    VOICE_ENROLLMENT_ACTION,
    VOICE_ENROLLMENT_MODEL,
    VOICE_TTS_MODEL,
)
from tests.fixtures.replay_http import ReplayHttpServer
from tests.service_helpers import call, expect_service_error, wait_until

API_KEY = "sk-test-voice-0001"
CUSTOMIZATION_PATH = "/api/v1/services/audio/tts/customization"


# DashScope 音色定制接口的成功与失败回执形状。
def _voice_created(server: ReplayHttpServer, voice_id: str) -> None:
    server.reply(
        CUSTOMIZATION_PATH,
        200,
        {"output": {"voice_id": voice_id}, "usage": {"count": 1}, "request_id": "req-ok"},
    )


def _rejected(server: ReplayHttpServer, message: str) -> None:
    server.reply(
        CUSTOMIZATION_PATH,
        400,
        {"request_id": "req-bad", "code": "InvalidParameter", "message": message},
    )


class SpeakerRecorder:
    """本机扬声器运行时的记录替身，经 attach_voice_runtime 注入。

    真实 VoiceRuntime 驱动麦克风、扬声器与 DashScope 流式合成，这里只记录
    试听入队与语音焦点切换。
    """

    speech_queue_len = 0

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str | None]] = []
        self.contexts: list[tuple[str, Any]] = []

    def enqueue_text(self, text: str, *, voice_id: str | None = None) -> None:
        self.enqueued.append((text, voice_id))

    async def set_context_async(self, conversation_id: str, pair_config: Any) -> None:
        self.contexts.append((conversation_id, pair_config))

    def on_message(self, message: Any) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def _write_wav(path: Path, *, seconds: float, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    path.write_bytes(buffer.getvalue())
    return buffer.getvalue()


async def _configure_voice(service, server: ReplayHttpServer) -> None:
    await call(
        service,
        "config",
        "config.set",
        updates={"voice.api_key": API_KEY, "voice.base_url": f"{server.base_url}/api/v1"},
    )


async def _card_with_reference(service, name: str) -> tuple[str, bytes]:
    card_id = (await call(service, "draft", "card.create_draft", name=name))["card_id"]
    path = service.tmp_path / "reference.wav"
    wav = _write_wav(path, seconds=1.0)
    await call(service, "bind", "voice.card_bind_reference", card_id=card_id, path=str(path))
    return card_id, wav


async def _publish_card(service, name: str) -> str:
    """发布一张卡：进入可选搭档目录并自动绑定默认搭档。"""
    card_id = (await call(service, "pub-draft", "card.create_draft", name=name))["card_id"]
    await call(
        service,
        "pub-update",
        "card.update",
        card_id=card_id,
        card={"name": name, "first_mes": "你好"},
    )
    await call(service, "pub", "card.publish", card_id=card_id)
    return card_id


async def _catalog_card(service, name: str) -> str:
    """目录内的卡：已发布并绑定参考音频。"""
    card_id = await _publish_card(service, name)
    path = service.tmp_path / f"{name}.wav"
    _write_wav(path, seconds=1.0)
    await call(
        service,
        "catalog-bind",
        "voice.card_bind_reference",
        card_id=card_id,
        path=str(path),
    )
    return card_id


def _catalog_option(pairs: list[dict[str, Any]], card_id: str) -> dict[str, Any]:
    """目录项按角色卡 id 取回。"""
    return next(item for item in pairs if item["character_card_id"] == card_id)


def _profile(service, card_id: str):
    return service.card_repository.get_card(card_id).card.hsr.voice_profile


def _provision_events(service, card_id: str) -> list[dict[str, Any]]:
    return [
        event
        for event in service.event_log.payloads("voice.card_provision_changed")
        if event["card_id"] == card_id
    ]


# ---------------------------------------------------------------- 参考音频


@pytest.mark.parametrize(
    ("file_name", "write", "contains"),
    [
        pytest.param(
            "note.txt", lambda p: p.write_text("不是音频", encoding="utf-8"), None,
            id="不支持的扩展名",
        ),
        pytest.param(
            "big.wav", lambda p: p.write_bytes(b"\x00" * (10 * 1024 * 1024 + 1)), None,
            id="超过10MB",
        ),
        pytest.param(
            "long.wav", lambda p: _write_wav(p, seconds=61, rate=8000), "60",
            id="WAV超过60秒",
        ),
    ],
)
async def test_bind_reference_rejects_invalid_audio(
    service, file_name: str, write: Callable[[Path], object], contains: str | None
) -> None:
    card_id = (await call(service, "1", "card.create_draft", name="参考音频角色"))["card_id"]
    path = service.tmp_path / file_name
    write(path)
    await expect_service_error(
        lambda: call(service, "2", "voice.card_bind_reference", card_id=card_id, path=str(path)),
        "voice_reference_invalid",
        contains=contains,
    )


async def test_bind_reference_stores_wav_asset(service) -> None:
    card_id = (await call(service, "1", "card.create_draft", name="参考音频角色"))["card_id"]
    path = service.tmp_path / "ok.wav"
    wav = _write_wav(path, seconds=1.0)

    bound = await call(service, "2", "voice.card_bind_reference", card_id=card_id, path=str(path))
    assert bound["card_id"] == card_id
    assert bound["duration_seconds"] == pytest.approx(1.0)
    assert bound["size_bytes"] == len(wav)
    assert bound["mime_type"] == "audio/wav"
    assert _profile(service, card_id).reference_audio_asset == bound["asset_id"]


# ---------------------------------------------------------------- 创建音色


async def test_card_create_without_voice_credentials_reports_not_configured(service) -> None:
    card_id = (await call(service, "1", "card.create_draft", name="无Key角色"))["card_id"]
    await expect_service_error(
        lambda: call(service, "2", "voice.card_create", card_id=card_id, mode="clone"),
        "voice_not_configured",
    )


async def test_clone_without_bound_reference_reports_missing(service, replay_http) -> None:
    await _configure_voice(service, replay_http)
    card_id = (await call(service, "1", "card.create_draft", name="未绑音频"))["card_id"]
    await expect_service_error(
        lambda: call(service, "2", "voice.card_create", card_id=card_id, mode="clone"),
        "voice_reference_missing",
    )
    assert replay_http.requests == []


async def test_clone_creates_voice_from_reference_audio(service, replay_http) -> None:
    await _configure_voice(service, replay_http)
    card_id, wav = await _card_with_reference(service, "克隆角色")
    _voice_created(replay_http, "qwen-audio-3.0-tts-flash-card-0001")

    result = await call(service, "1", "voice.card_create", card_id=card_id, mode="clone")
    assert result == {
        "card_id": card_id,
        "state": "voice_ready",
        "voice_id": "qwen-audio-3.0-tts-flash-card-0001",
    }
    # 账号 Key 与参考音频 data URI 发往 customization 接口；中文卡名的 prefix 缺省为 card。
    [request] = replay_http.requests
    assert request.path == CUSTOMIZATION_PATH
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert request.body == {
        "model": VOICE_ENROLLMENT_MODEL,
        "input": {
            "action": VOICE_ENROLLMENT_ACTION,
            "target_model": VOICE_TTS_MODEL,
            "prefix": "card",
            "url": "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii"),
        },
    }
    profile = _profile(service, card_id)
    assert (profile.state, profile.voice_id, profile.creation_mode) == (
        "voice_ready",
        "qwen-audio-3.0-tts-flash-card-0001",
        "clone",
    )
    assert [(e["state"], e["voice_id"]) for e in _provision_events(service, card_id)] == [
        ("voice_creating", None),
        ("voice_ready", "qwen-audio-3.0-tts-flash-card-0001"),
    ]

    # 重新绑定参考音频不影响已就绪的音色，重新创建前旧音色继续可用。
    _write_wav(service.tmp_path / "new.wav", seconds=0.5)
    await call(
        service,
        "2",
        "voice.card_bind_reference",
        card_id=card_id,
        path=str(service.tmp_path / "new.wav"),
    )
    profile = _profile(service, card_id)
    assert (profile.state, profile.voice_id) == (
        "voice_ready",
        "qwen-audio-3.0-tts-flash-card-0001",
    )


async def test_card_create_rejects_duplicate_while_in_progress(service, replay_http) -> None:
    await _configure_voice(service, replay_http)
    card_id, _ = await _card_with_reference(service, "并发角色")
    _voice_created(replay_http, "voice-concurrent")
    release = replay_http.hold(CUSTOMIZATION_PATH)

    first = asyncio.ensure_future(
        call(service, "1", "voice.card_create", card_id=card_id, mode="clone")
    )
    await wait_until(lambda: len(replay_http.requests) == 1)
    await expect_service_error(
        lambda: call(service, "2", "voice.card_create", card_id=card_id, mode="clone"),
        "voice_card_provision_in_progress",
    )
    release.set()
    assert (await first)["state"] == "voice_ready"
    assert len(replay_http.requests) == 1


async def test_card_create_failure_keeps_previous_voice_id(service, replay_http) -> None:
    await _configure_voice(service, replay_http)
    card_id = (await call(service, "1", "card.create_draft", name="失败保留"))["card_id"]
    service.card_repository.update_voice_profile(
        card_id, state="voice_ready", voice_id="old-voice-id", creation_mode="design"
    )
    _rejected(replay_http, "voice_prompt is not supported")

    await expect_service_error(
        lambda: call(
            service,
            "2",
            "voice.card_create",
            card_id=card_id,
            mode="design",
            voice_prompt="低沉而温暖的少年音",
        ),
        "voice_card_create_failed",
        contains="InvalidParameter: voice_prompt is not supported",
    )
    design_input = replay_http.requests[0].body["input"]
    assert design_input["voice_prompt"] == "低沉而温暖的少年音"
    # DashScope 拒绝少于 15 字符的 preview_text。
    assert len(design_input["preview_text"]) >= 15

    profile = _profile(service, card_id)
    assert profile.state == "voice_failed"
    assert "voice_prompt is not supported" in profile.last_error
    assert profile.voice_id == "old-voice-id"
    events = _provision_events(service, card_id)
    assert [(e["state"], e["voice_id"]) for e in events] == [
        ("voice_creating", None),
        ("voice_failed", "old-voice-id"),
    ]
    assert "voice_prompt is not supported" in events[1]["error"]


async def test_card_create_failure_reports_http_status_once(service, replay_http) -> None:
    await _configure_voice(service, replay_http)
    card_id, _ = await _card_with_reference(service, "状态码角色")
    _rejected(replay_http, "audio is too short")

    error = await expect_service_error(
        lambda: call(service, "1", "voice.card_create", card_id=card_id, mode="clone"),
        "voice_card_create_failed",
    )
    expected = "HTTP 400 DashScope 错误 InvalidParameter: audio is too short"
    assert str(error) == expected
    assert _profile(service, card_id).last_error == expected


async def test_unbind_resets_voice_and_keeps_reference(service, replay_http) -> None:
    await _configure_voice(service, replay_http)
    card_id, _ = await _card_with_reference(service, "解绑角色")
    _voice_created(replay_http, "voice-to-unbind")
    await call(service, "1", "voice.card_create", card_id=card_id, mode="clone")

    unbound = await call(service, "2", "voice.card_unbind", card_id=card_id)
    assert unbound == {"card_id": card_id, "state": "voice_unconfigured"}
    profile = _profile(service, card_id)
    assert (profile.voice_id, profile.creation_mode) == ("", "")
    kinds = [a.kind for a in service.asset_service.list_assets_for_card(card_id)]
    assert kinds == ["reference_audio"]


# ---------------------------------------------------------------- 目录事件


async def test_catalog_card_reference_binding_broadcasts_card_updated(service) -> None:
    """绑定参考音频改变卡资料：推进目录版本并只发 card.updated。"""
    card_id = await _publish_card(service, "参考音角色")
    service.event_log.items.clear()
    path = service.tmp_path / "reference-only.wav"
    _write_wav(path, seconds=1.0)

    await call(
        service, "1", "voice.card_bind_reference", card_id=card_id, path=str(path)
    )

    [event] = service.event_log.payloads("card.updated")
    assert event["card_id"] == card_id
    assert service.event_log.payloads("pair.updated") == []
    listing = await call(service, "2", "pair.list")
    assert listing["catalog_version"] == event["catalog_version"]


async def test_catalog_card_voice_lifecycle_broadcasts_card_updated(
    service, replay_http
) -> None:
    """目录内建卡音色：creating、ready 与解绑三次落库各推进一次目录版本。"""
    await _configure_voice(service, replay_http)
    card_id = await _catalog_card(service, "目录音色角色")
    _voice_created(replay_http, "catalog-voice-01")
    service.event_log.items.clear()

    await call(service, "1", "voice.card_create", card_id=card_id, mode="clone")

    events = service.event_log.payloads("card.updated")
    assert [event["card_id"] for event in events] == [card_id, card_id]
    versions = [event["catalog_version"] for event in events]
    assert versions[0] < versions[1]
    assert service.event_log.payloads("pair.updated") == []

    listing = await call(service, "2", "pair.list")
    assert listing["catalog_version"] == versions[-1]
    assert _catalog_option(listing["pairs"], card_id)["character"]["voice_id"] == (
        "catalog-voice-01"
    )

    await call(service, "3", "voice.card_unbind", card_id=card_id)

    unbound = service.event_log.payloads("card.updated")[-1]
    assert unbound["catalog_version"] > versions[-1]
    listing = await call(service, "4", "pair.list")
    assert listing["catalog_version"] == unbound["catalog_version"]
    assert _catalog_option(listing["pairs"], card_id)["character"]["voice_id"] == ""


async def test_catalog_card_voice_failure_clears_catalog_voice(
    service, replay_http
) -> None:
    """失败回调落 voice_failed 时目录里的 voice_id 随状态清空。"""
    await _configure_voice(service, replay_http)
    card_id = await _catalog_card(service, "失败音色角色")
    _voice_created(replay_http, "before-failure")
    await call(service, "1", "voice.card_create", card_id=card_id, mode="clone")
    ready = await call(service, "2", "pair.list")
    assert _catalog_option(ready["pairs"], card_id)["character"]["voice_id"] == (
        "before-failure"
    )
    service.event_log.items.clear()

    _rejected(replay_http, "audio is too short")
    await expect_service_error(
        lambda: call(service, "3", "voice.card_create", card_id=card_id, mode="clone"),
        "voice_card_create_failed",
    )

    events = service.event_log.payloads("card.updated")
    assert [event["card_id"] for event in events] == [card_id, card_id]
    assert events[0]["catalog_version"] < events[1]["catalog_version"]
    listing = await call(service, "4", "pair.list")
    assert listing["catalog_version"] == events[-1]["catalog_version"]
    assert _catalog_option(listing["pairs"], card_id)["character"]["voice_id"] == ""


async def test_draft_card_voice_changes_emit_no_catalog_event(service, replay_http) -> None:
    """不在目录内的卡改音色不发事件、不动目录版本。"""
    await _configure_voice(service, replay_http)
    card_id, _ = await _card_with_reference(service, "草稿音色角色")
    _voice_created(replay_http, "draft-voice")
    before = (await call(service, "0", "pair.list"))["catalog_version"]
    service.event_log.items.clear()

    await call(service, "1", "voice.card_create", card_id=card_id, mode="clone")
    await call(service, "2", "voice.card_unbind", card_id=card_id)

    assert service.event_log.payloads("card.updated") == []
    assert service.event_log.payloads("pair.updated") == []
    assert (await call(service, "3", "pair.list"))["catalog_version"] == before


# ---------------------------------------------------------------- 播放


async def test_card_preview_requires_runtime_and_ready_voice(service) -> None:
    card_id = (await call(service, "1", "card.create_draft", name="试听角色"))["card_id"]
    # 演示服务没有语音运行时。
    await expect_service_error(
        lambda: call(service, "2", "voice.card_preview", card_id=card_id), "voice_unavailable"
    )

    speaker = SpeakerRecorder()
    service.attach_voice_runtime(speaker)
    await expect_service_error(
        lambda: call(service, "3", "voice.card_preview", card_id=card_id),
        "voice_card_not_ready",
    )

    service.card_repository.update_voice_profile(
        card_id, state="voice_ready", voice_id="ready-vid-42"
    )
    result = await call(service, "4", "voice.card_preview", card_id=card_id, text="晚上好呀")
    assert isinstance(result["voice"], dict)
    assert speaker.enqueued == [("晚上好呀", "ready-vid-42")]


async def test_card_voice_applies_only_to_bound_conversation(service) -> None:
    speaker = SpeakerRecorder()
    service.attach_voice_runtime(speaker)
    unbound_id = service.current_conversation_id
    card_id = (await call(service, "1", "card.create_draft", name="覆盖角色"))["card_id"]
    await call(
        service,
        "2",
        "card.update",
        card_id=card_id,
        card={"name": "覆盖角色", "first_mes": "你好"},
    )
    await call(service, "3", "card.publish", card_id=card_id)
    service.card_repository.update_voice_profile(
        card_id, state="voice_ready", voice_id="card-voice-01"
    )
    binding = service.binding_repository.find_binding(card_id, "phainon_ancient_machine")
    assert binding is not None

    # 进入聊天时语音焦点切到该聊天的有效搭档音色。
    await call(service, "4", "conversation.create", binding_id=binding.binding_id)
    bound_id, bound_pair = speaker.contexts[-1]
    await call(service, "5", "conversation.select", conversation_id=unbound_id)
    focused_id, unbound_pair = speaker.contexts[-1]

    assert bound_id != unbound_id
    assert service.store.get_conversation(bound_id).character_card_id == card_id
    assert bound_pair.character.voice_id == "card-voice-01"
    assert focused_id == unbound_id
    assert unbound_pair.character.voice_id != "card-voice-01"
    # 卡音色只覆盖角色侧。
    assert bound_pair.assistant.voice_id == unbound_pair.assistant.voice_id
