from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

from pair_harness.core.contracts import CharacterTurn, DialogueEvent, DialogueRequest
from pair_harness.core.ports import DialogueModel


class OpenAICompatibleDialogueModel(DialogueModel):
    """OpenAI 兼容流式对话客户端骨架。

    从环境变量读取：
    - PAIR_HARNESS_DIALOGUE_BASE_URL
    - PAIR_HARNESS_DIALOGUE_API_KEY
    - PAIR_HARNESS_DIALOGUE_MODEL
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url or os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL", "")
        self.api_key = api_key or os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY", "")
        self.model = model or os.getenv("PAIR_HARNESS_DIALOGUE_MODEL", "")
        self._client = client

    def _client_or_raise(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if not self.base_url:
            raise RuntimeError("PAIR_HARNESS_DIALOGUE_BASE_URL 未配置")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(base_url=self.base_url, headers=headers)

    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        client = self._client_or_raise()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": request.user_message.text}],
            "stream": True,
        }
        async with client.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
            text_chunks: list[str] = []
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    text_chunks.append(delta)
                    yield DialogueEvent(type="speech.delta", delta=delta)
        speech = "".join(text_chunks)
        yield DialogueEvent(type="character.final", turn=CharacterTurn(speech=speech))
