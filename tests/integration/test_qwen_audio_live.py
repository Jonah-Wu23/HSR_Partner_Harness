"""B2 真实联调：Qwen 流式 ASR / TTS（live_qwen marker，默认跳过）。

双重门槛：``live_qwen`` marker 选中本文件，``RUN_LIVE_QWEN=1`` 且
``DASHSCOPE_API_KEY`` 存在才真正执行::

  RUN_LIVE_QWEN=1 PYTHONIOENCODING=utf-8 \\
    .venv/Scripts/python.exe -m pytest -q -m live_qwen \\
    tests/integration/test_qwen_audio_live.py

覆盖设计文档 §6.2：
- ASR：白厄参考语音（48 kHz WAV）numpy 线性插值重采样为 16 kHz PCM，
  按 100 ms / 3200 B 节奏推入 ``QwenStreamingRecognizer.stream_transcribe``，
  断言最终合并文本包含素材中的连续关键词（“回头见”）；对应验证点 R3/R5。
- TTS：用 pair 配置（或 ``PAIR_HARNESS_TEST_VOICE_ID``）的 voice_id 合成
  “你好，我是白厄。”，断言产出 PCM 总时长 > 0.5 s（24 kHz），并写入
  ``.tmp/`` 供人工试听；对应验证点 R3。

真实 voice_id 写回 pair YAML 前（B2.8 adopt），TTS 用例自动跳过。
"""

from __future__ import annotations

import asyncio
import os
import re
import wave
from pathlib import Path

import numpy as np
import pytest

from pair_harness.adapters.audio.qwen_asr import QwenStreamingRecognizer
from pair_harness.adapters.audio.qwen_tts import QwenSpeechSynthesizer, TTS_SAMPLE_RATE
from pair_harness.config.pairs import load_pair_config
from pair_harness.core.contracts import AsrEvent, SpeechRequest
from pair_harness.settings import Settings

pytestmark = pytest.mark.live_qwen

PAIR_ID = "phainon_ancient_machine"
REFERENCE_DIR = Path(__file__).resolve().parents[2] / "assets" / "reference_voices" / "白厄"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / ".tmp"
ASR_CHUNK_BYTES = 3200  # 100 ms @ 16 kHz / 16 bit 单声道
ASR_PACE_S = 0.1
ASR_KEYWORD = "回头见"
TTS_TEXT = "你好，我是白厄。"
COLLECT_TIMEOUT_S = 180.0


def _reference_wav() -> Path:
    """选择包含“回头见”素材的参考语音（9.67 s 段）。"""
    matches = [p for p in sorted(REFERENCE_DIR.glob("*.wav")) if "回头见" in p.name]
    if not matches:
        raise FileNotFoundError(f"参考语音目录中未找到含“回头见”的 WAV: {REFERENCE_DIR}")
    return matches[0]


def resample_to_16k_pcm(path: Path) -> bytes:
    """读取 16 bit PCM WAV，线性插值重采样为 16 kHz 单声道 int16 字节。

    不引入额外解码依赖（numpy 线性插值，设计 §6.2）。
    """
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        nframes = w.getnframes()
        raw = w.readframes(nframes)
    if sampwidth != 2:
        raise ValueError(f"仅支持 16 bit WAV: {path} (sampwidth={sampwidth})")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    target = int(round(nframes * 16_000 / framerate))
    if target != len(data):
        data = np.interp(
            np.linspace(0.0, 1.0, target), np.linspace(0.0, 1.0, len(data)), data
        )
    return data.astype("<i2").tobytes()


async def chunked_audio(pcm: bytes, chunk: int = ASR_CHUNK_BYTES, pace: float = ASR_PACE_S):
    """按固定块长与节奏产出 PCM 块（100 ms 一段，模拟实时麦克风流）。"""
    for offset in range(0, len(pcm), chunk):
        yield pcm[offset : offset + chunk]
        if pace > 0:
            await asyncio.sleep(pace)


async def collect(agen, timeout: float = COLLECT_TIMEOUT_S):
    """带超时地消费异步生成器，防止真实服务悬挂测试。"""
    events: list[AsrEvent] = []

    async def run() -> None:
        async for event in agen:
            events.append(event)

    await asyncio.wait_for(run(), timeout=timeout)
    return events


@pytest.fixture(scope="module")
def live_qwen_env() -> Settings:
    """双重门槛：RUN_LIVE_QWEN=1 且 DASHSCOPE_API_KEY 存在，否则跳过。"""
    if os.getenv("RUN_LIVE_QWEN") != "1":
        pytest.skip("未设置 RUN_LIVE_QWEN=1（live_qwen 双重门槛）")
    settings = Settings.from_environment()
    if not settings.dashscope_api_key:
        pytest.skip("缺少 DASHSCOPE_API_KEY 环境变量")
    return settings


@pytest.fixture(scope="module")
def live_voice_id(live_qwen_env: Settings) -> str:
    """TTS 音色：优先环境变量覆盖，否则取 pair 配置；占位 demo-* 时跳过。"""
    voice_id = os.getenv("PAIR_HARNESS_TEST_VOICE_ID", "").strip()
    if not voice_id:
        pair = load_pair_config(PAIR_ID)
        voice_id = pair.character.voice_id
    if voice_id.startswith("demo-"):
        pytest.skip(
            f"pair 配置 voice_id 仍是占位 {voice_id!r}；"
            "请先 scripts/create_qwen_voice.py adopt 真实音色，"
            "或设置 PAIR_HARNESS_TEST_VOICE_ID"
        )
    return voice_id


@pytest.mark.asyncio
async def test_live_asr_transcribes_reference_clip(live_qwen_env: Settings) -> None:
    """白厄 48 kHz 参考语音重采样后流式识别，final 文本包含“回头见”。"""
    wav_path = _reference_wav()
    pcm = resample_to_16k_pcm(wav_path)
    assert len(pcm) % ASR_CHUNK_BYTES == 0 or len(pcm) > ASR_CHUNK_BYTES
    assert len(pcm) / 2 / 16_000 > 3.0, "参考音频过短，无法验证流式识别"

    recognizer = QwenStreamingRecognizer(
        api_key=live_qwen_env.dashscope_api_key,
        ws_url=live_qwen_env.resolved_ws_url,
        model=live_qwen_env.qwen_asr_model,
    )
    events = await collect(recognizer.stream_transcribe(chunked_audio(pcm)))

    errors = [e.error for e in events if e.type == "error"]
    assert not errors, f"ASR 服务错误: {errors}"
    finals = [e.text for e in events if e.type == "final"]
    assert finals, f"未收到 final 事件（共 {len(events)} 个事件）"

    merged = "".join(finals)
    assert ASR_KEYWORD in merged, (
        f"识别结果未包含 {ASR_KEYWORD!r}: {merged!r}\n"
        f"partials: {[e.text for e in events if e.type == 'partial'][-5:]}"
    )


@pytest.mark.asyncio
async def test_live_tts_synthesizes_phainon_line(
    live_qwen_env: Settings, live_voice_id: str
) -> None:
    """用 pair 音色合成“你好，我是白厄。”，PCM 总时长 > 0.5 s，写入 .tmp 试听。"""
    synthesizer = QwenSpeechSynthesizer(
        api_key=live_qwen_env.dashscope_api_key,
        ws_url=live_qwen_env.resolved_ws_url,
        model=live_qwen_env.qwen_tts_model,
    )
    request = SpeechRequest(text=TTS_TEXT, voice_id=live_voice_id, message_id="live-tts")

    chunks = await _collect_tts(synthesizer, request)
    pcm_parts: list[bytes] = []
    saw_final = False
    for chunk in chunks:
        if chunk.pcm:
            pcm_parts.append(chunk.pcm)
        if chunk.final:
            saw_final = True

    assert saw_final, "TTS 流未收到 final 收尾块"
    total_bytes = sum(len(part) for part in pcm_parts)
    duration_s = total_bytes / 2 / TTS_SAMPLE_RATE
    assert duration_s > 0.5, f"合成 PCM 过短: {duration_s:.3f}s ({total_bytes} B)"

    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", live_voice_id)
    out_path = OUTPUT_DIR / f"live_tts_{safe_id}.wav"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(TTS_SAMPLE_RATE)
        out.writeframes(b"".join(pcm_parts))
    print(f"\n[TTS] 已写入 {out_path.relative_to(OUTPUT_DIR.parent)}（{duration_s:.2f}s）")


async def _collect_tts(synthesizer, request, timeout: float = COLLECT_TIMEOUT_S):
    """带超时地消费 TTS 流并收集全部 AudioChunk，避免真实服务悬挂。"""
    chunks: list = []
    agen = synthesizer.synthesize(request)
    try:

        async def run() -> None:
            async for chunk in agen:
                chunks.append(chunk)

        await asyncio.wait_for(run(), timeout=timeout)
    finally:
        await agen.aclose()
    return chunks
