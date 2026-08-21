"""Qwen-Audio-TTS 音色 customization 客户端（V0.3.2 M6）。

供 CLI（``scripts/create_qwen_voice.py``）与桌面命令（``voice.provision``）
共用同一份请求构建、响应解析和错误映射，避免两套实现漂移。

契约依据 ``docs/design/dashscope/千问声音复刻文档.md`` 与
``docs/design/dashscope/千问声音设计文档.md``：

- 复刻：``POST {http_base_url}/services/audio/tts/customization``，
  ``model="voice-enrollment"``，``input.action="create_voice"``，
  ``input.target_model`` 固定 ``VOICE_TTS_MODEL``，``input.prefix``
  （≤10 位小写字母数字），``input.url`` 为 DashScope 可访问的版本化
  HTTPS 参考音频地址；成功读取 ``output.voice_id``。
- 声音设计：同 endpoint，``input.voice_prompt`` + ``input.preview_text``，
  ``target_model`` 同上；成功同样读取 ``output.voice_id``。
- Qwen3-TTS 的 ``qwen-voice-enrollment`` / ``action="create"`` /
  ``input.audio.data``（Base64）属于另一模型系列，本客户端不提供。

错误处理（Let It Fail）：HTTP 状态、DashScope ``code``/``message`` 原样
保留在 :class:`VoiceCustomizationError` 中，绝不合成 voice_id，也绝不把
失败改写成成功。
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pair_harness.voice_models import (
    VOICE_ENROLLMENT_ACTION,
    VOICE_ENROLLMENT_MODEL,
    VOICE_TTS_MODEL,
)

CUSTOMIZATION_PATH = "/services/audio/tts/customization"
DEFAULT_TIMEOUT_S = 120.0

# prefix 只允许小写字母与数字，最长 10 字符（复刻文档要求）
_PREFIX_RE = re.compile(r"^[a-z0-9]{1,10}$")
_AUDIO_MIME_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}


class VoiceCustomizationError(RuntimeError):
    """customization 请求失败；保留真实 HTTP 状态与 DashScope 错误信息。"""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        dashscope_code: str | None = None,
        dashscope_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.dashscope_code = dashscope_code
        self.dashscope_message = dashscope_message


@dataclass(frozen=True)
class CustomizationResult:
    """创建成功的结果：真实响应中的 voice_id 与原始 payload。"""

    voice_id: str
    payload: dict[str, Any]


def normalize_prefix(prefix: str) -> str:
    """校验并规范 prefix：只允许小写字母/数字，最长 10 字符。"""
    normalized = (prefix or "").strip().lower()
    if not _PREFIX_RE.match(normalized):
        raise VoiceCustomizationError(
            f"prefix 必须是 1~10 位小写字母或数字，得到: {prefix!r}"
        )
    return normalized


def build_clone_payload(*, prefix: str, url: str) -> dict[str, Any]:
    """固定复刻 payload，支持服务端 URL 与本地音频 data URI。"""
    normalized_url = (url or "").strip()
    is_remote = normalized_url.startswith(("http://", "https://"))
    is_audio_data = normalized_url.startswith("data:audio/") and ";base64," in normalized_url
    if not (is_remote or is_audio_data):
        raise VoiceCustomizationError(
            "复刻 input.url 必须是 HTTP(S) 音频地址或 data:audio/*;base64, URI"
        )
    return {
        "model": VOICE_ENROLLMENT_MODEL,
        "input": {
            "action": VOICE_ENROLLMENT_ACTION,
            "target_model": VOICE_TTS_MODEL,
            "prefix": normalize_prefix(prefix),
            "url": normalized_url,
        },
    }


def audio_file_to_data_uri(path: Path) -> str:
    """把本地 WAV/MP3/M4A 转为已实测可用的 ``input.url`` data URI。"""
    if not path.is_file():
        raise VoiceCustomizationError(f"参考音频不存在: {path}")
    mime = _AUDIO_MIME_TYPES.get(path.suffix.lower())
    if mime is None:
        raise VoiceCustomizationError(
            f"参考音频格式不支持: {path.suffix or '<无扩展名>'}（仅 WAV/MP3/M4A）"
        )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_design_payload(
    *,
    prefix: str,
    voice_prompt: str,
    preview_text: str,
) -> dict[str, Any]:
    """固定声音设计 payload：与复刻同一 customization 契约，改传描述文本。"""
    return {
        "model": VOICE_ENROLLMENT_MODEL,
        "input": {
            "action": VOICE_ENROLLMENT_ACTION,
            "target_model": VOICE_TTS_MODEL,
            "prefix": normalize_prefix(prefix),
            "voice_prompt": voice_prompt,
            "preview_text": preview_text,
        },
        "parameters": {"sample_rate": 24000, "response_format": "wav"},
    }


def extract_voice_id(payload: dict[str, Any]) -> str:
    """从成功响应提取 ``output.voice_id``；缺失即真实失败，不得合成。"""
    output = payload.get("output") or {}
    voice_id = output.get("voice_id") or ""
    if not voice_id:
        raise VoiceCustomizationError(f"响应中未找到 output.voice_id: {payload}")
    return str(voice_id)


def customization_endpoint(http_base_url: str) -> str:
    return http_base_url.rstrip("/") + CUSTOMIZATION_PATH


# 可注入的 HTTP 传输：(url, headers, body, timeout) -> (status, raw_body)。
# 网络层异常原样上抛，由 _post 统一映射为 VoiceCustomizationError。
PostJson = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


def _urllib_post_json(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        # HTTPError 也是响应：保留真实状态码与响应体（DashScope 错误详情在内）
        return int(exc.code), exc.read()


class QwenVoiceCustomizationClient:
    """Qwen-Audio-TTS 音色 customization 客户端（同步 urllib，可注入传输）。"""

    def __init__(
        self,
        *,
        api_key: str,
        http_base_url: str,
        timeout: float = DEFAULT_TIMEOUT_S,
        transport: PostJson = _urllib_post_json,
    ) -> None:
        if not api_key:
            raise VoiceCustomizationError("缺少 DashScope API Key")
        if not http_base_url:
            raise VoiceCustomizationError("缺少 DashScope 服务地址")
        self._api_key = api_key
        self._http_base_url = http_base_url
        self._timeout = timeout
        self._transport = transport

    def _redact(self, value: object) -> str:
        text = str(value)
        if self._api_key:
            text = text.replace(self._api_key, "<REDACTED_API_KEY>")
        return text

    def _redacted_error(self, exc: VoiceCustomizationError) -> VoiceCustomizationError:
        return VoiceCustomizationError(
            self._redact(exc),
            http_status=exc.http_status,
            dashscope_code=exc.dashscope_code,
            dashscope_message=(
                self._redact(exc.dashscope_message)
                if exc.dashscope_message is not None
                else None
            ),
        )

    @property
    def endpoint(self) -> str:
        return customization_endpoint(self._http_base_url)

    def create_cloned_voice(self, *, prefix: str, url: str) -> CustomizationResult:
        payload = build_clone_payload(prefix=prefix, url=url)
        return self._request(payload)

    def create_designed_voice(
        self,
        *,
        prefix: str,
        voice_prompt: str,
        preview_text: str,
    ) -> CustomizationResult:
        if not voice_prompt.strip():
            raise VoiceCustomizationError("voice_prompt 不能为空")
        if not preview_text.strip():
            raise VoiceCustomizationError("preview_text 不能为空")
        payload = build_design_payload(
            prefix=prefix, voice_prompt=voice_prompt, preview_text=preview_text
        )
        return self._request(payload)

    def _request(self, payload: dict[str, Any]) -> CustomizationResult:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            status, raw = self._transport(self.endpoint, headers, body, self._timeout)
        except VoiceCustomizationError as exc:
            raise self._redacted_error(exc) from exc
        except Exception as exc:  # noqa: BLE001 - 网络层异常类型不稳定
            raise VoiceCustomizationError(
                f"网络请求失败: {self._redact(exc)}"
            ) from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            snippet = raw[:300]
            raise VoiceCustomizationError(
                f"HTTP {status}: 响应不是合法 JSON: {self._redact(snippet)!r}",
                http_status=status,
            ) from exc

        if not isinstance(data, dict):
            raise VoiceCustomizationError(
                f"HTTP {status}: 响应不是 JSON 对象: {self._redact(data)!r}",
                http_status=status,
            )

        # DashScope 失败回执：body 内 code/message 原样保留
        dashscope_code = data.get("code")
        if dashscope_code not in (None, ""):
            raise VoiceCustomizationError(
                f"HTTP {status} DashScope 错误 {dashscope_code}: "
                f"{self._redact(data.get('message', data))}",
                http_status=status,
                dashscope_code=str(dashscope_code),
                dashscope_message=self._redact(data.get("message", "")) or None,
            )
        if status < 200 or status >= 300:
            raise VoiceCustomizationError(
                f"HTTP {status}: {self._redact(data)}",
                http_status=status,
            )
        try:
            voice_id = extract_voice_id(data)
        except VoiceCustomizationError as exc:
            raise self._redacted_error(exc) from exc
        return CustomizationResult(voice_id=voice_id, payload=data)
