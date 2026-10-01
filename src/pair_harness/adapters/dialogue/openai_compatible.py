from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from pair_harness.config.pairs import load_pair_config, load_prompt
from pair_harness.adapters.dialogue.incremental_json import IncrementalJsonSpeechParser
from pair_harness.config.providers import (
    deepseek_request_extras,
    is_deepseek_host,
)
from pair_harness.core.character_prompt_assembler import AssembledPrompt
from pair_harness.core.contracts import (
    CharacterProgressSummary,
    CharacterResultSummary,
    CharacterTurn,
    DelegationDraft,
    DialogueEvent,
    DialogueRequest,
    MemoryDraft,
    Message,
    MessageSource,
    ProjectRuntimeContext,
    TaskAmendmentDraft,
    TaskRequestDraft,
)
from pair_harness.core.ports import DialogueModel

logger = logging.getLogger(__name__)


class DialogueProtocolError(ValueError):
    """模型输出或 Chat Completions 响应不符合协议，消息带原始数据。"""


# (conversation_id, recent_messages, turn_index) → 聊天绑定的自定义角色卡装配结果；
# 未绑定或卡已删除时返回 None，角色侧文本使用内置搭档配置。
CharacterPromptResolver = Callable[[str, tuple[Message, ...], int], AssembledPrompt | None]


class OpenAICompatibleDialogueModel(DialogueModel):
    """OpenAI Chat Completions 兼容端点上的角色对话、标题、摘要与 JSON 补全。

    角色回合的 system 由角色卡、助手身份一节与运行时输出协议组成，模型每轮
    只输出一个 JSON 对象。构造参数缺省时读取 PAIR_HARNESS_DIALOGUE_BASE_URL、
    PAIR_HARNESS_DIALOGUE_API_KEY、PAIR_HARNESS_DIALOGUE_MODEL。
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
        temperature: float | None = None,
        character_prompt_resolver: CharacterPromptResolver | None = None,
    ) -> None:
        self.base_url = base_url or os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL", "")
        self.api_key = api_key or os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY", "")
        self.model = model or os.getenv("PAIR_HARNESS_DIALOGUE_MODEL", "")
        self._client = client
        # 注入的 client 由调用方关闭，自建的由本类关闭。
        self._owns_client = client is None
        self._timeout = timeout or httpx.Timeout(30.0, connect=10.0)
        self._config_root = config_root
        # 角色回合的采样温度；None 表示使用服务端默认值。
        self.temperature = temperature
        self.character_prompt_resolver = character_prompt_resolver

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
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._owns_client = False

    def _system_prompt(self, pair_id: str, assembled: AssembledPrompt | None) -> str:
        """角色侧文本（自定义角色卡装配结果或内置角色卡）+ 助手身份 + 输出协议。"""
        config = load_pair_config(pair_id, root=self._config_root)
        if assembled is not None:
            character_text = assembled.system_text
        else:
            character_text = load_prompt(config.character.prompt, root=self._config_root)
        assistant_brief = self._assistant_brief(config.assistant.prompt)
        return f"{character_text}\n\n{assistant_brief}\n\n{_OUTPUT_FORMAT_INSTRUCTION}"

    def _assistant_brief(self, prompt_path: str) -> str:
        """助手提示词的第一节（身份与表达风格）。"""
        prompt = load_prompt(prompt_path, root=self._config_root)
        section = _first_markdown_section(prompt)
        return f"## 你的搭档（助手）\n{section}"

    def build_messages(self, request: DialogueRequest) -> list[dict[str, Any]]:
        assembled = None
        if request.conversation_id is not None and self.character_prompt_resolver is not None:
            assembled = self.character_prompt_resolver(
                request.conversation_id,
                request.recent_messages,
                request.turn_index,
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(request.pair_id, assembled)}
        ]
        for message in request.recent_messages:
            role = {
                MessageSource.USER: "user",
                MessageSource.CHARACTER: "assistant",
            }.get(message.source)
            if role is None:
                continue
            messages.append({"role": role, "content": message.text})
        # depth 注入只按对话消息计数，进度、结果与运行环境系统块在注入之后追加。
        if assembled is not None:
            _apply_depth_injections(messages, assembled)
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
        if request.runtime_context is not None:
            messages.append(
                {
                    "role": "system",
                    "content": _runtime_context_text(request.runtime_context),
                }
            )
        messages.append({"role": "user", "content": request.user_message.text})
        return messages

    @staticmethod
    def parse_output(raw_text: str) -> CharacterTurn:
        """把角色回合的完整正文解析为 CharacterTurn，不符合输出协议时抛 DialogueProtocolError。

        正文必须是一个 JSON 对象。模型自报 delegate=true 却没有 delegation 时
        标记 delegation_missed，由编排器如实暴露。解析失败时原始片段写入本地日志。
        """
        try:
            return _parse_character_turn(raw_text)
        except ValueError as exc:
            logger.warning("角色对话模型输出不符合协议（%s），原始片段: %r", exc, raw_text[-500:])
            if isinstance(exc, DialogueProtocolError):
                raise
            raise DialogueProtocolError(str(exc)) from exc

    async def complete_json(
        self, *, system: str, user: str, max_tokens: int
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "max_tokens": max_tokens,
            **self._request_extras(),
        }
        response = await self._client_or_raise().post("/chat/completions", json=body)
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DialogueProtocolError(
                f"Chat Completions 响应缺少 choices[0].message.content：{response.text[:2000]}"
            ) from exc
        if not isinstance(content, str):
            raise DialogueProtocolError(
                f"Chat Completions 响应没有正文：{response.text[:2000]}"
            )
        try:
            result = json.loads(content)
        except ValueError as exc:
            raise DialogueProtocolError(f"模型正文不是 JSON：{content[:2000]!r}") from exc
        if not isinstance(result, dict):
            raise DialogueProtocolError(f"模型正文不是 JSON 对象：{content[:2000]!r}")
        return result

    async def generate_title(
        self, *, pair_id: str, context: tuple[Message, ...]
    ) -> str:
        """以助手身份为聊天命名，不经过角色输出协议。"""
        config = load_pair_config(pair_id, root=self._config_root)
        assistant_prompt = load_prompt(config.assistant.prompt, root=self._config_root)
        context_text = "\n".join(
            f"{_title_source_label(message.source)}：{message.text.strip()}"
            for message in context
            if message.text.strip()
        )
        system = f"""你是{config.assistant.name}，当前只负责一项内部工作：给聊天起一个简短标题。
你只能做聊天命名，不能回答聊天、不能提出任务、不能调用工具。
根据真实消息上下文提炼主题，标题是 2 到 16 个字的中文，不加引号、句号、解释或前缀。
只输出一个 JSON 对象：{{"title": "标题"}}

以下是你的身份与表达边界：
{assistant_prompt}
"""
        result = await self.complete_json(
            system=system, user=f"聊天上下文：\n{context_text}", max_tokens=128
        )
        title = result.get("title")
        if not isinstance(title, str) or not title.strip():
            raise DialogueProtocolError(f"标题生成没有返回 title 字符串：{result!r}")
        return title.strip()

    async def generate_summary(
        self, *, pair_id: str, assistant_prompt: str, context_text: str
    ) -> dict[str, Any]:
        """以助手身份生成聊天摘要；摘要字段与语义由模型决定。"""
        config = load_pair_config(pair_id, root=self._config_root)
        system = f"""你是{config.assistant.name}，当前只负责一项内部工作：把这段话聊生成一个结构化摘要。
你只能做摘要，不能回答聊天、不能提出任务、不能调用工具。
只输出一个 JSON 对象，不要输出其他内容。

以下是你的身份与表达边界：
{assistant_prompt}
"""
        return await self.complete_json(system=system, user=context_text, max_tokens=2048)

    def _request_extras(self) -> dict[str, Any]:
        """DeepSeek 端点使用 JSON Output 并关闭 thinking，其他端点保持标准请求体。

        deepseek-v4-flash 在 thinking=enabled 与 response_format=json_object
        组合下，带历史和项目上下文的回合会返回 HTTP 200 但 content 只有空格。
        """
        if not is_deepseek_host(self.base_url):
            return {}
        extras = deepseek_request_extras(thinking=False, model=self.model)
        extras["response_format"] = {"type": "json_object"}
        return extras

    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        client = self._client_or_raise()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self.build_messages(request),
            "stream": True,
            **self._request_extras(),
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if is_deepseek_host(self.base_url):
            payload["max_tokens"] = 8192
        # content 增量经 IncrementalJsonSpeechParser 只提取 speech 上屏；
        # reasoning_content 走独立通道。
        text_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        parser = IncrementalJsonSpeechParser()
        speech_started = False
        reasoning_started = False
        async with aconnect_sse(
            client, "POST", "/chat/completions", json=payload
        ) as event_source:
            event_source.response.raise_for_status()
            async for sse in event_source.aiter_sse():
                if sse.data == "[DONE]":
                    break
                delta_payload = _chunk_delta(sse.data)
                content_delta = delta_payload.get("content", "")
                reasoning_delta = delta_payload.get("reasoning_content", "")
                if reasoning_delta:
                    if not reasoning_started:
                        yield DialogueEvent(type="reasoning.started")
                        reasoning_started = True
                    reasoning_chunks.append(str(reasoning_delta))
                    yield DialogueEvent(type="reasoning.delta", delta=str(reasoning_delta))
                if content_delta:
                    raw_text = str(content_delta)
                    text_chunks.append(raw_text)
                    speech_delta = parser.feed(raw_text)
                    if speech_delta:
                        if not speech_started:
                            yield DialogueEvent(type="speech.started")
                            speech_started = True
                        yield DialogueEvent(type="speech.delta", delta=speech_delta)
        if reasoning_started:
            yield DialogueEvent(type="reasoning.completed")
        raw_text = "".join(text_chunks)
        if raw_text:
            # speech.completed 携带完整原始输出供技术详情使用，raw 不进入气泡。
            yield DialogueEvent(type="speech.completed", raw=raw_text)
        turn = self.parse_output(raw_text)
        turn = turn.model_copy(update={"reasoning": "".join(reasoning_chunks).strip()})
        yield DialogueEvent(type="character.final", turn=turn)


_OUTPUT_FORMAT_INSTRUCTION = """## 运行时输出协议（最高优先级）

每轮只输出一个 JSON 对象，不得在 JSON 前后添加正文、解释或 Markdown
代码块。speech 只放会进入语音朗读的角色台词，不含舞台说明、括号、星号
或心理描写。每轮几句话，说完就停。

delegate 是每轮必填的布尔字段，由你判断：true 表示本轮用户请求需要
搭档真正动手（本地文件、代码、命令、工具操作），false 表示纯聊天或
你自己就能回答。判定以你对用户请求的理解为准，与用户怎么措辞无关。

纯聊天：

{"speech": "角色台词", "delegate": false}

需要委派时，delegate 必须为 true，且同一轮必须带上 delegation：

{"speech": "角色台词", "delegate": true, "delegation": {"type": "task", "instructions": "任务内容", "constraints": ["约束"]}}

delegate 为 true 却漏了 delegation 属于协议违规，本轮不会有任务交给搭档；
只在台词里说“让搭档看看”不算委派，只有 delegation 才是任务。

修改正在执行的任务：

{"speech": "角色台词", "delegate": true, "delegation": {"type": "amendment", "instructions": "修改内容", "target_task_id": "任务id", "revision": 2}}

memory 是可选的长期记忆字段：本轮出现了值得长期记住的内容时，在同一个
JSON 对象里加上 memory，值是数组，每个元素是对象且 content 是对象；字段与
内容由你自己决定，要不要记也由你判断，没有要记的就省略 memory：

{"speech": "角色台词", "delegate": false, "memory": [{"content": {"字段": "内容"}}]}

memory 不是任务，也不需要搭档动手；它只表示你希望记住这件事。

收到任务结果系统消息时只依据给定状态回应。任务失败时，可以立即重新返回
delegation.type == "task" 重试一次；重试仍未成功就如实说明，不再继续委派。
任务成功或已取消时，delegate 为 false 且不带 delegation。未收到成功结果前，
不得把任务描述成已执行或已完成。"""


def _chunk_delta(data: str) -> dict[str, Any]:
    """解析一个 Chat Completions 流式数据块，返回首个 choice 的 delta。

    OpenAI 协议允许 choices 为空的数据块（例如 usage 统计块），这类块
    没有增量；不是 JSON、缺少 choices 或 delta 形状不符都按协议错误抛出。
    """
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError as exc:
        raise DialogueProtocolError(f"流式数据块不是合法 JSON：{data[:500]!r}") from exc
    choices = chunk.get("choices") if isinstance(chunk, dict) else None
    if not isinstance(choices, list):
        raise DialogueProtocolError(f"流式数据块缺少 choices：{data[:500]!r}")
    if not choices:
        return {}
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if not isinstance(delta, dict):
        raise DialogueProtocolError(f"流式数据块的 delta 不是对象：{data[:500]!r}")
    return delta


def _parse_character_turn(raw_text: str) -> CharacterTurn:
    try:
        obj = json.loads(raw_text)
    except ValueError as exc:
        raise DialogueProtocolError(f"角色模型输出不是 JSON：{exc}") from exc
    if not isinstance(obj, dict):
        raise DialogueProtocolError("角色模型输出不是 JSON 对象")
    speech = obj.get("speech")
    if not isinstance(speech, str):
        raise DialogueProtocolError("角色模型输出缺少 speech 字符串")
    speech = speech.strip()
    if not speech.strip(" \t\r\n.…。!！?？"):
        raise DialogueProtocolError("角色模型输出的 speech 为空或仅包含占位标点")
    delegate = obj.get("delegate", False)
    if not isinstance(delegate, bool):
        raise DialogueProtocolError(f"角色模型输出的 delegate 不是布尔值：{delegate!r}")
    delegation = _parse_delegation(obj.get("delegation"))
    # memory 键缺省表示本轮没有要记的内容；显式 null 也必须符合数组形状。
    memory = _parse_memory(obj["memory"]) if "memory" in obj else ()
    return CharacterTurn(
        speech=speech,
        delegation=delegation,
        memory=memory,
        delegation_missed=delegate and delegation is None,
    )


def _parse_delegation(value: object) -> DelegationDraft | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DialogueProtocolError("角色模型输出的 delegation 必须是对象")
    kind = value.get("type")
    instructions = value.get("instructions")
    if isinstance(instructions, str):
        instructions = instructions.strip()
    if kind == "task":
        return TaskRequestDraft(
            instructions=instructions,
            constraints=value.get("constraints") or (),
        )
    if kind == "amendment":
        return TaskAmendmentDraft(
            instructions=instructions,
            target_task_id=value.get("target_task_id"),
            revision=value.get("revision"),
        )
    raise DialogueProtocolError(f"角色模型输出的 delegation.type 不是 task 或 amendment：{kind!r}")


def _parse_memory(value: object) -> tuple[MemoryDraft, ...]:
    """memory 必须是数组，每个元素是 content 为对象的对象；内容原样交给 MemoryDraft。"""
    if not isinstance(value, list):
        raise DialogueProtocolError("角色模型输出的 memory 必须是数组")
    drafts: list[MemoryDraft] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DialogueProtocolError(f"角色模型输出的 memory[{index}] 必须是对象")
        content = item.get("content")
        if not isinstance(content, dict):
            raise DialogueProtocolError(f"角色模型输出的 memory[{index}].content 必须是对象")
        drafts.append(MemoryDraft(content=content))
    return tuple(drafts)


def _apply_depth_injections(
    messages: list[dict[str, Any]], assembled: AssembledPrompt
) -> None:
    """把世界书 atDepth 与 depth_prompt 注入插进对话消息列表（SillyTavern doChatInject）。

    同 (depth, role) 的文本以换行合并为一条消息；按 depth 降序逐组插入到
    len(messages) - depth，夹在 [0, len(messages)] 之内，depth=0 追加到末尾。
    """
    groups: dict[tuple[int, str], list[str]] = {}
    for injection in assembled.depth_injections:
        groups.setdefault((injection.depth, injection.role), []).append(injection.text)
    for (depth, role), texts in sorted(groups.items(), key=lambda item: item[0][0], reverse=True):
        position = min(max(len(messages) - depth, 0), len(messages))
        messages.insert(position, {"role": role, "content": "\n".join(texts)})


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


def _title_source_label(source: MessageSource) -> str:
    return {
        MessageSource.USER: "用户",
        MessageSource.CHARACTER: "角色",
        MessageSource.ASSISTANT: "助手",
    }.get(source, "消息")


def _progress_summary_text(summary: CharacterProgressSummary) -> str:
    """进度摘要只含步骤计数与当前步骤，不含命令、路径或输出原文。"""
    lines = [
        "[系统信息：任务进度]",
        "状态：执行中",
        f"已完成步骤：{summary.completed_steps}",
        f"当前：{summary.current_step}",
    ]
    return "\n".join(lines)


def _runtime_context_text(ctx: ProjectRuntimeContext) -> str:
    """项目运行上下文系统块，不显示为聊天消息。

    聊天模式下角色不能读取或操作项目、不能委派助手；协作模式给出项目名称、
    绝对目录、时间与时区。
    """
    if ctx.conversation_mode == "chat":
        return (
            "[系统信息：当前工作环境]\n"
            "当前模式：聊天。你处于聊天模式，不能读取、查看或操作任何项目文件，"
            "不能委派任务给助手，也不能假装自己操作过项目。用户询问项目内容时，"
            "明确说明当前模式无法查看项目，并建议切换到协作模式。"
        )
    return (
        "[系统信息：当前工作环境]\n"
        f"当前模式：协作。你所在的项目：{ctx.project_name}，"
        f"项目目录：{ctx.project_abs_dir}。"
        f"本机系统时间：{ctx.local_time}（时区 {ctx.timezone}）。"
        "你本人不能直接读取或修改文件；需要项目文件、命令或代码操作时，"
        "通过 delegation 交给助手处理。"
    )


def _result_summary_text(result: CharacterResultSummary) -> str:
    lines = [
        "[系统信息：任务结果]",
        f"状态：{result.status}",
        f"摘要：{result.summary}",
    ]
    if result.status == "failed":
        lines.append(
            "任务失败了。你可以立即重新委派（delegation.type=task）重试一次，"
            "或在台词里如实说明失败原因。"
        )
    if result.user_visible_changes:
        lines.append("可见变更：" + "、".join(result.user_visible_changes))
    if result.limitations:
        lines.append("局限：" + "；".join(result.limitations))
    if result.pending_questions:
        lines.append("待确认：" + "；".join(result.pending_questions))
    return "\n".join(lines)
