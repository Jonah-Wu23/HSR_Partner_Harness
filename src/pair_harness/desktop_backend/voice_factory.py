from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Callable, Mapping, Literal

from pair_harness.config.pairs import PairConfig, repository_root
from pair_harness.core.orchestrator import ConversationOrchestrator
from pair_harness.core.voice_runtime import VoiceRuntime
from pair_harness.settings import Settings


@dataclass(frozen=True)
class EffectiveVoiceProfile:
    """V0.3.2 M6（计划 5.16 节）：当前账号的有效 TTS 音色解析结果。

    - ``account``：账号已保存自己的 voice.api_key，逐说话方使用
      ``voice.profile.<speaker>.voice_id``；未生成的说话方为 ``None``
      （TTS 不可用，不回退作者音色）。
    - ``env_author``：账号没有保存 Key，但开发机 ``.env`` 提供作者
      DASHSCOPE_API_KEY 时，继续使用 pair YAML 的作者音色（开发机兼容）。
    - ``not_provisioned``：既没有账号结果也没有开发环境 Key，TTS 不可用。
    """

    state: Literal["account", "env_author", "not_provisioned"]
    character_voice_id: str | None
    assistant_voice_id: str | None


def resolve_effective_voice_profile(
    *,
    account_config: Mapping[str, str],
    settings: Settings,
    pair_config: PairConfig,
) -> EffectiveVoiceProfile:
    """有效音色解析优先级：账号级 voice.profile.* → 开发机 .env 作者音色 → 不可用。"""
    account_key_configured = "voice.api_key" in account_config
    account_key = account_config.get("voice.api_key") or ""
    if account_key:
        # 账号自带 Key：只允许使用该账号自己生成的音色；未生成的说话方
        # 保持不可用，禁止拿 pair YAML 的作者 ID 静默尝试。
        character = account_config.get(
            f"voice.profile.{pair_config.character.id}.voice_id"
        ) or None
        assistant = account_config.get(
            f"voice.profile.{pair_config.assistant.id}.voice_id"
        ) or None
        return EffectiveVoiceProfile(
            state="account",
            character_voice_id=character,
            assistant_voice_id=assistant,
        )
    if account_key_configured:
        # 账号显式清空 Key 时不能重新落回开发机作者 Key/作者 voice_id。
        return EffectiveVoiceProfile(
            state="not_provisioned", character_voice_id=None, assistant_voice_id=None
        )
    if settings.dashscope_api_key:
        # 开发机兼容：.env 提供作者 Key 时允许继续使用 pair YAML 作者音色
        return EffectiveVoiceProfile(
            state="env_author",
            character_voice_id=pair_config.character.voice_id or None,
            assistant_voice_id=pair_config.assistant.voice_id or None,
        )
    return EffectiveVoiceProfile(
        state="not_provisioned", character_voice_id=None, assistant_voice_id=None
    )


def effective_pair_config(
    pair_config: PairConfig, voices: EffectiveVoiceProfile
) -> PairConfig:
    """把有效音色写进 pair 配置副本；不可用的说话方 voice_id 置空串。

    VoiceRuntime 的入队路径以空 voice_id 为“音色未生成，跳过合成”
    的信号，不会拿空 ID 或作者 ID 调 DashScope。
    """
    return pair_config.model_copy(
        update={
            "character": pair_config.character.model_copy(
                update={"voice_id": voices.character_voice_id or ""}
            ),
            "assistant": pair_config.assistant.model_copy(
                update={"voice_id": voices.assistant_voice_id or ""}
            ),
        }
    )


def build_real_voice_runtime(
    *,
    settings: Settings,
    orchestrator: ConversationOrchestrator,
    pair_config: PairConfig,
    conversation_id: str,
    on_vad_state: Callable[[str], None],
    on_asr_partial: Callable[[str], None],
    on_error: Callable[[str], None],
    on_tts_state: Callable[[str], None] = lambda _s: None,
    on_text_input: Callable[[str, str], Awaitable[None]] | None = None,
    voices: EffectiveVoiceProfile | None = None,
    account_config: Mapping[str, str] | None = None,
) -> VoiceRuntime:
    """创建供桌面 Sidecar 使用的 VoiceRuntime。

    V0.3.2 M6：只要保存了 Key（账号级或开发机 .env）即可构建——ASR
    不依赖任何音色；TTS 音色按 :func:`resolve_effective_voice_profile`
    的优先级解析，未生成的说话方保持不可用。
    """
    if not settings.dashscope_api_key or (
        account_config is not None
        and "voice.api_key" in account_config
        and not account_config.get("voice.api_key")
    ):
        raise RuntimeError("未配置 DashScope API Key（语音页可保存账号 Key）")

    if voices is None:
        voices = resolve_effective_voice_profile(
            account_config=account_config or {}, settings=settings, pair_config=pair_config
        )
    runtime_pair_config = effective_pair_config(pair_config, voices)

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
        ),
        synthesizer=QwenSpeechSynthesizer(
            api_key=settings.dashscope_api_key,
            ws_url=settings.resolved_ws_url,
        ),
        vad=vad,
        capture_factory=lambda: MicrophoneCapture(block_size=640),
        player=AudioPlayer(sample_rate=24_000),
        queue=SpeechQueue(),
        pair_config=runtime_pair_config,
        conversation_id=conversation_id,
        on_vad_state=on_vad_state,
        on_asr_partial=on_asr_partial,
        on_error=on_error,
        on_tts_state=on_tts_state,
        on_text_input=on_text_input,
    )
