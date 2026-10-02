from __future__ import annotations

from pathlib import Path

import pytest
from onnxruntime.capi.onnxruntime_pybind11_state import NoSuchFile

from pair_harness.adapters.audio.silero_vad import (
    DEFAULT_REDEMPTION_FRAMES,
    FRAME_BYTES,
    FRAME_SAMPLES,
    SileroVoiceActivityDetector,
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


ENDED = ["listening", "speech_started", "speech_ended"]
FALSE_TRIGGER = ["listening", "speech_started", "false_trigger"]


@pytest.mark.parametrize(
    ("probabilities", "options", "expected"),
    [
        pytest.param([0.01] * 10, {}, ["listening"], id="silence_only"),
        # 语音不足 min_speech_frames（4 帧）即闭合
        pytest.param([0.9] * 2 + [0.01] * 18, {"redemption_frames": 18}, FALSE_TRIGGER, id="short_burst"),
        pytest.param([0.9] * 5 + [0.01] * 18, {"redemption_frames": 18}, ENDED, id="ended_after_redemption"),
        # 静音不足窗口时恢复语音，仍是同一段
        pytest.param(
            [0.9] * 4 + [0.01] * 5 + [0.9] * 6 + [0.01] * 18,
            {"redemption_frames": 18},
            ENDED,
            id="resumes_within_window",
        ),
        # 默认约一秒的窗口让 18 帧停顿继续归入同一段
        pytest.param(
            [0.9] * 6 + [0.01] * 18 + [0.9] * 4 + [0.01] * DEFAULT_REDEMPTION_FRAMES,
            {},
            ENDED,
            id="default_window_keeps_short_pause",
        ),
        # 输入流结束时按已说话帧数判定
        pytest.param([0.9] * 4, {}, ENDED, id="stream_end_with_open_speech"),
        pytest.param([0.9] * 3, {}, FALSE_TRIGGER, id="stream_end_with_short_speech"),
    ],
)
async def test_speech_segment_state_machine(monkeypatch, probabilities, options, expected) -> None:
    detector = _make_detector(monkeypatch, probabilities, **options)
    events = await _collect(detector, [SILENT_FRAME] * len(probabilities))
    assert [e.type for e in events] == expected


async def test_empty_chunks_are_skipped(monkeypatch) -> None:
    detector = _make_detector(monkeypatch, [0.9] * 4)
    events = await _collect(detector, [b"", SILENT_FRAME, b"", SILENT_FRAME * 3, b""])
    assert [e.type for e in events] == ENDED


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
    assert [e.type for e in events] == ENDED


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
    assert [e.type for e in events] == FALSE_TRIGGER


# ---------------------------------------------------------------------------
# 构造与模型文件
# ---------------------------------------------------------------------------


def test_missing_model_raises_onnxruntime_error(tmp_path: Path) -> None:
    with pytest.raises(NoSuchFile):
        SileroVoiceActivityDetector(tmp_path / "missing.onnx")
