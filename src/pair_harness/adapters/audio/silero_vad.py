"""Silero VAD v5 本地语音活动检测（B2）。

把 16 kHz 单声道 int16 PCM 块流切成语音事件。内部：

- 任意大小的 PCM 块按 512 样本（32 ms @ 16 kHz）重分帧，不足一帧的
  尾部留存与下一块拼接；
- 每帧送入 onnxruntime 推理（毫秒级，直接在异步迭代器内同步调用，
  不进线程池——避免过度设计）；
- 状态机产出 ``VadEvent``：``listening`` / ``speech_started`` /
  ``speech_ended`` / ``false_trigger``，参数语义沿用旧项目
  ``vad-config.ts``（阈值 0.45、开口前保留 8 帧、结束等待 18 帧、
  最短语音 4 帧）。

模型文件缺失或 onnxruntime 不可用时，构造阶段抛
:class:`VadUnavailableError`；VoiceRuntime 捕获后退回按键说话。
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path

from pair_harness.core.contracts import VadEvent
from pair_harness.core.ports import VoiceActivityDetector

FRAME_SAMPLES = 512  # Silero v5 在 16 kHz 下的帧长（32 ms）
FRAME_BYTES = FRAME_SAMPLES * 2  # int16 单声道


class VadUnavailableError(RuntimeError):
    """VAD 模型文件缺失或 onnxruntime 不可导入。"""


class SileroVoiceActivityDetector(VoiceActivityDetector):
    """本地 Silero VAD v5 状态机。

    ``detect`` 每次调用维护独立的模型循环状态；进入即产出
    ``listening``，之后按语音概率产出事件，直到输入流结束。
    """

    def __init__(
        self,
        model_path: Path,
        *,
        threshold: float = 0.45,
        pre_speech_pad_frames: int = 8,
        redemption_frames: int = 18,
        min_speech_frames: int = 4,
    ) -> None:
        self.model_path = Path(model_path)
        self.threshold = threshold
        self.pre_speech_pad_frames = pre_speech_pad_frames
        self.redemption_frames = redemption_frames
        self.min_speech_frames = min_speech_frames
        self._session = self._load_session(self.model_path)

    @staticmethod
    def _load_session(model_path: Path):
        # 先检查文件，缺模型时不必加载 onnxruntime 原生库；这也避免无语音
        # 环境的降级路径在进程退出时承受无意义的原生运行时收尾。
        if not model_path.is_file():
            raise VadUnavailableError(
                f"VAD 模型文件缺失: {model_path}（应放置 silero_vad_v5.onnx）"
            )
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError as exc:  # pragma: no cover - 由环境决定
            raise VadUnavailableError(
                "未安装 onnxruntime，无法启用本地 VAD"
            ) from exc
        try:
            return ort.InferenceSession(
                str(model_path), providers=["CPUExecutionProvider"]
            )
        except Exception as exc:  # pragma: no cover - 模型损坏等
            raise VadUnavailableError(f"VAD 模型加载失败: {exc}") from exc

    def _frame_probability(self, frame: bytes, state) -> tuple[float, object]:
        import numpy as np  # 延迟导入：仅真实 VAD 路径需要

        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        samples = samples.reshape(1, -1)
        outputs = self._session.run(
            ["output", "stateN"],
            {"input": samples, "state": state, "sr": np.array(16000, dtype=np.int64)},
        )
        return float(outputs[0][0][0]), outputs[1]

    async def detect(self, pcm_stream: AsyncIterable[bytes]) -> AsyncIterator[VadEvent]:
        import numpy as np  # 延迟导入：仅真实 VAD 路径需要

        yield VadEvent(type="listening")

        state = np.zeros((2, 1, 128), dtype=np.float32)
        pending = b""  # 不足一帧的尾部留存

        # 状态机字段
        state_name = "listening"  # listening | speech
        speech_frames = 0
        silence_frames = 0
        # 开口前保留的 pre-roll 帧（环形缓冲，speech_started 时一并交给调用方）
        pre_roll: list[bytes] = []

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
                    else:
                        # 未开口的静音帧进 pre-roll，超容量丢弃最旧帧
                        pre_roll.append(frame)
                        if len(pre_roll) > self.pre_speech_pad_frames:
                            pre_roll.pop(0)
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
                    pre_roll = []

        # 输入流结束：未闭合的语音段按已说话帧数判定
        if state_name == "speech":
            if speech_frames >= self.min_speech_frames:
                yield VadEvent(type="speech_ended")
            else:
                yield VadEvent(type="false_trigger")

    @property
    def pre_roll_bytes(self) -> int:
        """开口前保留的 pre-roll 字节数（供 VoiceRuntime 补发 ASR）。"""
        return self.pre_speech_pad_frames * FRAME_BYTES


def copy_reference_model(source: Path, dest: Path) -> None:
    """把旧项目的 silero_vad_v5.onnx 复制到项目 assets/models/。"""
    if not source.is_file():
        raise FileNotFoundError(f"源模型不存在: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
