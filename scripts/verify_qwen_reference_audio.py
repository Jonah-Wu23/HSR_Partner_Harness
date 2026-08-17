#!/usr/bin/env python3
"""固定千问 TTS 模型参考音频能力真实验证脚本（V0.4.0 逻辑底座，一次性诊断）。

只做真实请求并原样打印响应，不写回任何配置、不生成 mock 结果。
固定契约：``model=voice-enrollment``，``input.action=create_voice``，
``input.target_model=qwen-audio-3.0-tts-flash``（产品常量，不可修改）。

探针序列（按代价从低到高）：
  1. 本地 WAV 以 data URI 塞进 input.url —— 验证本地 Base64 是否被接受；
  2. 本地 Windows 绝对路径塞进 input.url —— 验证本地路径是否被接受；
  3. 公网存在但 404 的 URL —— 验证服务端是否真实拉取 URL；
  4. Qwen3-TTS-VC 形态 input.audio.data —— 验证另一模型系列的 payload 是否被拒绝；
  5. 真实公网 WAV URL（本仓库 raw.githubusercontent.com 资源）—— 成功路径，
     成功时输出真实 voice_id。

凭据：项目 .env 的 DASHSCOPE_API_KEY / DASHSCOPE_BASE_URL；脚本绝不打印 Key。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXED_TARGET_MODEL = "qwen-audio-3.0-tts-flash"
CUSTOMIZATION_PATH = "/services/audio/tts/customization"
LOCAL_WAV = ROOT / "assets" / "reference_voices" / "白厄" / "phainon_concat.wav"
# 已提交到公开仓库的版本化公网音频（main 分支当前字节）。
PUBLIC_WAV_URL = (
    "https://raw.githubusercontent.com/Jonah-Wu23/HSR_Partner_Harness/main/"
    + urllib.parse.quote("assets/reference_voices/白厄/phainon_concat.wav")
)
NOT_FOUND_WAV_URL = (
    "https://raw.githubusercontent.com/Jonah-Wu23/HSR_Partner_Harness/main/"
    "assets/reference_voices/definitely_not_exists.wav"
)
CREATE_PREFIX = "vfylogic"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
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


def post(payload: dict, base_url: str, timeout: float = 120.0) -> tuple[int, str]:
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


def head_status(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, resp.headers.get("Content-Length", "?")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Length", "?")
    except urllib.error.URLError as exc:
        return -1, f"URLError: {exc.reason}"


def clone_payload(prefix: str, url: str) -> dict:
    return {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": FIXED_TARGET_MODEL,
            "prefix": prefix,
            "url": url,
        },
    }


def main() -> int:
    _load_dotenv()
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    base_url = os.environ.get("DASHSCOPE_BASE_URL", "").strip()
    if not api_key or not base_url:
        print("[blocked] 缺少 DASHSCOPE_API_KEY 或 DASHSCOPE_BASE_URL，无法真实验证")
        return 2
    print(f"[env] base_url={base_url}")
    print(f"[env] local wav exists={LOCAL_WAV.is_file()} size={LOCAL_WAV.stat().st_size if LOCAL_WAV.is_file() else 0}")

    print("\n[probe0] 公网 URL 可达性（本机视角，非 DashScope 视角）")
    for label, url in (("public", PUBLIC_WAV_URL), ("notfound", NOT_FOUND_WAV_URL)):
        status, length = head_status(url)
        print(f"  {label}: HEAD status={status} content-length={length} url={url}")

    data_uri = "data:audio/wav;base64," + base64.b64encode(LOCAL_WAV.read_bytes()).decode("ascii")

    probes: list[tuple[str, dict]] = [
        ("1-local-wav-as-data-uri-in-url", clone_payload(CREATE_PREFIX, data_uri)),
        ("2-local-absolute-path-in-url", clone_payload(CREATE_PREFIX, str(LOCAL_WAV))),
        ("3-public-404-url", clone_payload(CREATE_PREFIX, NOT_FOUND_WAV_URL)),
        (
            "4-qwen3tts-vc-style-audio-data",
            {
                "model": "voice-enrollment",
                "input": {
                    "action": "create_voice",
                    "target_model": FIXED_TARGET_MODEL,
                    "prefix": CREATE_PREFIX,
                    "audio": {"data": data_uri},
                },
            },
        ),
        ("5-public-url-success-path", clone_payload(CREATE_PREFIX, PUBLIC_WAV_URL)),
    ]

    for name, payload in probes:
        shown = json.dumps(payload, ensure_ascii=False)
        if len(shown) > 300:
            shown = shown[:300] + f"...(共 {len(shown)} 字符，data URI 已截断)"
        print(f"\n[probe:{name}] request={_redact(shown)}")
        status, body = post(payload, base_url)
        print(f"[probe:{name}] HTTP {status}\n[probe:{name}] body={_redact(body)}")
    print("\n[done] 全部探针已执行；以上为原始响应，未做任何改写")
    return 0


if __name__ == "__main__":
    sys.exit(main())
