from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """应用配置，全部来自环境变量（B1/B2：密钥只经环境变量进入进程）。

    - 对话 API（B1）：PAIR_HARNESS_DIALOGUE_BASE_URL / _API_KEY / _MODEL
    - Codex（B1）：PAIR_HARNESS_CODEX_BIN
    - DashScope 语音（B2）：DASHSCOPE_API_KEY 及可选的 HOST/WS_URL/HTTP_URL 覆盖
    """

    codex_bin: str = "codex"
    dialogue_base_url: str | None = None
    dialogue_api_key: str | None = None
    dialogue_model: str | None = None

    # —— B2 新增：DashScope 语音配置 ——
    dashscope_api_key: str | None = None          # DASHSCOPE_API_KEY
    dashscope_host: str = "llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com"
    dashscope_ws_url: str | None = None           # 覆盖项；默认由 host 推导
    dashscope_http_url: str | None = None         # 覆盖项；默认由 host 推导
    qwen_asr_model: str = "qwen-audio-3.0-asr-flash-streaming"
    qwen_tts_model: str = "qwen-audio-3.0-tts-flash"

    @property
    def resolved_ws_url(self) -> str:
        """WebSocket 地址：默认按专属端点推导（B2 联调验证点 R5）。"""
        return self.dashscope_ws_url or f"wss://{self.dashscope_host}/api-ws/v1/inference"

    @property
    def resolved_http_url(self) -> str:
        """DashScope HTTP 地址：默认按专属端点推导。"""
        return self.dashscope_http_url or f"https://{self.dashscope_host}/api/v1"

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            codex_bin=os.getenv("PAIR_HARNESS_CODEX_BIN", "codex"),
            dialogue_base_url=os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL"),
            dialogue_api_key=os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY"),
            dialogue_model=os.getenv("PAIR_HARNESS_DIALOGUE_MODEL"),
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
            dashscope_host=os.getenv(
                "PAIR_HARNESS_DASHSCOPE_HOST",
                "llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com",
            ),
            dashscope_ws_url=os.getenv("PAIR_HARNESS_DASHSCOPE_WS_URL"),
            dashscope_http_url=os.getenv("PAIR_HARNESS_DASHSCOPE_HTTP_URL"),
            qwen_asr_model=os.getenv(
                "PAIR_HARNESS_QWEN_ASR_MODEL", "qwen-audio-3.0-asr-flash-streaming"
            ),
            qwen_tts_model=os.getenv(
                "PAIR_HARNESS_QWEN_TTS_MODEL", "qwen-audio-3.0-tts-flash"
            ),
        )
