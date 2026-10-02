# 创建 Qwen 音色并写回 pair 配置：clone 声音复刻、design 声音设计、adopt 把 voice_id 写回
# config/pairs/*.yaml。请求与错误映射复用 pair_harness.adapters.audio.qwen_voice_customization，
# 与桌面端 voice.provision 共用同一实现。base URL 默认取 DASHSCOPE_BASE_URL 环境变量。
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# 脚本可在未安装包时直接运行，先把 src 加入导入路径。
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

load_dotenv(ROOT / ".env", encoding="utf-8-sig")

DEFAULT_BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL",
    "https://llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com/api/v1",
)
DEFAULT_TARGET_MODEL = VOICE_TTS_MODEL
DEFAULT_DESIGN_PROMPT = ROOT / "config" / "voices" / "ancient_machine_prompt.txt"
DEFAULT_PREVIEW_TEXT = ANCIENT_MACHINE_PREVIEW_TEXT


class VoiceCliError(RuntimeError):
    """CLI 可预期错误（缺少 Key、HTTP 失败、配置缺失等）。"""


def _api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise VoiceCliError(
            "缺少 DASHSCOPE_API_KEY 环境变量（请检查项目 .env 或系统环境）"
        )
    return key


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
            f"target_model 固定为 {DEFAULT_TARGET_MODEL}，得到 {args.target_model}"
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
            f"target_model 固定为 {DEFAULT_TARGET_MODEL}，得到 {args.target_model}"
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
    old_voice_id = adopt_voice_id(args.pair, args.role, args.voice_id, force=args.force)
    print(f"[adopt] {args.role}.voice_id 已更新: {old_voice_id!r} -> {args.voice_id}")
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
    clone.add_argument("--file", type=Path, help="本地 WAV/MP3/M4A 参考音频（转为 data URI 提交）")
    clone.add_argument("--url", default="", help="DashScope 服务端可下载的 HTTP(S) 音频 URL")
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
