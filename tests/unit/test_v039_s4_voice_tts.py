"""V0.3.9（S4）语音侧离线回归：V039-S4-012（适配器侧）/ V039-S4-018（中继侧）。

本文件全部离线：DashScope 适配器由脚本化替身替换，不发网络请求、不读真实
账号配置、不启动候选应用、不连真机。真实限流阈值与真实抢占时序仍需真机复验，
离线通过不等于真机通过。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from pair_harness.core.contracts import (
    AudioChunk,
    Message,
    MessageKind,
    MessageSource,
)

# 复用 test_v035_wiring 的 service 夹具（pytest 同目录导入）
from test_v035_wiring import service  # noqa: F401


def _install_relay_prerequisites(service, monkeypatch, published: list) -> None:
    """让 _maybe_relay_mobile_tts 走到真实下发路径（无真实供应商）。"""

    class FakeFanout:
        def has_remote_subscribers(self) -> bool:
            return True

        def publish(self, envelope, *, remote_only: bool = False) -> None:
            published.append((envelope["event"], envelope["payload"]))

    monkeypatch.setattr(service, "_event_fanout", FakeFanout())
    monkeypatch.setattr(
        service,
        "_load_account_config",
        lambda *args, **kwargs: {
            "voice.api_key": "test-key",
            "voice.base_url": "https://example.test",
        },
    )
    monkeypatch.setattr(
        service,
        "_effective_voice_pair",
        lambda pair_id, conversation_id=None: SimpleNamespace(
            character=SimpleNamespace(voice_id="test-voice-id"),
            assistant=SimpleNamespace(voice_id=""),
        ),
    )


def _character_message(conversation, message_id: str, text: str = "你好") -> Message:
    return Message(
        message_id=message_id,
        conversation_id=conversation.conversation_id,
        pair_id=conversation.pair_id,
        source=MessageSource.CHARACTER,
        kind=MessageKind.CHARACTER_SPEECH,
        text=text,
        tts_eligible=True,
    )


async def test_preempted_relay_is_not_reported_as_failure(service, monkeypatch) -> None:
    """V039-S4-018：抢占旧合成不得产生 voice.mobile_tts_failed。

    复刻现场时序：旧中继挂在 asyncio.wait_for(future, timeout) 上，分片 future
    先就绪，随后 _maybe_relay_mobile_tts 取消旧任务并 stop(old_msg_id)；Python
    3.11 的 wait_for 在 future 已完成时返回其结果而不抛 CancelledError，因此旧
    任务会继续执行到下一次 feed()——此时条目已被 stop 回收。该路径必须按
    「已中断」静默收尾，不得广播失败。
    """
    published: list[tuple[str, dict[str, Any]]] = []
    _install_relay_prerequisites(service, monkeypatch, published)
    conversation = service.store.get_conversation(service.current_conversation_id)

    entered = asyncio.Event()
    chunk = AudioChunk(pcm=b"\x01\x02" * 8, sample_rate=24_000, channels=1)

    class ScriptedSynthesizer:
        pending: asyncio.Future | None = None

        def __init__(self, **kwargs: Any) -> None:
            pass

        async def synthesize(self, request):
            if request.message_id == "m-old":
                future: asyncio.Future = asyncio.get_running_loop().create_future()
                ScriptedSynthesizer.pending = future
                entered.set()
                ready = await asyncio.wait_for(future, timeout=5)
                yield ready
                return
            yield AudioChunk(pcm=b"\x03\x04" * 8, sample_rate=24_000, channels=1)

        async def aclose(self) -> None:
            return None

    import pair_harness.adapters.audio.qwen_tts as qwen_tts_module

    monkeypatch.setattr(qwen_tts_module, "QwenSpeechSynthesizer", ScriptedSynthesizer)

    service._maybe_relay_mobile_tts(_character_message(conversation, "m-old"))
    old_task = service._mobile_tts_tasks["m-old"]
    await asyncio.wait_for(entered.wait(), timeout=5)
    assert ScriptedSynthesizer.pending is not None
    # 分片先就绪，再让新回复到达触发抢占（cancel + stop）
    ScriptedSynthesizer.pending.set_result(chunk)
    service._maybe_relay_mobile_tts(_character_message(conversation, "m-new"))
    new_task = service._mobile_tts_tasks["m-new"]

    # 旧任务整条收尾（取消或正常返回都不影响本断言：关键是不得上报失败）
    done, _ = await asyncio.wait({old_task}, timeout=5)
    assert done, "旧中继任务没有收尾"
    await asyncio.wait_for(new_task, timeout=5)

    events = [name for name, _ in published]
    assert "voice.mobile_tts_failed" not in events, published
    # 新消息的路径本身照常完成（不是靠整体静默换来的「没有失败」）
    assert "voice.mobile_tts_chunk" in events
    assert any(
        name == "voice.mobile_tts_end" and payload["message_id"] == "m-new"
        for name, payload in published
    )


async def test_supplier_failure_is_still_reported(service, monkeypatch) -> None:
    """V039-S4-018 反向断言：真实供应商失败仍必须上报失败事件。"""
    published: list[tuple[str, dict[str, Any]]] = []
    _install_relay_prerequisites(service, monkeypatch, published)
    conversation = service.store.get_conversation(service.current_conversation_id)

    class ExplodingSynthesizer:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def synthesize(self, request):
            raise RuntimeError("Throttling.RateQuota: Requests rate limit exceeded")
            yield  # pragma: no cover - 使其成为 async 生成器

        async def aclose(self) -> None:
            return None

    import pair_harness.adapters.audio.qwen_tts as qwen_tts_module

    monkeypatch.setattr(qwen_tts_module, "QwenSpeechSynthesizer", ExplodingSynthesizer)

    await asyncio.wait_for(
        service._relay_mobile_tts_task(_character_message(conversation, "m-fail")),
        timeout=5,
    )
    failures = [
        payload for name, payload in published if name == "voice.mobile_tts_failed"
    ]
    assert len(failures) == 1, published
    assert failures[0]["message_id"] == "m-fail"
    assert "Throttling.RateQuota" in failures[0]["error"]
