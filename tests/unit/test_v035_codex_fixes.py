"""V0.3.5 Codex Review 修复的回归测试（P1×6、P2×2 中的可离线验证项）。

覆盖：
- Codex P1 #1：remote-only 事件序号必须消费（allocate_sequence），与 emit 交错单调不重复。
- Codex P1 #5：复制卡真实复制受管理资产，删除原卡后副本头像仍在。
- Codex P1 #7：卡引用头像但资产损坏时 card.get 如实失败（card_avatar_missing）。
- Codex P1 #9：TTS 供应商失败发 voice.mobile_tts_failed（手机端退出播放状态）。
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pair_harness.core.contracts import Message, MessageKind, MessageSource
from pair_harness.desktop_backend.application_service import ServiceError

# 复用 test_v035_wiring 的 command 辅助与 service 夹具（pytest 同目录导入）
from test_v035_wiring import command, service  # noqa: F401


def test_eventemitter_allocate_sequence_keeps_global_monotonic_order() -> None:
    """Codex P1 #1：remote-only 事件必须消费序号，与 emit 交错仍单调不重复。"""
    from pair_harness.desktop_backend.events import EventEmitter

    emitted: list[dict[str, Any]] = []
    emitter = EventEmitter(emitted.append)
    seq_remote_a = emitter.allocate_sequence()
    emitter.emit("business.event", {})
    seq_remote_b = emitter.allocate_sequence()
    emitter.emit("business.event2", {})
    sequences = [
        seq_remote_a,
        emitted[0]["sequence"],
        seq_remote_b,
        emitted[1]["sequence"],
    ]
    assert sequences == sorted(set(sequences)), sequences


@pytest.mark.asyncio
async def test_card_duplicate_copies_shared_assets(service, tmp_path_factory) -> None:
    """Codex P1 #5：复制卡必须真实复制受管理资产；删除原卡后副本头像仍在。"""
    created = await service.handle_command(command("1", "card.create_draft", name="资产卡"))
    card_id = created["card_id"]
    png_path = Path(tmp_path_factory.mktemp("dup_assets")) / "a.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"original-image-bytes")
    await service.handle_command(command("2", "card.set_avatar", card_id=card_id, path=str(png_path)))

    duplicated = await service.handle_command(command("3", "card.duplicate", card_id=card_id))
    dup_id = duplicated["card_id"]

    # 删除原卡（连带头像资产清理），副本的头像必须仍然可读且字节一致
    await service.handle_command(command("4", "card.delete", card_id=card_id, confirm=True))
    fetched = await service.handle_command(command("5", "card.get", card_id=dup_id))
    avatar = fetched["avatar"]
    assert avatar is not None, "副本头像被原卡删除连带清掉（Codex P1 #5）"
    assert base64.b64decode(avatar["data_base64"]) == b"\x89PNG\r\n\x1a\n" + b"original-image-bytes"


@pytest.mark.asyncio
async def test_card_get_avatar_asset_corruption_raises(service, tmp_path_factory) -> None:
    """Codex P1 #7：卡引用头像但资产文件损坏时如实失败，不合成 avatar:null。"""
    created = await service.handle_command(command("1", "card.create_draft", name="损坏卡"))
    card_id = created["card_id"]
    png_path = Path(tmp_path_factory.mktemp("broken_avatar")) / "b.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"to-be-deleted")
    await service.handle_command(command("2", "card.set_avatar", card_id=card_id, path=str(png_path)))
    # 模拟资产文件真实丢失（表记录仍在）
    for record in service.asset_service.list_assets_for_card(card_id):
        Path(record.file_path).unlink()

    with pytest.raises(ServiceError) as excinfo:
        await service.handle_command(command("3", "card.get", card_id=card_id))
    assert excinfo.value.code == "card_avatar_missing"


@pytest.mark.asyncio
async def test_mobile_tts_failure_publishes_failed_event(service, monkeypatch) -> None:
    """Codex P1 #9：TTS 供应商失败必须发 voice.mobile_tts_failed，手机端不能停在 buffering。"""
    import pair_harness.adapters.audio.qwen_tts as qwen_tts_module

    published: list[tuple[str, dict[str, Any]]] = []

    class FakeFanout:
        def has_remote_subscribers(self):
            return True

        def publish(self, envelope, *, remote_only=False):
            published.append((envelope["event"], envelope["payload"]))

    monkeypatch.setattr(service, "_event_fanout", FakeFanout())
    conversation = service.store.get_conversation(service.current_conversation_id)
    message = Message(
        conversation_id=conversation.conversation_id,
        pair_id=conversation.pair_id,
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text="你好",
        tts_eligible=True,
    )

    class ExplodingSynthesizer:
        def __init__(self, **kwargs):
            pass

        async def synthesize(self, request):
            raise RuntimeError("dashscope connection refused")
            yield  # pragma: no cover - 使其成为 async 生成器

        async def aclose(self):
            return None

    # relay 任务内部对 QwenSpeechSynthesizer 是局部导入，patch 模块属性即命中
    monkeypatch.setattr(qwen_tts_module, "QwenSpeechSynthesizer", ExplodingSynthesizer)
    # 无 Key 的 demo 环境音色解析为空会提前返回；本测试关注失败事件路径
    monkeypatch.setattr(
        service,
        "_effective_voice_pair",
        lambda pair_id, conversation_id=None: SimpleNamespace(
            character=SimpleNamespace(voice_id="test-voice-id"),
            assistant=SimpleNamespace(voice_id=""),
        ),
    )
    await asyncio.wait_for(service._relay_mobile_tts_task(message), timeout=5)

    events = [name for name, _ in published]
    assert "voice.mobile_tts_failed" in events, events
    failed_payload = next(p for name, p in published if name == "voice.mobile_tts_failed")
    assert failed_payload["message_id"] == message.message_id
    assert "connection refused" in failed_payload["error"]
