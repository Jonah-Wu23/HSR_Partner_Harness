from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from pair_harness.config.pairs import load_pair_config, load_prompt
from pair_harness.core.contracts import (
    CharacterProgressSummary,
    CharacterResultSummary,
    CharacterTurn,
    DelegationDraft,
    DialogueEvent,
    DialogueRequest,
    MessageSource,
    TaskAmendmentDraft,
    TaskRequestDraft,
)
from pair_harness.core.ports import DialogueModel

# 结构化输出约定：模型可在台词后附 JSON（见 _OUTPUT_FORMAT_INSTRUCTION）。
# 解析失败时降级为纯台词；原始 JSON 绝不进入台词（TTS 只朗读 speech）。
_FALLBACK_SPEECH = "……"


class OpenAICompatibleDialogueModel(DialogueModel):
    """OpenAI 兼容流式对话客户端（角色适配器）。

    从环境变量读取（构造参数可覆盖）：
    - PAIR_HARNESS_DIALOGUE_BASE_URL
    - PAIR_HARNESS_DIALOGUE_API_KEY
    - PAIR_HARNESS_DIALOGUE_MODEL

    O3.2 提示词装配：
    - system = 角色卡（config/prompts/characters/）+ 搭档（助手）表达配置
      （按 ``pair_id`` 从 ``config/pairs`` 加载）+ 输出格式约定；
    - messages = 近期角色对话（user/character 互转 chat 角色）；
    - ``progress_summary`` / ``result_summary`` 以系统消息注入；
    - 输出解析为 :class:`CharacterTurn`：``delegation.type == "task"`` →
      :class:`TaskRequestDraft`，``"amendment"`` → :class:`TaskAmendmentDraft`；
      解析失败降级为纯台词，且原始 JSON 不会作为台词进入 TTS。
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: httpx.Timeout | None = None,
        config_root: Path | None = None,
    ) -> None:
        self.base_url = base_url or os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL", "")
        self.api_key = api_key or os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY", "")
        self.model = model or os.getenv("PAIR_HARNESS_DIALOGUE_MODEL", "")
        self._client = client
        # O3.2：注入的 client 由调用方管理生命周期；自建的由本类负责关闭
        self._owns_client = client is None
        self._timeout = timeout or httpx.Timeout(30.0, connect=10.0)
        self._config_root = config_root

    # ---- client 生命周期（O3.2）----

    def _client_or_raise(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self.base_url:
                raise RuntimeError("PAIR_HARNESS_DIALOGUE_BASE_URL 未配置")
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url, headers=headers, timeout=self._timeout
            )
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """关闭自建 client；注入的 client 交由调用方关闭。"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._owns_client = False

    # ---- 提示词装配（O3.2）----

    def _system_prompt(self, pair_id: str) -> str:
        config = load_pair_config(pair_id, root=self._config_root)
        character_card = load_prompt(config.character.prompt, root=self._config_root)
        assistant_brief = self._assistant_brief(config.assistant.prompt)
        return f"{character_card}\n\n{assistant_brief}\n\n{_OUTPUT_FORMAT_INSTRUCTION}"

    def _assistant_brief(self, prompt_path: str) -> str:
        """从助手提示词取“身份”一节作为搭档表达配置（名称+表达风格）。"""
        prompt = load_prompt(prompt_path, root=self._config_root)
        section = _first_markdown_section(prompt)
        return f"## 你的搭档（助手）\n{section}"

    def _build_messages(self, request: DialogueRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(request.pair_id)}
        ]
        for message in request.recent_messages:
            role = {
                MessageSource.USER: "user",
                MessageSource.CHARACTER: "assistant",
            }.get(message.source)
            if role is None:
                continue
            messages.append({"role": role, "content": message.text})
        if request.progress_summary is not None:
            messages.append(
                {
                    "role": "system",
                    "content": _progress_summary_text(request.progress_summary),
                }
            )
        if request.result_summary is not None:
            messages.append(
                {"role": "system", "content": _result_summary_text(request.result_summary)}
            )
        messages.append({"role": "user", "content": request.user_message.text})
        return messages

    # ---- 输出解析（O3.2）----

    @staticmethod
    def _parse_output(raw_text: str) -> CharacterTurn:
        """把模型输出解析为 CharacterTurn。

        整体或结尾 JSON 对象 → 结构化（speech + delegation）；
        解析失败 → 降级为纯台词（剥离疑似 JSON 残块，原始 JSON 不进 TTS）。
        """
        text = raw_text.strip()
        obj = OpenAICompatibleDialogueModel._try_parse_json(text)
        if obj is not None:
            speech = str(obj.get("speech") or "").strip() or _FALLBACK_SPEECH
            delegation = OpenAICompatibleDialogueModel._parse_delegation(
                obj.get("delegation")
            )
            return CharacterTurn(speech=speech, delegation=delegation)
        cleaned = OpenAICompatibleDialogueModel._strip_json_attempt(text)
        return CharacterTurn(speech=cleaned or _FALLBACK_SPEECH)

    @staticmethod
    def _try_parse_json(text: str) -> dict[str, Any] | None:
        """整体解析；失败时尝试“台词后附 JSON”的尾部对象。"""
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            obj = None
        if isinstance(obj, dict):
            return obj
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start or text[end + 1 :].strip():
            return None
        try:
            obj = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            return None
        return obj if isinstance(obj, dict) else None

    @staticmethod
    def _strip_json_attempt(text: str) -> str:
        """剥离疑似 JSON 输出残块。

        仅当输出以 ``{`` 开头（模型明显在输出 JSON 但格式损坏），或台词
        尾部含 speech/delegation 关键字（JSON 约定字段）时剥离；普通台词
        中的花括号（如 “用 {shutil} 库”）不受影响。
        """
        stripped = text.strip()
        if not stripped:
            return stripped
        start = stripped.find("{")
        if stripped.startswith("{"):
            # 纯 JSON 输出残块（可能未闭合）：整体剥离
            end = stripped.rfind("}")
            return (stripped[end + 1 :] if end != -1 else "").strip()
        if start == -1:
            return stripped
        tail = stripped[start:]
        if "speech" in tail or "delegation" in tail:
            end = tail.rfind("}")
            return (stripped[:start] + (tail[end + 1 :] if end != -1 else "")).strip()
        return stripped

    @staticmethod
    def _parse_delegation(value: object) -> DelegationDraft | None:
        if not isinstance(value, dict):
            return None
        kind = value.get("type")
        instructions = str(value.get("instructions") or "").strip()
        if not instructions:
            return None
        if kind == "task":
            constraints = value.get("constraints") or ()
            if not isinstance(constraints, (list, tuple)):
                constraints = ()
            return TaskRequestDraft(
                instructions=instructions,
                constraints=tuple(str(c) for c in constraints),
            )
        if kind == "amendment":
            target = value.get("target_task_id")
            revision = value.get("revision")
            return TaskAmendmentDraft(
                instructions=instructions,
                target_task_id=str(target) if target else None,
                revision=int(revision) if isinstance(revision, int) and revision >= 1 else None,
            )
        return None

    # ---- 流式对话 ----

    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        client = self._client_or_raise()
        payload = {
            "model": self.model,
            "messages": self._build_messages(request),
            "stream": True,
        }
        text_chunks: list[str] = []
        async with client.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
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
        yield DialogueEvent(
            type="character.final", turn=self._parse_output("".join(text_chunks))
        )


_OUTPUT_FORMAT_INSTRUCTION = """## 输出格式

只输出角色台词本身，台词会进入语音朗读：写纯台词，不含舞台说明、括号、
星号或心理描写。每轮几句话，说完就停。

若要把任务交给搭档，或要修改正在执行的任务，在台词之后另起一行附一个
JSON 对象：

{"speech": "角色台词", "delegation": {"type": "task", "instructions": "任务内容", "constraints": ["约束"]}}

{"speech": "角色台词", "delegation": {"type": "amendment", "instructions": "修改内容", "target_task_id": "任务id", "revision": 2}}

delegation.type 为 "task" 表示新任务，"amendment" 表示修改当前任务；
纯聊天不输出 JSON。"""


def _first_markdown_section(prompt: str) -> str:
    """取提示词中第一个标题（##）之后、下一个标题之前的正文。"""
    lines = prompt.splitlines()
    content: list[str] = []
    for line in lines:
        if line.startswith("#"):
            if any(content):
                break
            continue
        content.append(line)
    return "\n".join(content).strip()


def _progress_summary_text(summary: CharacterProgressSummary) -> str:
    """O3.3：进度摘要约定格式（压缩中性描述，不含命令/路径/输出原文）。"""
    lines = ["[系统信息：任务进度]", "状态：执行中"]
    if summary.total_steps is not None:
        lines.append(f"已完成：{summary.completed_steps}/{summary.total_steps}")
    else:
        lines.append(f"已完成步骤：{summary.completed_steps}")
    lines.append(f"当前：{summary.current_step}")
    return "\n".join(lines)


def _result_summary_text(result: CharacterResultSummary) -> str:
    lines = [
        "[系统信息：任务结果]",
        f"状态：{result.status}",
        f"摘要：{result.summary}",
    ]
    if result.user_visible_changes:
        lines.append("可见变更：" + "、".join(result.user_visible_changes))
    if result.limitations:
        lines.append("局限：" + "；".join(result.limitations))
    if result.pending_questions:
        lines.append("待确认：" + "；".join(result.pending_questions))
    return "\n".join(lines)
