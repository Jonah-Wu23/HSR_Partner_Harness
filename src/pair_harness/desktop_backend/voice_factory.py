from __future__ import annotations

from typing import Callable

from pair_harness.config.pairs import PairConfig, repository_root
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.voice_runtime import VoiceRuntime
from pair_harness.settings import Settings


def build_real_voice_runtime(
    *,
    settings: Settings,
    orchestrator: ConversationOrchestrator,
    pair_config: PairConfig,
    conversation_id: str,
    on_vad_state: Callable[[str], None],
    on_asr_partial: Callable[[str], None],
    on_error: Callable[[str], None],
) -> VoiceRuntime:
    """创建供桌面 Sidecar 使用的 VoiceRuntime。"""
    if not settings.dashscope_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置")

    from pair_harness.adapters.audio.qwen_asr import QwenStreamingRecognizer
    from pair_harness.adapters.audio.qwen_tts import QwenSpeechSynthesizer
    from pair_harness.adapters.audio.silero_vad import (
        SileroVoiceActivityDetector,
        VadUnavailableError,
    )
    from pair_harness.adapters.audio.sounddevice_io import AudioPlayer, MicrophoneCapture
    from pair_harness.core.audio import SpeechQueue

    model_path = repository_root() / "assets" / "models" / "silero_vad_v5.onnx"
    try:
        vad = SileroVoiceActivityDetector(model_path)
    except VadUnavailableError as exc:
        vad = None
        on_vad_state("unavailable")
        on_error(f"VAD 模型未启用：{exc}")
    else:
        on_vad_state("ready")

    return VoiceRuntime(
        orchestrator=orchestrator,
        recognizer=QwenStreamingRecognizer(
            api_key=settings.dashscope_api_key,
            ws_url=settings.resolved_ws_url,
            model=settings.qwen_asr_model,
        ),
        synthesizer=QwenSpeechSynthesizer(
            api_key=settings.dashscope_api_key,
            ws_url=settings.resolved_ws_url,
            model=settings.qwen_tts_model,
        ),
        vad=vad,
        capture_factory=lambda: MicrophoneCapture(block_size=640),
        player=AudioPlayer(sample_rate=24_000),
        queue=SpeechQueue(),
        pair_config=pair_config,
        conversation_id=conversation_id,
        on_vad_state=on_vad_state,
        on_asr_partial=on_asr_partial,
        on_error=on_error,
    )
