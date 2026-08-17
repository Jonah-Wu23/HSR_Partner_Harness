from __future__ import annotations

import os
from dataclasses import dataclass
from collections.abc import Mapping
from urllib.parse import urlsplit

from pair_harness.voice_models import VOICE_ASR_MODEL, VOICE_TTS_MODEL


@dataclass(frozen=True)
class Settings:
    """应用配置，全部来自环境变量（B1/B2：密钥只经环境变量进入进程）。

    - 对话 API（B1）：PAIR_HARNESS_DIALOGUE_BASE_URL / _API_KEY / _MODEL
    - Codex（B1）：PAIR_HARNESS_CODEX_BIN
    - DashScope 语音（B2）：DASHSCOPE_API_KEY 及可选的 HOST/WS_URL/HTTP_URL 覆盖

    V0.3.2 M6（计划 5.17 节）：ASR/TTS 模型是产品不可变常量
    ``VOICE_ASR_MODEL`` / ``VOICE_TTS_MODEL``，不再读取用户可控的
    ``PAIR_HARNESS_QWEN_ASR_MODEL`` / ``PAIR_HARNESS_QWEN_TTS_MODEL``，
    也不从账号配置读取语音模型。字段保留只为既有调用点的只读便捷。
    """

    codex_bin: str = "codex"
    dialogue_base_url: str | None = None
    dialogue_api_key: str | None = None
    dialogue_model: str | None = None

    # —— B2 新增：DashScope 语音配置 ——
    dashscope_api_key: str | None = None          # DASHSCOPE_API_KEY
    dashscope_host: str = "dashscope.aliyuncs.com"
    dashscope_ws_url: str | None = None           # 覆盖项；默认由 host 推导
    dashscope_http_url: str | None = None         # 覆盖项；默认由 host 推导
    @classmethod
    def overlay(cls, base: "Settings", account_config: Mapping[str, str]) -> "Settings":
        """V0.2 M3：用账号级配置覆盖环境默认（账号配置优先）。

        键名与 config.set 的扁平键一致：dialogue.base_url / dialogue.api_key /
        dialogue.model / voice.base_url / voice.api_key / engine。
        未提供的键保留环境值。

        V0.3.2 M6：账号已保存 voice.api_key 时账号配置优先于 .env 的
        DASHSCOPE_API_KEY（开发机兼容入口）；语音模型不接受账号级覆盖。
        """
        # ``None`` means the account has never configured the key/address and
        # may use the development environment fallback.  An empty string is a
        # deliberate clear and must not silently recover the old environment
        # credential.
        voice_api_key = (
            account_config["voice.api_key"]
            if "voice.api_key" in account_config
            else base.dashscope_api_key
        )
        voice_http_url = (
            account_config["voice.base_url"]
            if "voice.base_url" in account_config
            else base.dashscope_http_url
        )
        voice_host = account_config.get("voice.host") or cls._host_from_url(
            voice_http_url
        )
        return cls(
            codex_bin=account_config.get("codex.bin") or base.codex_bin,
            dialogue_base_url=(
                account_config.get("dialogue.base_url") or base.dialogue_base_url
            ),
            dialogue_api_key=(
                account_config.get("dialogue.api_key") or base.dialogue_api_key
            ),
            dialogue_model=account_config.get("dialogue.model") or base.dialogue_model,
            dashscope_api_key=voice_api_key,
            dashscope_host=voice_host or base.dashscope_host,
            dashscope_ws_url=base.dashscope_ws_url,
            dashscope_http_url=voice_http_url,
        )

    @property
    def qwen_asr_model(self) -> str:
        """兼容旧调用点；ASR 模型不是可配置字段。"""
        return VOICE_ASR_MODEL

    @property
    def qwen_tts_model(self) -> str:
        """兼容旧调用点；TTS 模型不是可配置字段。"""
        return VOICE_TTS_MODEL

    @staticmethod
    def _host_from_url(url: str | None) -> str | None:
        if not url:
            return None
        parsed = urlsplit(url if "://" in url else f"https://{url}")
        return parsed.hostname

    @property
    def resolved_ws_url(self) -> str:
        """WebSocket 地址：默认按专属端点推导（B2 联调验证点 R5）。

        推导规则与 docs/design/千问语音识别文档.md 一致：北京/新加坡
        Key 与地址必须同地域，ws 地址由 HTTP 服务地址的 host 推导
        （北京 ``wss://{host}.cn-beijing.../api-ws/v1/inference``、
        新加坡 ``wss://{host}.ap-southeast-1.../api-ws/v1/inference``），
        ASR 与 TTS 共用同一推导结果。
        """
        return self.dashscope_ws_url or f"wss://{self.dashscope_host}/api-ws/v1/inference"

    @property
    def resolved_http_url(self) -> str:
        """DashScope HTTP 地址：默认按专属端点推导。"""
        if self.dashscope_http_url is not None:
            return self.dashscope_http_url.rstrip("/")
        return f"https://{self.dashscope_host}/api/v1"

    @classmethod
    def from_environment(cls) -> "Settings":
        configured_host = os.getenv("PAIR_HARNESS_DASHSCOPE_HOST")
        if not configured_host:
            base_url = os.getenv("DASHSCOPE_BASE_URL", "")
            if base_url:
                parsed = urlsplit(
                    base_url if "://" in base_url else f"https://{base_url}"
                )
                configured_host = parsed.hostname
        return cls(
            codex_bin=(
                os.getenv("PAIR_HARNESS_CODEX_BIN")
                or os.getenv("PAIR_HARNESS_BUNDLED_CODEX_BIN")
                or "codex"
            ),
            dialogue_base_url=os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL"),
            dialogue_api_key=os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY"),
            dialogue_model=os.getenv("PAIR_HARNESS_DIALOGUE_MODEL"),
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
            dashscope_host=configured_host or "dashscope.aliyuncs.com",
            dashscope_ws_url=os.getenv("PAIR_HARNESS_DASHSCOPE_WS_URL"),
            dashscope_http_url=os.getenv("PAIR_HARNESS_DASHSCOPE_HTTP_URL"),
            # V0.3.2 M6：不读取 PAIR_HARNESS_QWEN_ASR_MODEL /
            # PAIR_HARNESS_QWEN_TTS_MODEL；模型固定为产品常量。
        )
