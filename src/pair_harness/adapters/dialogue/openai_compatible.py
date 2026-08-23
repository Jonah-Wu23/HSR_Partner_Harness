from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx

from pair_harness.config.pairs import load_pair_config, load_prompt
from pair_harness.adapters.dialogue.incremental_json import IncrementalJsonSpeechParser
from pair_harness.config.providers import (
    deepseek_request_extras,
    detect_provider,
    is_deepseek_host,
    load_reasoning_preset,
    normalize_effort,
)
from pair_harness.core.contracts import (
    CharacterProgressSummary,
    CharacterResultSummary,
    CharacterTurn,
    DelegationDraft,
    DialogueEvent,
    DialogueRequest,
    Message,
    MessageSource,
    ProjectRuntimeContext,
    TaskAmendmentDraft,
    TaskRequestDraft,
)
from pair_harness.core.ports import DialogueModel

logger = logging.getLogger(__name__)

# 当前协议要求单一 JSON 对象；解析器仍兼容早期“台词 + JSON”输出。
# 解析失败必须暴露；不能把空输出改写成可显示的省略号。


class UnusableSpeechError(ValueError):
    """角色输出不可用（空输出/JSON 截断/占位标点）。

    ``category`` 区分失败形态，供流式适配器决定是否对真实模型做有界重试：
    - ``empty``：没有可用的台词（原始输出为空，或剥离 JSON 残块后只剩
      空白/占位标点；含合法 JSON 内 speech 为占位标点）；
    - ``truncated``：模型在输出 JSON 但被截断（以 ``{`` 开头却无法解析）。
    """

    def __init__(self, message: str, *, category: str) -> None:
        super().__init__(message)
        self.category = category


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
      解析失败直接抛出，且原始 JSON 不会作为台词进入 TTS。
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
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        character_prompt_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self.base_url = base_url or os.getenv("PAIR_HARNESS_DIALOGUE_BASE_URL", "")
        self.api_key = api_key or os.getenv("PAIR_HARNESS_DIALOGUE_API_KEY", "")
        self.model = model or os.getenv("PAIR_HARNESS_DIALOGUE_MODEL", "")
        self._client = client
        # O3.2：注入的 client 由调用方管理生命周期；自建的由本类负责关闭
        self._owns_client = client is None
        self._timeout = timeout or httpx.Timeout(30.0, connect=10.0)
        self._config_root = config_root
        # B1：DeepSeek 推理请求形态（thinking 开关与 effort 档位）。
        # None 表示采用供应商预设默认（DeepSeek 默认开启思考）。
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        # B1：采样温度；None 表示不写入请求体（服务端默认，DeepSeek 为 1）。
        self.temperature = temperature
        # V0.3.5：按 conversation_id 解析对话绑定的自定义角色卡装配结果
        # （docs/plans/V0.3.5-契约冻结.md §4.2）。命中时角色侧 system 文本
        # 来自装配器；助手 brief 与输出协议仍取内置 pair YAML，卡内容不
        # 进入。resolver 返回 None（未绑定/卡已删除）一律回退内置 YAML。
        self.character_prompt_resolver = character_prompt_resolver

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

    # ---- 提示词装配（O3.2；V0.3.5 角色卡覆盖）----

    def _system_prompt(self, pair_id: str, conversation_id: str | None = None) -> str:
        config = load_pair_config(pair_id, root=self._config_root)
        character_card = load_prompt(config.character.prompt, root=self._config_root)
        if conversation_id is not None and self.character_prompt_resolver is not None:
            assembled = self.character_prompt_resolver(conversation_id)
            if assembled is not None:
                # 自定义角色卡对话：角色侧文本来自装配器（不改写原文），
                # 助手 brief 与输出协议指令保持内置来源，两段永不互换。
                assistant_brief = self._assistant_brief(config.assistant.prompt)
                return (
                    f"{assembled.system_text}\n\n"
                    f"{assistant_brief}\n\n{_OUTPUT_FORMAT_INSTRUCTION}"
                )
        assistant_brief = self._assistant_brief(config.assistant.prompt)
        return f"{character_card}\n\n{assistant_brief}\n\n{_OUTPUT_FORMAT_INSTRUCTION}"

    def _assistant_brief(self, prompt_path: str) -> str:
        """从助手提示词取“身份”一节作为搭档表达配置（名称+表达风格）。"""
        prompt = load_prompt(prompt_path, root=self._config_root)
        section = _first_markdown_section(prompt)
        return f"## 你的搭档（助手）\n{section}"

    def build_messages(
        self, request: DialogueRequest, *, delegation_retry: bool = False
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._system_prompt(
                    request.pair_id, request.conversation_id
                ),
            }
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
        if request.runtime_context is not None:
            messages.append(
                {
                    "role": "system",
                    "content": _runtime_context_text(request.runtime_context),
                }
            )
        if delegation_retry:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "上一轮输出不符合运行时输出协议：缺少 delegate 字段，"
                        "或自报 delegate=true 却没有返回 delegation。请重新判断"
                        "本轮用户请求：需要搭档动手执行就返回 delegate=true 并"
                        "带完整的 delegation.type=task；不需要就返回 "
                        "delegate=false。不要只在台词里答应，也不要声称已经完成。"
                    ),
                }
            )
        messages.append({"role": "user", "content": request.user_message.text})
        if delegation_retry:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "请按运行时协议重新输出本轮结果：只输出一个完整 JSON "
                        "对象，必须包含 speech 与 delegate；需要委派时同时带上"
                        " delegation.type=task，把用户要执行的真实操作写入"
                        " delegation.instructions。"
                    ),
                }
            )
        return messages

    def _needs_delegation_retry(
        self, request: DialogueRequest, turn: CharacterTurn
    ) -> bool:
        """纠偏条件：协作模式下模型没有给出 delegation，且协议不完整。

        两种协议不完整形态，都是结构一致性检查，不猜意图：
        - 自报 delegate=true 却没返回 delegation（自相矛盾）；
        - 连 delegate 字段都没输出（协议规定每轮必填；纯台词/旧格式
          输出都算缺失）。
        纠偏只要求模型按协议重新判断并补全输出，要不要委派仍由模型
        决定。聊天模式与任务结果轮不纠偏。
        """
        context = request.runtime_context
        if (
            context is None
            or context.conversation_mode != "collaboration"
            or request.result_summary is not None
        ):
            return False
        if turn.delegation is not None:
            return False
        return turn.declares_delegation or not turn.delegate_field_present

    def parse_output(
        self, raw_text: str, *, request: DialogueRequest | None = None
    ) -> CharacterTurn:
        """公开共享解析入口：解析并应用委派纠偏标记。

        供 OpenAI 兼容流与 Codex 对话适配器共用，覆盖空正文/截断 JSON
        （解析失败时不吞异常，把原始输出片段记入本地日志后继续抛出）
        以及委派自报不一致时的 ``delegation_missed`` 真实标记。
        """
        try:
            turn = self._parse_output(raw_text)
        except ValueError as exc:
            # V0.3.3：解析失败把原始输出片段写入本地日志（不进聊天）——
            # 保留真实失败以便定位是截断还是真空，而不是让 UI 只能看到
            # 一句无法诊断的“回复失败”。
            logger.warning(
                "角色对话模型输出不可用（%s），原始片段: %r",
                getattr(exc, "category", "parse"),
                raw_text[-500:],
            )
            raise
        if (
            request is not None
            and request.result_summary is None
            and self._needs_delegation_retry(request, turn)
        ):
            turn = turn.model_copy(update={"delegation_missed": True})
        return turn

    # ---- 输出解析（O3.2）----

    @staticmethod
    def _parse_output(raw_text: str) -> CharacterTurn:
        """把模型输出解析为 CharacterTurn。

        整体或结尾 JSON 对象 → 结构化（speech + delegation）；
        解析失败或 speech 为空 → 直接抛错，不能生成占位台词。
        """
        text = raw_text.strip()
        obj = OpenAICompatibleDialogueModel._try_parse_json(text)
        if obj is not None:
            if "speech" not in obj:
                raise ValueError("角色模型输出缺少 speech 字段")
            speech = str(obj.get("speech") or "").strip()
            if _is_placeholder_speech(speech):
                raise UnusableSpeechError(
                    "角色模型输出的 speech 为空或仅包含占位标点", category="empty"
                )
            delegation = OpenAICompatibleDialogueModel._parse_delegation(
                obj.get("delegation")
            )
            field_present = "delegate" in obj or delegation is not None
            declares = bool(obj.get("delegate", False)) or delegation is not None
            return CharacterTurn(
                speech=speech,
                delegation=delegation,
                declares_delegation=declares,
                delegate_field_present=field_present,
            )
        cleaned = OpenAICompatibleDialogueModel._strip_json_attempt(text)
        if _is_placeholder_speech(cleaned):
            # 剥离 JSON 残块后只剩空白/标点：按失败形态区分文案——
            # 以 { 开头是模型在输出 JSON 时被截断；否则就是纯空/占位输出。
            if text.startswith("{"):
                raise UnusableSpeechError(
                    "角色模型 JSON 截断，未返回可用 speech", category="truncated"
                )
            raise UnusableSpeechError(
                "角色模型输出为空或仅含占位标点，未返回可用 speech", category="empty"
            )
        return CharacterTurn(speech=cleaned)

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
        # 兼容旧角色卡和已有模型输出中的 delegation.data.instructions；
        # 当前运行时协议使用 delegation.instructions 平铺字段。
        payload = value
        if not str(payload.get("instructions") or "").strip():
            nested = payload.get("data")
            if isinstance(nested, dict):
                payload = nested
        instructions = str(payload.get("instructions") or "").strip()
        if not instructions:
            return None
        if kind == "task":
            constraints = payload.get("constraints") or ()
            if not isinstance(constraints, (list, tuple)):
                constraints = ()
            return TaskRequestDraft(
                instructions=instructions,
                constraints=tuple(str(c) for c in constraints),
            )
        if kind == "amendment":
            target = payload.get("target_task_id")
            revision = payload.get("revision")
            return TaskAmendmentDraft(
                instructions=instructions,
                target_task_id=str(target) if target else None,
                revision=int(revision) if isinstance(revision, int) and revision >= 1 else None,
            )
        return None

    # ---- 标题生成与流式对话 ----

    async def generate_title(
        self, *, pair_id: str, context: tuple[Message, ...]
    ) -> str | None:
        """使用助手提示词生成短标题，不经过角色输出协议。

        DeepSeek 等推理模型默认开启思考，会把 max_tokens 全部耗在思考上
        （finish_reason=length、content 为空）——标题请求显式关闭思考并
        保留足够 token 预算；仍为空时带更大预算重试一次。
        """
        if not context:
            return None
        config = load_pair_config(pair_id, root=self._config_root)
        assistant_prompt = load_prompt(config.assistant.prompt, root=self._config_root)
        context_text = "\n".join(
            f"{_title_source_label(message.source)}：{message.text.strip()}"
            for message in context
            if message.text.strip()
        )
        if not context_text:
            return None
        system = f"""你是{config.assistant.name}，当前只负责一项内部工作：给聊天起一个简短标题。
你只能做聊天命名，不能回答聊天、不能提出任务、不能调用工具。
根据真实消息上下文提炼主题，只输出一个中文标题，2 到 16 个字，不加引号、句号、解释或前缀。

以下是你的身份与表达边界：
{assistant_prompt}
"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"聊天上下文：\n{context_text}"},
        ]
        for thinking, max_tokens in ((False, 128), (True, 512)):
            body: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "temperature": 0.5,
                "max_tokens": max_tokens,
            }
            body.update(deepseek_request_extras(thinking=thinking, model=self.model))
            response = await self._client_or_raise().post(
                "/chat/completions", json=body
            )
            response.raise_for_status()
            payload = response.json()
            choices = payload.get("choices") or []
            if not choices:
                return None
            content = (choices[0].get("message") or {}).get("content", "")
            title = _normalize_title(content)
            if title:
                return title
        return None

    def _request_extras(self, *, structured_dialogue: bool = False) -> dict[str, Any]:
        """B1：按后端识别注入推理请求形态。

        只对 DeepSeek 端点写入 thinking/reasoning_effort 字段；
        其余 OpenAI 兼容端点保持标准请求体（Reasonix 文档——
        "the endpoint silently ignores reasoning_effort" 的后端不做无谓注入）。

        DeepSeek 的结构化角色回合必须关闭 thinking。真实 ``deepseek-v4-flash``
        联调表明，``thinking=enabled`` 与 ``response_format=json_object`` 组合在
        带历史和项目上下文的回合里会返回 HTTP 200，但 content 只有空格；这不是
        可解析的台词，也不能靠占位文本或重试伪装成成功。结构化委派仍由同一个
        DeepSeek 模型生成，只调整这个已验证会失败的请求形态。
        """
        if not is_deepseek_host(self.base_url):
            return {}
        thinking = False if structured_dialogue else self.thinking
        effort = None if structured_dialogue else self.reasoning_effort
        extras = deepseek_request_extras(
            thinking=thinking,
            effort=effort,
            model=self.model,
        )
        # DeepSeek JSON Output：与 system 中唯一的 JSON 协议配合；结构化角色
        # 回合不启用 thinking，避免真实接口返回空白 content。
        extras["response_format"] = {"type": "json_object"}
        return extras

    async def stream_reply(
        self,
        request: DialogueRequest,
        *,
        _attempt: int = 0,
        _delegation_retry: bool = False,
    ) -> AsyncIterator[DialogueEvent]:
        client = self._client_or_raise()
        payload = {
            "model": self.model,
            "messages": self.build_messages(
                request, delegation_retry=_delegation_retry
            ),
            "stream": True,
        }
        deepseek_structured = is_deepseek_host(self.base_url)
        if deepseek_structured:
            # 结构化委派回合使用确定的采样参数；不改变供应商或模型，只避开
            # deepseek-v4-flash 在 thinking + JSON Output 下的空白正文响应。
            payload["temperature"] = 1.0
            payload["max_tokens"] = 8192
        elif self.temperature is not None:
            payload["temperature"] = self.temperature
        payload.update(self._request_extras(structured_dialogue=deepseek_structured))
        if deepseek_structured and _attempt > 0 and not _delegation_retry:
            # DeepSeek 偶发在带历史的 response_format=json_object 请求中返回
            # 空 content；重试时放宽供应商格式约束，仍由本地解析器和委派
            # 协议决定是否接受结果。
            payload.pop("response_format", None)
            payload["temperature"] = 1.2
        # V0.2 M2（问题 10）：content 增量经 IncrementalJsonSpeechParser 只提取
        # 干净 speech 上屏（不再闪烁 JSON 键名）；reasoning_content 走独立通道。
        # 增量期间若字段尚未解析出来，界面显示“正在组织语言…”。
        text_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        parser = IncrementalJsonSpeechParser()
        speech_started = False
        reasoning_started = False
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
                delta_payload = chunk.get("choices", [{}])[0].get("delta", {})
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
        if text_chunks:
            # speech.completed 携带完整原始输出（含解析失败的 JSON），
            # 供技术详情与审查智能体复用；raw 绝不进入气泡。
            yield DialogueEvent(type="speech.completed", raw="".join(text_chunks))
        raw_text = "".join(text_chunks)
        try:
            turn = self.parse_output(raw_text, request=request)
        except UnusableSpeechError as exc:
            # 空输出/截断 JSON：尚未产生任何 speech 增量时，对 DeepSeek
            # 结构化端点做一次有界重试（重新请求真实模型，与委派纠偏重试
            # 同机制，不合成结果）；不会用占位台词掩盖失败，也不会重放已经
            # 展示过的半截正文。重试后再失败才报错，报错文案区分「输出为空」
            # 与「JSON 截断」。
            if (
                deepseek_structured
                and _attempt < 2
                and not speech_started
                and exc.category in ("empty", "truncated")
            ):
                async for retry_event in self.stream_reply(
                    request,
                    _attempt=_attempt + 1,
                    _delegation_retry=_delegation_retry,
                ):
                    yield retry_event
                return
            raise
        turn = turn.model_copy(update={"reasoning": "".join(reasoning_chunks).strip()})
        if (
            _attempt < 2
            and not _delegation_retry
            and self._needs_delegation_retry(request, turn)
        ):
            # 模型自报了委派意图却没给出 delegation：用运行时协议纠偏一次，
            # 对全部供应商生效。
            async for retry_event in self.stream_reply(
                request,
                _attempt=1,
                _delegation_retry=True,
            ):
                yield retry_event
            return
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

delegate 为 true 却漏了 delegation 属于协议违规，系统会要求你重发；
只在台词里说“让搭档看看”不算委派，只有 delegation 才是任务。

修改正在执行的任务：

{"speech": "角色台词", "delegate": true, "delegation": {"type": "amendment", "instructions": "修改内容", "target_task_id": "任务id", "revision": 2}}

收到任务结果系统消息时只依据给定状态回应。任务失败时，可以立即重新返回
delegation.type == "task" 重试一次；重试仍未成功就如实说明，不再继续委派。
任务成功或已取消时，delegate 为 false 且不带 delegation。未收到成功结果前，
不得把任务描述成已执行或已完成。"""


def _is_placeholder_speech(speech: str) -> bool:
    return not str(speech or "").strip(" \\t\\r\\n.…。!！?？")


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


def _normalize_title(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`").strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            text = str(parsed.get("title") or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = text.splitlines()[0].strip().strip("\"'“”‘’")
    for prefix in ("标题：", "标题:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    text = text.rstrip("。！？!?：:，,")
    return text[:16].strip() or None


def _progress_summary_text(summary: CharacterProgressSummary) -> str:
    """O3.3：进度摘要约定格式（压缩中性描述，不含命令/路径/输出原文）。"""
    lines = ["[系统信息：任务进度]", "状态：执行中"]
    if summary.total_steps is not None:
        lines.append(f"已完成：{summary.completed_steps}/{summary.total_steps}")
    else:
        lines.append(f"已完成步骤：{summary.completed_steps}")
    lines.append(f"当前：{summary.current_step}")
    return "\n".join(lines)


def _runtime_context_text(ctx: ProjectRuntimeContext) -> str:
    """V0.2：把项目运行上下文注入角色 system 提示词（不显示成聊天消息）。

    聊天模式是能力边界：角色不能读取/操作项目、不能委派助手；
    协作模式给出项目名称、绝对目录、时间与时区，引导形成委派。
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
