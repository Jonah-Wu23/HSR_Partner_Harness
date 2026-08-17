#!/usr/bin/env python3
"""创建 Qwen 音色并写回 pair 配置（V0.3.2 M6 起复用共享 customization 客户端）。

子命令：
  clone   —— 声音复刻（voice-enrollment / create_voice，支持本地音频或公网 URL）
  design  —— 声音设计（voice_prompt 描述，返回 preview_audio 供试听）
  adopt   —— 把 voice_id 写回 config/pairs/*.yaml（只改对应行）

请求构建、响应解析与错误映射统一来自
``pair_harness.adapters.audio.qwen_voice_customization``，与桌面端
``voice.provision`` 命令共用同一实现，避免两套漂移。契约固定为
Qwen-Audio-TTS：model=voice-enrollment、action=create_voice、
target_model=qwen-audio-3.0-tts-flash、复刻传 input.url、成功读
output.voice_id；不提供 Qwen3-TTS 的 qwen-voice-enrollment /
action=create / audio.data 形态。

base URL 默认取 DASHSCOPE_BASE_URL 环境变量，未设置时回退到本项目
专属地域端点（用户提供的 DashScope 地址）。
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pair_harness.adapters.audio.qwen_voice_customization import (  # noqa: E402
    QwenVoiceCustomizationClient,
    VoiceCustomizationError,
    audio_file_to_data_uri,
    normalize_prefix,
)
from pair_harness.config.pairs import PairConfigError, adopt_voice_id  # noqa: E402
from pair_harness.config.voices import ANCIENT_MACHINE_PREVIEW_TEXT  # noqa: E402
from pair_harness.voice_models import VOICE_TTS_MODEL  # noqa: E402


def _load_dotenv(root: Path = ROOT) -> None:
    """轻量加载项目 .env（KEY=VALUE，跳过注释），不覆盖已存在的环境变量。"""
    env_path = root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv()

DEFAULT_BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL",
    "https://llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com/api/v1",
)
DEFAULT_TARGET_MODEL = VOICE_TTS_MODEL
DEFAULT_SOURCE_DIR = ROOT / "assets" / "reference_voices" / "白厄"
DEFAULT_DESIGN_PROMPT = ROOT / "config" / "voices" / "ancient_machine_prompt.txt"
DEFAULT_PREVIEW_TEXT = ANCIENT_MACHINE_PREVIEW_TEXT
SILENCE_SECONDS = 0.5


class VoiceCliError(RuntimeError):
    """CLI 可预期错误（缺少 Key、HTTP 失败、配置缺失等）。"""


def _api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise VoiceCliError(
            "缺少 DASHSCOPE_API_KEY 环境变量（请检查项目 .env 或系统环境）"
        )
    return key


def data_uri_for(path: Path) -> str:
    """向后兼容的 CLI 辅助入口，实际实现与桌面端共用。"""
    return audio_file_to_data_uri(path)


def pick_longest_wav(source_dir: Path) -> Path:
    wavs = sorted(source_dir.glob("*.wav"))
    if not wavs:
        raise VoiceCliError(f"目录中没有 .wav 文件: {source_dir}")
    return max(wavs, key=lambda p: p.stat().st_size)


def concat_wavs(files: list[Path], out_path: Path, silence_s: float = SILENCE_SECONDS) -> Path:
    """拼接多个 WAV（要求参数一致：声道数/采样宽度/采样率），段间插入静音。"""
    if not files:
        raise VoiceCliError("没有可拼接的 WAV 文件")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    first = wave.open(str(files[0]), "rb")
    params = (first.getnchannels(), first.getsampwidth(), first.getframerate())
    first.close()
    for path in files:
        w = wave.open(str(path), "rb")
        got = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        w.close()
        if got != params:
            raise VoiceCliError(
                f"WAV 参数不一致，无法拼接: {path.name} {got} != {params}"
            )
    channels, sampwidth, framerate = params
    silence = b"\x00" * (channels * sampwidth * int(framerate * silence_s))
    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)
        for index, path in enumerate(files):
            if index:
                out.writeframes(silence)
            with wave.open(str(path), "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))
    return out_path


def _client(base_url: str) -> QwenVoiceCustomizationClient:
    try:
        return QwenVoiceCustomizationClient(
            api_key=_api_key(), http_base_url=base_url
        )
    except VoiceCustomizationError as exc:
        raise VoiceCliError(str(exc)) from exc


def save_preview_audio(result: dict, prefix: str, out_dir: Path) -> Path | None:
    output = result.get("output") or {}
    preview = output.get("preview_audio")
    if not preview:
        return None
    data = preview.get("data") if isinstance(preview, dict) else preview
    if not data:
        return None
    if isinstance(data, str) and data.startswith("data:"):
        data = data.split(",", 1)[1]
    raw = base64.b64decode(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{prefix}_preview.wav"
    out.write_bytes(raw)
    return out


# ---------------------------------------------------------------- 子命令

def cmd_clone(args: argparse.Namespace) -> None:
    prefix = normalize_prefix(args.prefix)
    if args.file is not None and args.url:
        raise VoiceCliError("clone 的 --file 与 --url 只能选择一个")
    if args.file is not None:
        try:
            audio_url = audio_file_to_data_uri(args.file)
        except VoiceCustomizationError as exc:
            raise VoiceCliError(str(exc)) from exc
        source_label = str(args.file)
    else:
        audio_url = (args.url or "").strip()
        source_label = "公网 URL"
    if not audio_url:
        raise VoiceCliError(
            "clone 必须提供 --file 本地参考音频或 --url HTTP(S) 音频地址"
        )

    print(f"[clone] target_model={args.target_model} prefix={prefix} source={source_label}")
    if args.target_model != DEFAULT_TARGET_MODEL:
        raise VoiceCliError(
            f"target_model 固定为 {DEFAULT_TARGET_MODEL}（V0.3.2 冻结契约），"
            f"得到 {args.target_model}"
        )
    client = _client(args.base_url)
    try:
        result = client.create_cloned_voice(prefix=prefix, url=audio_url)
    except VoiceCustomizationError as exc:
        raise VoiceCliError(str(exc)) from exc
    print(f"[clone] voice_id={result.voice_id}")
    print(f"下一步: python scripts/create_qwen_voice.py adopt --pair ... --role ... --voice-id {result.voice_id}")


def cmd_design(args: argparse.Namespace) -> None:
    prefix = normalize_prefix(args.prefix)
    prompt = args.voice_prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise VoiceCliError(f"voice_prompt 文件为空: {args.voice_prompt_file}")
    preview_text = args.preview_text or DEFAULT_PREVIEW_TEXT
    if args.target_model != DEFAULT_TARGET_MODEL:
        raise VoiceCliError(
            f"target_model 固定为 {DEFAULT_TARGET_MODEL}（V0.3.2 冻结契约），"
            f"得到 {args.target_model}"
        )
    print(f"[design] model=voice-enrollment action=create_voice target_model={args.target_model} prefix={prefix}")
    client = _client(args.base_url)
    try:
        result = client.create_designed_voice(
            prefix=prefix, voice_prompt=prompt, preview_text=preview_text
        )
    except VoiceCustomizationError as exc:
        raise VoiceCliError(str(exc)) from exc
    preview = save_preview_audio(result.payload, prefix, ROOT / ".tmp")
    if preview:
        print(f"[design] 预览音频已保存: {preview.relative_to(ROOT)}（请先试听再 adopt）")
    print(f"[design] voice_id={result.voice_id}")
    print(f"下一步: python scripts/create_qwen_voice.py adopt --pair ... --role ... --voice-id {result.voice_id}")


def cmd_adopt(args: argparse.Namespace) -> None:
    if not args.pair.is_file():
        raise VoiceCliError(f"pair 文件不存在: {args.pair}")
    old_line = adopt_voice_id(args.pair, args.role, args.voice_id, force=args.force)
    print(f"[adopt] {args.role}.voice_id 已更新: {old_line.strip()!r} -> {args.voice_id}")
    print(f"[adopt] 文件: {args.pair}")


# ---------------------------------------------------------------- CLI 入口

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="create_qwen_voice",
        description="创建 Qwen 音色（复刻/设计）并写回 pair 配置",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"DashScope API 基址（默认 {DEFAULT_BASE_URL}）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    clone = sub.add_parser("clone", help="声音复刻：上传参考音频创建音色")
    clone.add_argument("--prefix", default="phainon", help="音色前缀（小写字母数字 ≤10）")
    clone.add_argument("--target-model", default=DEFAULT_TARGET_MODEL)
    clone.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help=argparse.SUPPRESS)
    clone.add_argument("--file", type=Path, help="本地 WAV/MP3/M4A 参考音频（转为 data URI 提交）")
    clone.add_argument("--url", default="", help="DashScope 服务端可下载的 HTTP(S) 音频 URL")
    clone.add_argument("--concat", action="store_true", help=argparse.SUPPRESS)
    clone.set_defaults(func=cmd_clone)

    design = sub.add_parser("design", help="声音设计：用文字描述生成音色")
    design.add_argument("--prefix", default="ancient_machine")
    design.add_argument("--target-model", default=DEFAULT_TARGET_MODEL)
    design.add_argument("--voice-prompt-file", type=Path, default=DEFAULT_DESIGN_PROMPT)
    design.add_argument("--preview-text", default=DEFAULT_PREVIEW_TEXT)
    design.set_defaults(func=cmd_design)

    adopt = sub.add_parser("adopt", help="把 voice_id 写回 pair YAML")
    adopt.add_argument("--pair", type=Path, required=True, help="config/pairs/*.yaml")
    adopt.add_argument("--role", choices=("character", "assistant"), required=True)
    adopt.add_argument("--voice-id", required=True)
    adopt.add_argument("--force", action="store_true", help="覆盖已启用的真实 voice_id")
    adopt.set_defaults(func=cmd_adopt)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except VoiceCliError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except PairConfigError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
