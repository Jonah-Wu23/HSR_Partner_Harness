"""V0.3.5 服务级接线测试（契约：docs/plans/V0.3.5-契约冻结.md）。

覆盖域与契约章节对应：

1. 角色卡导入导出与发布（§2.1–§2.4）
2. 头像资产与随卡清理（§2.5/§2.6）
3. 卡音色状态机（§3，供应商边界注入假客户端）
4. 对话绑定角色卡与装配（§4）
5. 卡音色覆盖有效音色对（§3.4）
6. 审批仲裁与命令来源（§6）
7. 手机音频命令路由（§5，不连真实识别器）

mock 只允许出现在供应商边界（DashScope 音色定制客户端、ASR 识别器、
本地扬声器运行时）；存储层全部使用真实 SQLite 临时库与临时目录，
任何 await 都有超时护栏，挂起即失败暴露。
"""

from __future__ import annotations

import asyncio
import base64
import io
import threading
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import pair_harness.adapters.audio.qwen_voice_customization as qwen_voice_customization
from pair_harness.character_cards.models import HsrExtension, VoiceProfile
from pair_harness.core.contracts import ApprovalDecision, PendingOperation
from pair_harness.desktop_backend.application_service import (
    ServiceError,
    build_demo_service,
)
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.desktop_backend.mobile_audio import MobileAudioError


# ---------------------------------------------------------------- 基础设施

DEFAULT_TIMEOUT_S = 5.0

FIXTURE_CARD = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "character_cards"
    / "白厄（3.4前）.json"
)


def command(
    request_id: str, method: str, *, origin: str = "desktop", **params: Any
) -> DesktopCommand:
    return DesktopCommand(
        request_id=request_id, method=method, params=params, origin=origin
    )


async def call(
    service,
    request_id: str,
    method: str,
    *,
    origin: str = "desktop",
    timeout: float = DEFAULT_TIMEOUT_S,
    **params: Any,
) -> Any:
    """带超时的命令调用；意外挂起在超时后如实失败，不静默等待。"""
    return await asyncio.wait_for(
        service.handle_command(command(request_id, method, origin=origin, **params)),
        timeout=timeout,
    )


async def expect_service_error(
    action: Callable[[], Any],
    code: str,
    *,
    contains: str | None = None,
) -> ServiceError:
    with pytest.raises(ServiceError) as excinfo:
        await action()
    assert excinfo.value.code == code, str(excinfo.value)
    if contains is not None:
        assert contains in str(excinfo.value)
    return excinfo.value


async def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    interval: float = 0.01,
) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(interval)

    await asyncio.wait_for(poll(), timeout)


class EventLog:
    """事件订阅器（event_sink）：按事件名过滤 payload。"""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def __call__(self, envelope: dict[str, Any]) -> None:
        self.items.append(envelope)

    def payloads(self, event: str) -> list[dict[str, Any]]:
        return [item["payload"] for item in self.items if item["event"] == event]


@pytest.fixture
def service(tmp_path: Path):
    log = EventLog()
    svc = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=log,
    )
    svc.event_log = log
    svc.tmp_path = tmp_path
    yield svc
    svc.store.close()


def asset_dir(service) -> Path:
    return service.store.database.parent / "character_assets"


def write_min_png(path: Path, filler: bytes = b"fake-png-body") -> None:
    """最小 PNG：魔数 + 任意内容即可通过 mime 魔数探测（image/png）。"""
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + filler)


def write_wav(path: Path, *, seconds: float = 1.0, rate: int = 16000) -> int:
    """构造最小合法 WAV（PCM s16le 单声道），返回文件字节数。"""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    data = buffer.getvalue()
    path.write_bytes(data)
    return len(data)


async def create_published_card(
    service,
    request_id: str,
    *,
    name: str,
    description: str = "",
    first_mes: str = "",
) -> str:
    created = await call(service, request_id + "-draft", "card.create_draft", name=name)
    card_id = created["card_id"]
    await call(
        service,
        request_id + "-update",
        "card.update",
        card_id=card_id,
        card={"name": name, "description": description, "first_mes": first_mes},
    )
    published = await call(service, request_id + "-publish", "card.publish", card_id=card_id)
    assert published["state"] == "saved"
    return card_id


async def create_conversation_model(service, request_id: str, **params: Any):
    await call(
        service,
        request_id,
        "conversation.create",
        project_id=service.current_project_id,
        **params,
    )
    return service.store.get_conversation(service.current_conversation_id)


def grant_voice_credentials(service) -> None:
    """账号级语音凭据直接落库（config.set 会重建真实运行时，这里绕开）。"""
    account_id = service.current_account_id
    service.store.set_config(account_id, "voice.base_url", "https://dashscope.example.com")
    service.store.set_secret(account_id, "voice.api_key", "sk-test-key-0001")


def force_voice_profile(service, card_id: str, **updates: Any) -> None:
    """手工把卡的 voice_profile 置为给定字段值（绕过供应商流程）。"""
    record = service.card_repository.get_card(card_id)
    card = record.card
    if card.hsr is None:
        card.hsr = HsrExtension()
    if card.hsr.voice_profile is None:
        card.hsr.voice_profile = VoiceProfile()
    for key, value in updates.items():
        setattr(card.hsr.voice_profile, key, value)
    service.card_repository.update_card(card_id, card)


class RecordingVoiceRuntime:
    """本地扬声器运行时替身：只记录 enqueue_text 的调用参数。"""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []

    def enqueue_text(self, text: str, voice_id: str = "") -> None:
        self.enqueued.append((text, voice_id))


def install_fake_qwen_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    error: Exception | None = None,
    block_event: threading.Event | None = None,
    voice_id: str = "svc-voice-001",
) -> list[tuple[str, dict[str, Any]]]:
    """替换 DashScope 音色定制客户端（供应商 HTTP 边界），记录全部调用参数。"""
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeQwenVoiceCustomizationClient:
        def __init__(self, *, api_key: str, http_base_url: str, **kwargs: Any) -> None:
            calls.append(
                ("init", {"api_key": api_key, "http_base_url": http_base_url})
            )

        def _respond(self) -> Any:
            if error is not None:
                raise error
            return SimpleNamespace(voice_id=voice_id, payload={})

        def create_cloned_voice(self, *, prefix: str, url: str) -> Any:
            calls.append(("clone", {"prefix": prefix, "url": url}))
            if block_event is not None:
                assert block_event.wait(timeout=10), "假客户端等待释放超时"
            return self._respond()

        def create_designed_voice(
            self, *, prefix: str, voice_prompt: str, preview_text: str
        ) -> Any:
            calls.append(
                (
                    "design",
                    {
                        "prefix": prefix,
                        "voice_prompt": voice_prompt,
                        "preview_text": preview_text,
                    },
                )
            )
            return self._respond()

    monkeypatch.setattr(
        qwen_voice_customization,
        "QwenVoiceCustomizationClient",
        FakeQwenVoiceCustomizationClient,
    )
    return calls


# ================================================================ 1 导入导出


async def test_peek_import_json_reports_preview_fields(service) -> None:
    result = await call(service, "1", "card.peek_import_json", path=str(FIXTURE_CARD))
    preview = result["preview"]
    # 样例卡经 load_card_json 解析出的真实名称带时间线后缀
    assert preview["name"] == "白厄（3.4前）"
    assert preview["spec_version"] == "3.0"
    assert preview["greeting_count"] == 6  # first_mes + 5 条 alternate_greetings
    assert preview["world_book_entries"] == 20
    assert preview["report"]["applied"]  # 兼容报告必须非空
    assert preview["report"]["errors"] == []


async def test_peek_import_json_failure_keeps_original_error(service) -> None:
    missing = service.tmp_path / "不存在的卡.json"
    exc = await expect_service_error(
        lambda: call(service, "1", "card.peek_import_json", path=str(missing)),
        "card_import_failed",
    )
    assert missing.name in str(exc)  # message 携带原始错误摘要（含文件名）

    broken = service.tmp_path / "broken.json"
    broken.write_text("{这不是合法JSON", encoding="utf-8")
    await expect_service_error(
        lambda: call(service, "2", "card.peek_import_json", path=str(broken)),
        "card_import_failed",
        contains="解析失败",
    )


async def test_import_json_persists_as_tavern_import_with_duplicate_suffix(service) -> None:
    imported = await call(service, "1", "card.import_json", path=str(FIXTURE_CARD))
    assert imported["state"] == "imported"
    assert imported["report"]["applied"]

    fetched = await call(service, "2", "card.get", card_id=imported["card_id"])
    assert fetched["card"]["name"] == "白厄（3.4前）"
    assert fetched["source"] == "tavern_import"

    duplicate = await call(
        service, "3", "card.import_json", path=str(FIXTURE_CARD), as_duplicate=True
    )
    assert duplicate["state"] == "imported"
    assert duplicate["name"].endswith("（副本）")


async def test_export_json_roundtrip_and_avatar_saved_flag(service) -> None:
    imported = await call(service, "1", "card.import_json", path=str(FIXTURE_CARD))
    out_dir = service.tmp_path / "export-out"
    out_dir.mkdir()
    export_path = out_dir / "exported_card.json"

    result = await call(
        service,
        "2",
        "card.export_json",
        card_id=imported["card_id"],
        path=str(export_path),
        save_avatar=True,
    )
    assert result["exported"] is True
    assert result["avatar_saved"] is False  # 卡无头像时不另存头像文件

    re_peek = await call(service, "3", "card.peek_import_json", path=str(export_path))
    assert re_peek["preview"]["name"] == "白厄（3.4前）"


async def test_publish_validates_first_mes_then_is_idempotent(service) -> None:
    draft = await call(service, "1", "card.create_draft", name="无开场白角色")
    card_id = draft["card_id"]

    async def publish() -> Any:
        return await call(service, "p", "card.publish", card_id=card_id)

    await expect_service_error(publish, "card_publish_invalid", contains="第一条消息")

    await call(
        service,
        "2",
        "card.update",
        card_id=card_id,
        card={"name": "无开场白角色", "description": "设定", "first_mes": "你好。"},
    )
    published = await publish()
    assert published == {"card_id": card_id, "state": "saved"}

    republished = await publish()  # 非 draft 状态重复 publish 幂等成功
    assert republished["state"] == "saved"


# ================================================================ 2 头像资产


async def test_avatar_roundtrip_through_managed_asset_dir(service) -> None:
    card_id = await create_published_card(
        service, "c1", name="头像角色", description="设定", first_mes="你好"
    )
    png_path = service.tmp_path / "avatar.png"
    write_min_png(png_path, b"png-body-bytes")

    set_result = await call(
        service, "c2", "card.set_avatar", card_id=card_id, path=str(png_path)
    )
    assert set_result["card_id"] == card_id
    assert set_result["mime_type"] == "image/png"
    assert set_result["asset_id"]

    files = list(asset_dir(service).iterdir())
    assert len(files) == 1  # 资产复制进受管理目录

    fetched = await call(service, "c3", "card.get", card_id=card_id)
    avatar = fetched["avatar"]
    assert avatar is not None and avatar["mime_type"] == "image/png"
    assert base64.b64decode(avatar["data_base64"]) == png_path.read_bytes()

    removed = await call(service, "c4", "card.remove_avatar", card_id=card_id)
    assert removed == {"card_id": card_id, "removed": True}

    fetched_again = await call(service, "c5", "card.get", card_id=card_id)
    assert fetched_again["avatar"] is None
    assert list(asset_dir(service).iterdir()) == []  # 资产目录无残留
    assert service.asset_service.list_assets_for_card(card_id) == []


async def test_set_avatar_rejects_non_image_and_oversize(service) -> None:
    card_id = await create_published_card(
        service, "c1", name="头像校验", description="设定", first_mes="你好"
    )

    fake_png = service.tmp_path / "text.png"
    fake_png.write_text("plain text, not an image", encoding="utf-8")
    await expect_service_error(
        lambda: call(
            service, "c2", "card.set_avatar", card_id=card_id, path=str(fake_png)
        ),
        "card_avatar_unsupported",
    )

    oversize = service.tmp_path / "huge.png"
    oversize.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024))
    await expect_service_error(
        lambda: call(
            service, "c3", "card.set_avatar", card_id=card_id, path=str(oversize)
        ),
        "card_avatar_too_large",
    )


async def test_export_with_avatar_saves_sidecar_file(service) -> None:
    card_id = await create_published_card(
        service, "c1", name="导出头像", description="设定", first_mes="你好"
    )
    png_path = service.tmp_path / "avatar.png"
    write_min_png(png_path, b"sidecar-bytes")
    await call(service, "c2", "card.set_avatar", card_id=card_id, path=str(png_path))

    export_path = service.tmp_path / "exported.json"
    result = await call(
        service,
        "c3",
        "card.export_json",
        card_id=card_id,
        path=str(export_path),
        save_avatar=True,
    )
    assert result["avatar_saved"] is True
    sidecar = export_path.with_suffix(".avatar.png")
    assert sidecar.read_bytes() == png_path.read_bytes()


async def test_delete_card_cleans_all_assets(service) -> None:
    imported = await call(service, "d0", "card.import_json", path=str(FIXTURE_CARD))
    card_id = imported["card_id"]

    png_path = service.tmp_path / "avatar.png"
    write_min_png(png_path)
    await call(service, "d1", "card.set_avatar", card_id=card_id, path=str(png_path))

    wav_path = service.tmp_path / "reference.wav"
    write_wav(wav_path, seconds=0.5)
    await call(
        service,
        "d2",
        "voice.card_bind_reference",
        card_id=card_id,
        path=str(wav_path),
    )

    kinds = {a.kind for a in service.asset_service.list_assets_for_card(card_id)}
    assert kinds == {"avatar", "reference_audio"}

    await call(service, "d3", "card.delete", card_id=card_id, confirm=True)
    assert service.asset_service.list_assets_for_card(card_id) == []
    assert list(asset_dir(service).iterdir()) == []


# ================================================================ 3 卡音色状态机


async def test_voice_card_create_without_key_reports_not_configured(service) -> None:
    card_id = await create_published_card(
        service, "v0", name="无Key角色", description="设定", first_mes="你好"
    )
    await expect_service_error(
        lambda: call(
            service, "v1", "voice.card_create", card_id=card_id, mode="clone"
        ),
        "voice_not_configured",
    )


async def test_bind_reference_validates_format_size_and_duration(service) -> None:
    card_id = await create_published_card(
        service, "b0", name="参考音频角色", description="设定", first_mes="你好"
    )

    wrong_ext = service.tmp_path / "note.txt"
    wrong_ext.write_text("不是音频", encoding="utf-8")
    await expect_service_error(
        lambda: call(
            service, "b1", "voice.card_bind_reference", card_id=card_id, path=str(wrong_ext)
        ),
        "voice_reference_invalid",
    )

    oversize = service.tmp_path / "big.wav"
    oversize.write_bytes(b"\x00" * (10 * 1024 * 1024 + 1))
    await expect_service_error(
        lambda: call(
            service, "b2", "voice.card_bind_reference", card_id=card_id, path=str(oversize)
        ),
        "voice_reference_invalid",
    )

    too_long = service.tmp_path / "long.wav"
    write_wav(too_long, seconds=61, rate=8000)  # WAV 本地精确探测时长
    await expect_service_error(
        lambda: call(
            service, "b3", "voice.card_bind_reference", card_id=card_id, path=str(too_long)
        ),
        "voice_reference_invalid",
        contains="60",
    )

    wav_path = service.tmp_path / "ok.wav"
    size = write_wav(wav_path, seconds=1.0, rate=16000)
    bound = await call(
        service, "b4", "voice.card_bind_reference", card_id=card_id, path=str(wav_path)
    )
    assert bound["card_id"] == card_id
    assert abs(bound["duration_seconds"] - 1.0) < 1e-6
    assert bound["size_bytes"] == size
    assert bound["mime_type"] == "audio/wav"
    profile = service.card_repository.get_card(card_id).card.hsr.voice_profile
    assert profile.reference_audio_asset == bound["asset_id"]

    # 重新绑定不改变 state 与旧 voice_id（旧 ready 音色在重新创建前仍有效）
    force_voice_profile(service, card_id, state="voice_ready", voice_id="keep-me")
    wav_path2 = service.tmp_path / "ok2.wav"
    write_wav(wav_path2, seconds=0.5)
    await call(
        service, "b5", "voice.card_bind_reference", card_id=card_id, path=str(wav_path2)
    )
    profile_after = service.card_repository.get_card(card_id).card.hsr.voice_profile
    assert profile_after.state == "voice_ready"
    assert profile_after.voice_id == "keep-me"


async def test_clone_without_bound_reference_reports_missing(service) -> None:
    grant_voice_credentials(service)
    card_id = await create_published_card(
        service, "m0", name="未绑音频", description="设定", first_mes="你好"
    )
    await expect_service_error(
        lambda: call(
            service, "m1", "voice.card_create", card_id=card_id, mode="clone"
        ),
        "voice_reference_missing",
    )


async def test_voice_card_create_clone_success_flow(service, monkeypatch) -> None:
    grant_voice_credentials(service)
    calls = install_fake_qwen_client(monkeypatch)
    card_id = await create_published_card(
        service, "s0", name="克隆角色", description="设定", first_mes="你好"
    )

    wav_path = service.tmp_path / "ref.wav"
    write_wav(wav_path, seconds=1.0)
    await call(
        service, "s1", "voice.card_bind_reference", card_id=card_id, path=str(wav_path)
    )

    result = await call(
        service, "s2", "voice.card_create", card_id=card_id, mode="clone"
    )
    assert result == {"card_id": card_id, "state": "voice_ready", "voice_id": "svc-voice-001"}

    # 供应商边界收到账号凭据与 data URI 参考音频；中文卡名缺省 prefix 回退 card
    assert calls[0][0] == "init"
    assert calls[0][1]["api_key"] == "sk-test-key-0001"
    clone_call = next(item for item in calls if item[0] == "clone")
    assert clone_call[1]["prefix"] == "card"
    assert clone_call[1]["url"].startswith("data:audio/wav;base64,")

    profile = service.card_repository.get_card(card_id).card.hsr.voice_profile
    assert profile.state == "voice_ready"
    assert profile.voice_id == "svc-voice-001"
    assert profile.creation_mode == "clone"

    events = [
        e for e in service.event_log.payloads("voice.card_provision_changed")
        if e["card_id"] == card_id
    ]
    assert [e["state"] for e in events] == ["voice_creating", "voice_ready"]
    assert events[0]["voice_id"] is None
    assert events[1]["voice_id"] == "svc-voice-001"


async def test_voice_card_create_rejects_duplicate_while_in_progress(
    service, monkeypatch
) -> None:
    grant_voice_credentials(service)
    release = threading.Event()
    calls = install_fake_qwen_client(monkeypatch, block_event=release)
    card_id = await create_published_card(
        service, "l0", name="并发角色", description="设定", first_mes="你好"
    )
    wav_path = service.tmp_path / "ref.wav"
    write_wav(wav_path, seconds=1.0)
    await call(
        service, "l1", "voice.card_bind_reference", card_id=card_id, path=str(wav_path)
    )

    first = asyncio.ensure_future(
        call(service, "l2", "voice.card_create", card_id=card_id, mode="clone")
    )
    # 第一笔已进入供应商调用（每卡互斥锁持有中），第二笔必须被拒绝
    await wait_until(lambda: any(name == "clone" for name, _ in calls))
    await expect_service_error(
        lambda: call(
            service, "l3", "voice.card_create", card_id=card_id, mode="clone"
        ),
        "voice_card_provision_in_progress",
    )
    release.set()
    result = await asyncio.wait_for(first, DEFAULT_TIMEOUT_S)
    assert result["state"] == "voice_ready"


async def test_voice_card_create_failure_preserves_previous_voice_id(
    service, monkeypatch
) -> None:
    grant_voice_credentials(service)
    failure = qwen_voice_customization.VoiceCustomizationError(
        "上游拒绝：bad reference audio", http_status=400
    )
    install_fake_qwen_client(monkeypatch, error=failure)
    card_id = await create_published_card(
        service, "f0", name="失败保留", description="设定", first_mes="你好"
    )
    force_voice_profile(
        service,
        card_id,
        state="voice_ready",
        voice_id="old-voice-id",
        creation_mode="design",
    )

    exc = await expect_service_error(
        lambda: call(
            service,
            "f1",
            "voice.card_create",
            card_id=card_id,
            mode="design",
            voice_prompt="低沉而温暖的少年音",
        ),
        "voice_card_create_failed",
        contains="bad reference audio",
    )
    assert "bad reference audio" in str(exc)

    profile = service.card_repository.get_card(card_id).card.hsr.voice_profile
    assert profile.state == "voice_failed"
    assert profile.last_error != "" and "bad reference audio" in profile.last_error
    assert profile.voice_id == "old-voice-id"  # 旧 voice_id 不清空

    events = [
        e for e in service.event_log.payloads("voice.card_provision_changed")
        if e["card_id"] == card_id
    ]
    assert [e["state"] for e in events] == ["voice_creating", "voice_failed"]
    assert events[1]["voice_id"] == "old-voice-id"
    assert events[1]["error"] and "bad reference audio" in events[1]["error"]


async def test_voice_card_unbind_resets_state_but_keeps_reference_asset(
    service, monkeypatch
) -> None:
    grant_voice_credentials(service)
    install_fake_qwen_client(monkeypatch)
    card_id = await create_published_card(
        service, "u0", name="解绑角色", description="设定", first_mes="你好"
    )
    wav_path = service.tmp_path / "ref.wav"
    write_wav(wav_path, seconds=1.0)
    await call(
        service, "u1", "voice.card_bind_reference", card_id=card_id, path=str(wav_path)
    )
    created = await call(
        service, "u2", "voice.card_create", card_id=card_id, mode="clone"
    )
    assert created["state"] == "voice_ready"

    unbound = await call(service, "u3", "voice.card_unbind", card_id=card_id)
    assert unbound == {"card_id": card_id, "state": "voice_unconfigured"}

    profile = service.card_repository.get_card(card_id).card.hsr.voice_profile
    assert profile.voice_id == ""
    assert profile.creation_mode == ""
    kinds = [a.kind for a in service.asset_service.list_assets_for_card(card_id)]
    assert "reference_audio" in kinds  # 参考音频资产保留


async def test_voice_card_preview_gate_and_local_playback(service) -> None:
    card_id = await create_published_card(
        service, "p0", name="试听角色", description="设定", first_mes="你好"
    )
    # demo 服务无语音运行时：先报 voice_unavailable
    await expect_service_error(
        lambda: call(service, "p1", "voice.card_preview", card_id=card_id),
        "voice_unavailable",
    )

    runtime = RecordingVoiceRuntime()
    service.voice_runtime = runtime
    # 未就绪（无 profile）：voice_card_not_ready
    await expect_service_error(
        lambda: call(service, "p2", "voice.card_preview", card_id=card_id),
        "voice_card_not_ready",
    )

    force_voice_profile(
        service, card_id, state="voice_ready", voice_id="ready-vid-42"
    )
    result = await call(
        service, "p3", "voice.card_preview", card_id=card_id, text="晚上好呀"
    )
    assert isinstance(result["voice"], dict)
    assert runtime.enqueued == [("晚上好呀", "ready-vid-42")]  # 卡音色进入本地播放


# ================================================================ 4 对话绑定装配


async def test_new_conversation_snapshots_active_card_and_inserts_greeting(service) -> None:
    description = "【设定】金色的麦田与不肯熄灭的火种。"
    first_mes = "*他抬眼看到你时，笑意像被瞬间点燃一样亮了起来。*"
    card_id = await create_published_card(
        service, "g0", name="绑定角色", description=description, first_mes=first_mes
    )
    await call(service, "g1", "card.select_active", card_id=card_id)

    conversation = await create_conversation_model(service, "g2")
    assert conversation.character_card_id == card_id

    messages = service.store.load_conversation(conversation.conversation_id)["messages"]
    assert messages, "绑定卡的对话必须有开场白消息"
    assert messages[0].source == "character"
    assert messages[0].text == first_mes

    assembled = service._resolve_character_prompt(conversation.conversation_id)
    assert assembled is not None
    assert description in assembled.system_text  # 装配保留作者原文
    assert assembled.first_mes == first_mes


async def test_resolver_returns_none_for_unbound_or_unknown_conversations(service) -> None:
    initial_id = service.current_conversation_id
    assert service.store.get_conversation(initial_id).character_card_id is None
    assert service._resolve_character_prompt(initial_id) is None
    assert service._resolve_character_prompt("no-such-conversation") is None


async def test_switching_active_only_affects_future_conversations(service) -> None:
    card_a = await create_published_card(
        service, "w0", name="卡片甲", description="甲设定", first_mes="甲开场"
    )
    await call(service, "w1", "card.select_active", card_id=card_a)
    conv_a = await create_conversation_model(service, "w2")
    assert conv_a.character_card_id == card_a

    card_b = await create_published_card(
        service, "w3", name="卡片乙", description="乙设定", first_mes="乙开场"
    )
    await call(service, "w4", "card.select_active", card_id=card_b)
    conv_b = await create_conversation_model(service, "w5")
    assert conv_b.character_card_id == card_b

    reloaded_a = service.store.get_conversation(conv_a.conversation_id)
    assert reloaded_a.character_card_id == card_a  # 契约 §4.3-1：快照不变


async def test_draft_active_card_does_not_bind_new_conversations(service) -> None:
    draft = await call(service, "dr0", "card.create_draft", name="草稿角色")
    await call(service, "dr1", "card.select_active", card_id=draft["card_id"])

    conversation = await create_conversation_model(service, "dr2")
    assert conversation.character_card_id is None  # 契约 §4.1：draft 不生效
    assert service._resolve_character_prompt(conversation.conversation_id) is None


async def test_open_deleted_binding_emits_card_missing(service) -> None:
    card_id = await create_published_card(
        service, "x0", name="将删角色", description="设定", first_mes="你好"
    )
    await call(service, "x1", "card.select_active", card_id=card_id)
    conversation = await create_conversation_model(service, "x2")

    await call(service, "x3", "card.delete", card_id=card_id, confirm=True)

    opened = await call(
        service, "x4", "conversation.open", conversation_id=conversation.conversation_id
    )
    missings = service.event_log.payloads("conversation.card_missing")
    assert len(missings) == 1
    assert missings[0]["conversation_id"] == conversation.conversation_id
    assert missings[0]["card_id"] == card_id
    assert missings[0]["message"]

    # 绑定快照仍在对话上；resolver 回退内置（返回 None），不静默换人
    assert opened["conversation"]["character_card_id"] == card_id
    assert service._resolve_character_prompt(conversation.conversation_id) is None


# ================================================================ 5 卡音色覆盖


async def test_card_voice_overrides_pair_character_voice_only_when_bound(service) -> None:
    initial_id = service.current_conversation_id  # 未绑定卡的既有对话
    card_id = await create_published_card(
        service, "o0", name="覆盖角色", description="设定", first_mes="你好"
    )
    await call(service, "o1", "card.select_active", card_id=card_id)
    conversation = await create_conversation_model(service, "o2")
    pair_id = conversation.pair_id

    baseline = service._effective_voice_pair(pair_id)
    force_voice_profile(
        service, card_id, state="voice_ready", voice_id="cosyvoice-v2-card-01"
    )

    overridden = service._effective_voice_pair(pair_id, conversation.conversation_id)
    assert overridden.character.voice_id == "cosyvoice-v2-card-01"

    unbound = service._effective_voice_pair(pair_id, initial_id)
    assert unbound.character.voice_id == baseline.character.voice_id
    assert unbound.character.voice_id != "cosyvoice-v2-card-01"

    # 助手侧永不覆盖
    assert overridden.assistant.voice_id == baseline.assistant.voice_id


# ================================================================ 6 审批仲裁


async def test_approval_double_resolution_reports_first_outcome(service) -> None:
    approval_id = "apr-v035-arbitration-1"
    operation = PendingOperation(tool_kind="shell", command="echo hi")
    conversation_id = service.current_conversation_id

    async def waiter() -> ApprovalDecision:
        return await asyncio.wait_for(
            service.approval_broker.request(
                operation,
                approval_id,
                "需要执行命令",
                conversation_id,
                "task-v035",
            ),
            DEFAULT_TIMEOUT_S,
        )

    pending_task = asyncio.ensure_future(waiter())
    await wait_until(lambda: approval_id in service.approval_broker.pending)

    first = await call(
        service,
        "a1",
        "approval.resolve",
        approval_id=approval_id,
        decision="deny",
        origin="remote",
    )
    assert first == {
        "approval_id": approval_id,
        "accepted": True,
        "resolved_by": "remote",
        "decision": "deny",
    }
    decision = await asyncio.wait_for(pending_task, DEFAULT_TIMEOUT_S)
    assert decision == ApprovalDecision.DENY

    with pytest.raises(ServiceError) as excinfo:
        await call(
            service,
            "a2",
            "approval.resolve",
            approval_id=approval_id,
            decision="allow",
            origin="desktop",
        )
    assert excinfo.value.code == "approval_already_resolved"
    message = str(excinfo.value)
    assert "remote" in message and "deny" in message
    # 契约 §6：错误响应携带先到者的结构化真实结果（视觉遗留建议 1）。
    assert excinfo.value.details == {"decision": "deny", "resolved_by": "remote"}


async def test_approval_resolve_unknown_id_reports_not_found(service) -> None:
    await expect_service_error(
        lambda: call(
            service,
            "n1",
            "approval.resolve",
            approval_id="apr-never-exists",
            decision="allow",
        ),
        "approval_not_found",
    )


# ================================================================ 7 手机音频路由


async def test_mobile_ptt_start_requires_dashscope_key(service, monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    conversation_id = service.current_conversation_id
    await expect_service_error(
        lambda: call(
            service,
            "k1",
            "voice.mobile_ptt_start",
            conversation_id=conversation_id,
        ),
        "voice_not_configured",
    )


async def test_mobile_audio_chunk_rejects_non_integer_seq(service) -> None:
    for bad_seq in ("0", 0.5, True, None):
        await expect_service_error(
            lambda bad_seq=bad_seq: call(
                service,
                "q-bad",
                "voice.mobile_audio_chunk",
                session_id="sess-x",
                seq=bad_seq,
                data="AAE=",
            ),
            "invalid_params",
        )


async def test_mobile_audio_chunk_maps_manager_errors_verbatim(service) -> None:
    class GapManager:
        def __init__(self) -> None:
            self.fed: list[tuple[str, int, str]] = []

        def feed_chunk(self, session_id: str, seq: int, data: str) -> None:
            self.fed.append((session_id, seq, data))
            raise MobileAudioError("voice_audio_seq_gap", "跳号：期望 0，实际 2")

    gap_manager = GapManager()
    service._mobile_asr = gap_manager
    await expect_service_error(
        lambda: call(
            service,
            "e1",
            "voice.mobile_audio_chunk",
            session_id="sess-1",
            seq=2,
            data="AAE=",
        ),
        "voice_audio_seq_gap",
    )
    assert gap_manager.fed == [("sess-1", 2, "AAE=")]

    class AcceptingManager:
        def __init__(self) -> None:
            self.fed: list[tuple[str, int, str]] = []

        def feed_chunk(self, session_id: str, seq: int, data: str) -> None:
            self.fed.append((session_id, seq, data))

    accepting = AcceptingManager()
    service._mobile_asr = accepting
    accepted = await call(
        service,
        "e2",
        "voice.mobile_audio_chunk",
        session_id="sess-2",
        seq=0,
        data="AAE=",
    )
    assert accepted == {"accepted": True}
    assert accepting.fed == [("sess-2", 0, "AAE=")]
