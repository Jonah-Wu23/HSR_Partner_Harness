# Silero VAD v5 本地语音活动检测：16 kHz 单声道 int16 PCM 按 512 样本重分帧，逐帧用 onnxruntime 推理。
# 阈值 0.45、结束等待约 1 秒、最短语音 4 帧；开口前的 pre-roll 由 VoiceRuntime 维护。

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path

import numpy as np
import onnxruntime as ort

from pair_harness.core.contracts import VadEvent
from pair_harness.core.ports import VoiceActivityDetector

FRAME_SAMPLES = 512  # Silero v5 在 16 kHz 下的帧长（32 ms）
FRAME_BYTES = FRAME_SAMPLES * 2  # int16 单声道
DEFAULT_REDEMPTION_FRAMES = 30  # 约 960 ms 连续静音后结束语音段


class SileroVoiceActivityDetector(VoiceActivityDetector):
    """本地 Silero VAD v5 状态机。

    ``detect`` 每次调用维护独立的模型循环状态；进入即产出
    ``listening``，之后按语音概率产出事件，直到输入流结束。
    模型文件缺失或损坏时构造即抛出 onnxruntime 的原始错误。
    """

    def __init__(
        self,
        model_path: Path,
        *,
        threshold: float = 0.45,
        redemption_frames: int = DEFAULT_REDEMPTION_FRAMES,
        min_speech_frames: int = 4,
    ) -> None:
        self.model_path = Path(model_path)
        self.threshold = threshold
        self.redemption_frames = redemption_frames
        self.min_speech_frames = min_speech_frames
        self._session = self._load_session(self.model_path)

    @staticmethod
    def _load_session(model_path: Path) -> ort.InferenceSession:
        return ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])

    def _frame_probability(self, frame: bytes, state) -> tuple[float, object]:
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        samples = samples.reshape(1, -1)
        outputs = self._session.run(
            ["output", "stateN"],
            {"input": samples, "state": state, "sr": np.array(16000, dtype=np.int64)},
        )
        return float(outputs[0][0][0]), outputs[1]

    async def detect(self, pcm_stream: AsyncIterable[bytes]) -> AsyncIterator[VadEvent]:
        yield VadEvent(type="listening")

        state = np.zeros((2, 1, 128), dtype=np.float32)
        pending = b""  # 不足一帧的尾部留存

        # 状态机字段
        state_name = "listening"  # listening | speech
        speech_frames = 0
        silence_frames = 0

        async for chunk in pcm_stream:
            if not chunk:
                continue
            pending += chunk
            while len(pending) >= FRAME_BYTES:
                frame, pending = pending[:FRAME_BYTES], pending[FRAME_BYTES:]
                prob, state = self._frame_probability(frame, state)
                is_speech = prob >= self.threshold

                if state_name == "listening":
                    if is_speech:
                        state_name = "speech"
                        speech_frames = 1
                        silence_frames = 0
                        yield VadEvent(type="speech_started")
                    continue

                # state_name == "speech"
                if is_speech:
                    speech_frames += 1
                    silence_frames = 0
                    continue
                silence_frames += 1
                if silence_frames >= self.redemption_frames:
                    if speech_frames >= self.min_speech_frames:
                        yield VadEvent(type="speech_ended")
                    else:
                        yield VadEvent(type="false_trigger")
                    state_name = "listening"
                    speech_frames = 0
                    silence_frames = 0

        # 输入流结束：未闭合的语音段按已说话帧数判定
        if state_name == "speech":
            if speech_frames >= self.min_speech_frames:
                yield VadEvent(type="speech_ended")
            else:
                yield VadEvent(type="false_trigger")
