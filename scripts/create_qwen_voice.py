#!/usr/bin/env python3
"""创建 Qwen 音色并写回 pair 配置。

子命令：
  clone   —— 声音复刻（voice-enrollment / create_voice，需公网 URL 或本地音频转 data URI）
  design  —— 声音设计（voice_prompt 描述，返回 preview_audio 供试听）
  adopt   —— 把 voice_id 写回 config/pairs/*.yaml（只改对应行）

HTTP 用标准库 urllib 实现；base URL 默认取 DASHSCOPE_BASE_URL 环境变量，
未设置时回退到本项目专属地域端点（用户提供的 DashScope 地址）。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pair_harness.config.pairs import PairConfigError, adopt_voice_id  # noqa: E402


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
CUSTOMIZATION_PATH = "/services/audio/tts/customization"
DEFAULT_TARGET_MODEL = "qwen-audio-3.0-tts-flash"
DEFAULT_SOURCE_DIR = ROOT / "assets" / "reference_voices" / "白厄"
DEFAULT_DESIGN_PROMPT = ROOT / "config" / "voices" / "ancient_machine_prompt.txt"
DEFAULT_PREVIEW_TEXT = "你好，我是神秘的古代机械。核心模块已启动，正在等待指令。"
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


def normalize_prefix(prefix: str) -> str:
    """prefix 只允许小写字母与数字，最长 10 字符。"""
    normalized = re.sub(r"[^a-z0-9]", "", (prefix or "").lower())
    if not normalized:
        raise VoiceCliError(f"prefix 必须包含小写字母/数字，得到: {prefix!r}")
    return normalized[:10]


def data_uri_for(path: Path) -> str:
    mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}.get(
        path.suffix.lower(), "audio/wav"
    )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


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


def build_clone_payload(prefix: str, url: str, target_model: str = DEFAULT_TARGET_MODEL) -> dict:
    return {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": target_model,
            "prefix": prefix,
            "url": url,
        },
    }


def build_design_payload(
    prefix: str,
    voice_prompt: str,
    preview_text: str,
    target_model: str = DEFAULT_TARGET_MODEL,
    model: str = "voice-enrollment",
    action: str = "create_voice",
) -> dict:
    payload = {
        "model": model,
        "input": {
            "action": action,
            "target_model": target_model,
            "voice_prompt": voice_prompt,
            "preview_text": preview_text,
        },
        "parameters": {"sample_rate": 24000, "response_format": "wav"},
    }
    if model == "voice-enrollment":
        payload["input"]["prefix"] = prefix
    else:  # qwen-voice-design 形态用 preferred_name
        payload["input"]["preferred_name"] = prefix
    return payload


def post_customization(payload: dict, base_url: str, timeout: float = 120.0) -> dict:
    url = base_url.rstrip("/") + CUSTOMIZATION_PATH
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise VoiceCliError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise VoiceCliError(f"网络请求失败: {exc.reason}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoiceCliError(f"响应不是合法 JSON: {raw[:300]!r}") from exc
    if data.get("code") not in (None, ""):
        raise VoiceCliError(
            f"API 错误 {data.get('code')}: {data.get('message', data)}"
        )
    return data


def extract_voice_id(result: dict, model: str) -> str:
    output = result.get("output") or {}
    if model == "qwen-voice-design":
        voice = output.get("voice") or ""
        if not voice:
            raise VoiceCliError(f"响应中未找到 output.voice: {result}")
        return str(voice)
    voice_id = output.get("voice_id") or ""
    if not voice_id:
        raise VoiceCliError(f"响应中未找到 output.voice_id: {result}")
    return str(voice_id)


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
    audio_url = (args.url or "").strip()
    audio_note = "公网 URL"
    if not audio_url:
        if args.concat:
            files = sorted(args.source_dir.glob("*.wav"))
            if not files:
                raise VoiceCliError(f"目录中没有 .wav 文件: {args.source_dir}")
            out = ROOT / "assets" / "reference_voices" / "processed" / f"{prefix}_concat.wav"
            concat_wavs(files, out)
            source = out
            audio_note = f"拼接音频 {out.relative_to(ROOT)}"
        else:
            source = pick_longest_wav(args.source_dir)
            audio_note = f"最长单段 {source.name}"
        audio_url = data_uri_for(source)
        audio_note += "（data URI）"

    print(f"[clone] target_model={args.target_model} prefix={prefix} url={audio_note}")
    payload = build_clone_payload(prefix, audio_url, args.target_model)
    try:
        result = post_customization(payload, args.base_url)
    except VoiceCliError as exc:
        if "url" in str(exc).lower():
            raise VoiceCliError(
                f"{exc}\n"
                "提示：Qwen-Audio-TTS 复刻要求音频为公网可访问的 URL，"
                "data URI 可能被拒绝。请把音频上传到公网后重试：\n"
                f"  python scripts/create_qwen_voice.py clone --url https://... --prefix {prefix}\n"
                "或手动调用 API 后用 adopt 写回配置。"
            ) from exc
        raise
    voice_id = extract_voice_id(result, "voice-enrollment")
    print(f"[clone] voice_id={voice_id}")
    print(f"下一步: python scripts/create_qwen_voice.py adopt --pair ... --role ... --voice-id {voice_id}")


def cmd_design(args: argparse.Namespace) -> None:
    prefix = normalize_prefix(args.prefix)
    prompt = args.voice_prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise VoiceCliError(f"voice_prompt 文件为空: {args.voice_prompt_file}")
    preview_text = args.preview_text or DEFAULT_PREVIEW_TEXT
    payload = build_design_payload(
        prefix, prompt, preview_text, args.target_model, args.model, args.action
    )
    print(f"[design] model={args.model} action={args.action} target_model={args.target_model} prefix={prefix}")
    result = post_customization(payload, args.base_url)
    voice_id = extract_voice_id(result, args.model)
    preview = save_preview_audio(result, prefix, ROOT / ".tmp")
    if preview:
        print(f"[design] 预览音频已保存: {preview.relative_to(ROOT)}（请先试听再 adopt）")
    print(f"[design] voice_id={voice_id}")
    print(f"下一步: python scripts/create_qwen_voice.py adopt --pair ... --role ... --voice-id {voice_id}")


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
    clone.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    clone.add_argument("--url", default="", help="公网可访问的音频 URL（优先于本地文件）")
    clone.add_argument("--concat", action="store_true", help="拼接目录内全部 WAV（段间 0.5s 静音）")
    clone.set_defaults(func=cmd_clone)

    design = sub.add_parser("design", help="声音设计：用文字描述生成音色")
    design.add_argument("--prefix", default="ancient_machine")
    design.add_argument("--target-model", default=DEFAULT_TARGET_MODEL)
    design.add_argument("--voice-prompt-file", type=Path, default=DEFAULT_DESIGN_PROMPT)
    design.add_argument("--preview-text", default=DEFAULT_PREVIEW_TEXT)
    design.add_argument("--model", default="voice-enrollment", help="voice-enrollment 或 qwen-voice-design")
    design.add_argument("--action", default="create_voice", help="create_voice 或 create")
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
