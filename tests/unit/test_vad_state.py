"""Silero VAD 状态机测试（B2.2）。

通过 FakeSession 注入每帧语音概率，驱动 512 样本重分帧与
listening → speech → ended/false_trigger 状态机，不触碰真实模型。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pair_harness.adapters.audio.silero_vad import (
    DEFAULT_REDEMPTION_FRAMES,
    FRAME_BYTES,
    FRAME_SAMPLES,
    SileroVoiceActivityDetector,
    VadUnavailableError,
    copy_reference_model,
)
from pair_harness.core.contracts import VadEvent

SILENT_FRAME = b"\x00" * FRAME_BYTES  # 512 样本 int16 全零（32 ms @ 16 kHz）
CHUNK_20MS = b"\x00" * (FRAME_SAMPLES // 2 * 2)  # 20 ms 块 = 512 字节


class FakeSession:
    """模拟 onnxruntime InferenceSession：按序吐出注入的概率。"""

    def __init__(self, probabilities: list[float]) -> None:
        self._probs = list(probabilities)
        self.calls = 0

    def run(self, output_names, inputs):
        self.calls += 1
        prob = self._probs.pop(0) if self._probs else 0.0
        # onnx 输出形状 (1,1,1)：_frame_probability 取 outputs[0][0][0]
        return [[prob]], inputs["state"]


def _make_detector(
    monkeypatch: pytest.MonkeyPatch,
    probabilities: list[float],
    **kwargs,
) -> SileroVoiceActivityDetector:
    fake = FakeSession(probabilities)
    monkeypatch.setattr(
        SileroVoiceActivityDetector,
        "_load_session",
        staticmethod(lambda path: fake),
    )
    detector = SileroVoiceActivityDetector(Path("unused.onnx"), **kwargs)
    return detector


async def _collect(detector: SileroVoiceActivityDetector, chunks: list[bytes]) -> list[VadEvent]:
    async def _stream():
        for chunk in chunks:
            yield chunk

    return [event async for event in detector.detect(_stream())]


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------


async def test_silence_only_emits_listening(monkeypatch) -> None:
    detector = _make_detector(monkeypatch, [0.01] * 10)
    events = await _collect(detector, [SILENT_FRAME] * 10)
    assert [e.type for e in events] == ["listening"]


async def test_short_burst_is_false_trigger(monkeypatch) -> None:
    """语音不足 min_speech_frames(4) 帧，闭合时产出 false_trigger。"""
    detector = _make_detector(
        monkeypatch, [0.9] * 2 + [0.01] * 18, redemption_frames=18
    )
    events = await _collect(detector, [SILENT_FRAME] * 20)
    assert [e.type for e in events] == ["listening", "speech_started", "false_trigger"]


async def test_speech_ended_after_redemption_silence(monkeypatch) -> None:
    """≥4 帧语音 + 连续 18 帧静音 → speech_ended。"""
    detector = _make_detector(
        monkeypatch, [0.9] * 5 + [0.01] * 18, redemption_frames=18
    )
    events = await _collect(detector, [SILENT_FRAME] * 23)
    assert [e.type for e in events] == ["listening", "speech_started", "speech_ended"]


async def test_voice_resumes_within_redemption_window(monkeypatch) -> None:
    """静音不足 18 帧时恢复语音，不提前结束。"""
    detector = _make_detector(
        monkeypatch,
        [0.9] * 4 + [0.01] * 5 + [0.9] * 6 + [0.01] * 18,
        redemption_frames=18,
    )
    events = await _collect(detector, [SILENT_FRAME] * 33)
    assert [e.type for e in events] == ["listening", "speech_started", "speech_ended"]


async def test_default_redemption_window_keeps_short_pause_inside_turn(monkeypatch) -> None:
    """默认约一秒的静音窗口让说话中的短暂停顿继续归入同一段。

    18 帧停顿 + 4 帧语音 + 默认窗口静音：只有当默认窗口大于 18 帧时
    才产出单一 speech_ended；窗口缩回旧的 18 帧时 18 帧停顿会先触发
    speech_ended、再 false_trigger，本测试随即变红。
    """
    probabilities = (
        [0.9] * 6
        + [0.01] * 18
        + [0.9] * 4
        + [0.01] * DEFAULT_REDEMPTION_FRAMES
    )
    detector = _make_detector(monkeypatch, probabilities)
    events = await _collect(detector, [SILENT_FRAME] * len(probabilities))
    assert [e.type for e in events] == ["listening", "speech_started", "speech_ended"]


async def test_stream_end_with_open_speech_emits_ended(monkeypatch) -> None:
    """输入流结束且语音 ≥4 帧：按已说话帧数判定 speech_ended。"""
    detector = _make_detector(monkeypatch, [0.9] * 4)
    events = await _collect(detector, [SILENT_FRAME] * 4)
    assert [e.type for e in events] == ["listening", "speech_started", "speech_ended"]


async def test_stream_end_with_short_open_speech_is_false_trigger(monkeypatch) -> None:
    detector = _make_detector(monkeypatch, [0.9] * 3)
    events = await _collect(detector, [SILENT_FRAME] * 3)
    assert [e.type for e in events] == ["listening", "speech_started", "false_trigger"]


async def test_empty_chunks_are_skipped(monkeypatch) -> None:
    detector = _make_detector(monkeypatch, [0.9] * 4)
    events = await _collect(detector, [b"", SILENT_FRAME, b"", SILENT_FRAME * 3, b""])
    assert [e.type for e in events] == ["listening", "speech_started", "speech_ended"]


# ---------------------------------------------------------------------------
# 重分帧
# ---------------------------------------------------------------------------


async def test_rechunks_20ms_blocks_into_512_sample_frames(monkeypatch) -> None:
    """20 ms（512 字节）块被重分帧：3 块凑 1.5 帧，跨块拼接。"""
    fake = FakeSession([0.9] * 4 + [0.01] * 18)
    monkeypatch.setattr(
        SileroVoiceActivityDetector, "_load_session", staticmethod(lambda path: fake)
    )
    detector = SileroVoiceActivityDetector(Path("unused.onnx"))
    # 3 块 × 512 字节 = 1.5 帧 → 第 1 帧推理，尾部 256 字节留存；
    # 再喂 5 个完整帧 → 第 2 帧由 256B 尾部 + 768B 拼出，随后 4 帧推理
    events = await _collect(detector, [CHUNK_20MS] * 3 + [SILENT_FRAME] * 5)
    assert fake.calls == 6
    assert [e.type for e in events] == ["listening", "speech_started", "speech_ended"]


async def test_arbitrary_chunk_sizes_are_stitched(monkeypatch) -> None:
    """不规则块大小（如 999 字节）也能正确拼接成帧。"""
    fake = FakeSession([0.9] * 4 + [0.01] * 18)
    monkeypatch.setattr(
        SileroVoiceActivityDetector, "_load_session", staticmethod(lambda path: fake)
    )
    detector = SileroVoiceActivityDetector(Path("unused.onnx"))
    odd = b"\x00" * 999
    events = await _collect(detector, [odd] * 4)  # 3996 字节 = 3.9 帧
    assert fake.calls == 3
    assert [e.type for e in events] == ["listening", "speech_started", "false_trigger"]


# ---------------------------------------------------------------------------
# 构造与模型文件
# ---------------------------------------------------------------------------


def test_missing_model_raises_unavailable(tmp_path: Path) -> None:
    with pytest.raises(VadUnavailableError):
        SileroVoiceActivityDetector(tmp_path / "missing.onnx")


def test_copy_reference_model(tmp_path: Path) -> None:
    source = tmp_path / "src.onnx"
    source.write_bytes(b"fake-onnx")
    dest = tmp_path / "sub" / "dest.onnx"
    copy_reference_model(source, dest)
    assert dest.read_bytes() == b"fake-onnx"


def test_copy_reference_model_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        copy_reference_model(tmp_path / "nope.onnx", tmp_path / "dest.onnx")
