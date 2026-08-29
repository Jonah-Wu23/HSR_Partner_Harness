#!/usr/bin/env python3
"""V0.3.5 参考音频能力增补真实验证（强逻辑 AI L9）。

补齐《千问参考音频能力验证记录》2026-08-16 未实测项：
  P1. MP3 本地文件转 data URI 提交（clone）；
  P2. M4A 本地文件转 data URI 提交（clone）；
  P3. 61 秒 WAV（超 60 秒时长边界，大小界内）——观察服务端真实裁决；
  P4. 55 秒 / 10.56MB 48kHz 立体声 WAV（超 10MB 大小边界，时长界内）；
  P5. 声音设计 voice_prompt + preview_text 真实请求（无 url）。

固定契约不变：model=voice-enrollment，input.action=create_voice，
input.target_model=qwen-audio-3.0-tts-flash。只做真实请求、原样打印响应，
不写回配置、不生成 mock 结果、绝不打印 Key。
样本由 scripts 同目录 .tmp/v035_audio 下的 ffmpeg 产物提供。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = Path(os.environ.get("PAIR_HARNESS_ENV_FILE") or (ROOT / ".env"))
SAMPLES = ROOT / ".tmp" / "v035_audio"
FIXED_TARGET_MODEL = "qwen-audio-3.0-tts-flash"
CUSTOMIZATION_PATH = "/services/audio/tts/customization"
PREFIX = "vfy035a"


def _load_dotenv() -> None:
    if not ENV_PATH.is_file():
        print(f"[blocked] 未找到 .env：{ENV_PATH}")
        sys.exit(2)
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _redact(text: str) -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if key and key in text:
        text = text.replace(key, "<REDACTED_API_KEY>")
    return text


def post(payload: dict, base_url: str, timeout: float = 180.0) -> tuple[int, str]:
    url = base_url.rstrip("/") + CUSTOMIZATION_PATH
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ.get('DASHSCOPE_API_KEY', '')}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return -1, f"URLError: {exc.reason}"


def clone_payload(prefix: str, data_uri: str) -> dict:
    return {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": FIXED_TARGET_MODEL,
            "prefix": prefix,
            "url": data_uri,
        },
    }


def design_payload(prefix: str, voice_prompt: str, preview_text: str) -> dict:
    return {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": FIXED_TARGET_MODEL,
            "prefix": prefix,
            "voice_prompt": voice_prompt,
            "preview_text": preview_text,
        },
    }


def data_uri_of(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return (
        f"data:{mime};base64,"
        + base64.b64encode(path.read_bytes()).decode("ascii")
    )


def main() -> int:
    _load_dotenv()
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    base_url = os.environ.get("DASHSCOPE_BASE_URL", "").strip()
    if not api_key or not base_url:
        print("[blocked] 缺少 DASHSCOPE_API_KEY 或 DASHSCOPE_BASE_URL")
        return 2
    print(f"[env] base_url={base_url}")
    print(f"[env] samples dir={SAMPLES} exists={SAMPLES.is_dir()}")

    mp3 = SAMPLES / "phainon.mp3"
    m4a = SAMPLES / "phainon.m4a"
    wav61 = SAMPLES / "wav61s.wav"
    wav10mb = SAMPLES / "wav_10mb.wav"
    for probe_file in (mp3, m4a, wav61, wav10mb):
        print(
            f"[sample] {probe_file.name} exists={probe_file.is_file()} "
            f"size={probe_file.stat().st_size if probe_file.is_file() else 0}"
        )

    probes: list[tuple[str, dict]] = [
        ("P1-mp3-data-uri", clone_payload(PREFIX + "m", data_uri_of(mp3))),
        ("P2-m4a-data-uri", clone_payload(PREFIX + "n", data_uri_of(m4a))),
        ("P3-wav-61s-over-duration", clone_payload(PREFIX + "o", data_uri_of(wav61))),
        ("P4-wav-10mb-over-size", clone_payload(PREFIX + "p", data_uri_of(wav10mb))),
        (
            "P5-design-voice-prompt",
            design_payload(
                PREFIX + "q",
                "温柔的青年男性声音，语速平缓，尾音干净，不带口音，"
                "适合近距离轻声讲述",
                "你好，很高兴在这里遇见你。",
            ),
        ),
    ]

    for name, payload in probes:
        shown = json.dumps(payload, ensure_ascii=False)
        if len(shown) > 320:
            shown = shown[:320] + f"...(共 {len(shown)} 字符，data URI 已截断)"
        print(f"\n[probe:{name}] request={_redact(shown)}")
        status, body = post(payload, base_url)
        print(f"[probe:{name}] HTTP {status}\n[probe:{name}] body={_redact(body)}")
    print("\n[done] 全部探针已执行；以上为原始响应，未做任何改写")
    return 0


if __name__ == "__main__":
    sys.exit(main())
