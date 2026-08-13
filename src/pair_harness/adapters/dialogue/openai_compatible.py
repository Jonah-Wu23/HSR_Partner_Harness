from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
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

# 当前协议要求单一 JSON 对象；解析器仍兼容早期“台词 + JSON”输出。
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
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
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
        if request.runtime_context is not None:
            messages.append(
                {
                    "role": "system",
                    "content": _runtime_context_text(request.runtime_context),
                }
            )
        messages.append({"role": "user", "content": request.user_message.text})
        return messages

    def _enforce_execution_boundary(
        self, turn: CharacterTurn, request: DialogueRequest
    ) -> CharacterTurn:
        """把模型输出收敛到角色/助手职责边界。

        JSON 模式和提示词负责主要行为；这里保留一条确定性边界：明确要求
        操作本地文件、代码或命令时，若模型漏掉 delegation，仍以用户原始
        指令形成结构化委派。角色只说“交给搭档”，不把工具操作说成自己做。
        结果回应则以 ExecutionReceipt 派生的状态为准，禁止成功/失败倒置。
        """
        config = load_pair_config(request.pair_id, root=self._config_root)
        assistant_name = config.assistant.name

        if request.result_summary is not None:
            speech = _truthful_result_speech(
                turn.speech, request.result_summary.status, assistant_name
            )
            return turn.model_copy(update={"speech": speech, "delegation": None})

        delegation = turn.delegation
        if delegation is None and _is_explicit_local_task(request.user_message.text):
            delegation = TaskRequestDraft(instructions=request.user_message.text.strip())

        speech = turn.speech
        if isinstance(delegation, TaskRequestDraft) and _claims_self_execution(speech):
            speech = f"这事得交给{assistant_name}来处理。{assistant_name}，麻烦你了。"
        elif delegation is not None and not speech.strip():
            speech = f"这事交给{assistant_name}来处理。"
        elif delegation is not None and not _mentions_assistant(speech, assistant_name):
            speech = f"{speech.rstrip('。！？!?')}。{assistant_name}，麻烦你了。"

        return turn.model_copy(update={"speech": speech, "delegation": delegation})

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
                "temperature": 0.2,
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

    def _request_extras(self) -> dict[str, Any]:
        """B1：按后端识别注入推理请求形态。

        只对 DeepSeek 端点写入 thinking/reasoning_effort 字段；
        其余 OpenAI 兼容端点保持标准请求体（Reasonix 文档——
        "the endpoint silently ignores reasoning_effort" 的后端不做无谓注入）。
        """
        if not is_deepseek_host(self.base_url):
            return {}
        extras = deepseek_request_extras(
            thinking=self.thinking,
            effort=self.reasoning_effort,
            model=self.model,
        )
        # DeepSeek JSON Output：与 system 中唯一的 JSON 协议配合，避免
        # “正文 + JSON 尾巴”在流式分块或随机采样下偶发解析失败。
        extras["response_format"] = {"type": "json_object"}
        return extras

    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        client = self._client_or_raise()
        payload = {
            "model": self.model,
            "messages": self._build_messages(request),
            "stream": True,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        payload.update(self._request_extras())
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
        turn = self._parse_output(raw_text)
        # 流式解析已经拿到 speech 时，完整 JSON 可能在收尾分片处截断。
        # 保留已经展示的正式台词，让正文气泡沿用已解析内容。
        streamed_speech = parser.speech.strip()
        if streamed_speech and turn.speech == _FALLBACK_SPEECH:
            turn = turn.model_copy(update={"speech": streamed_speech})
        turn = turn.model_copy(update={"reasoning": "".join(reasoning_chunks).strip()})
        yield DialogueEvent(
            type="character.final",
            turn=self._enforce_execution_boundary(turn, request),
        )


_OUTPUT_FORMAT_INSTRUCTION = """## 运行时输出协议（最高优先级）

每轮只输出一个 JSON 对象，不得在 JSON 前后添加正文、解释或 Markdown
代码块。speech 只放会进入语音朗读的角色台词，不含舞台说明、括号、星号
或心理描写。每轮几句话，说完就停。

纯聊天：

{"speech": "角色台词"}

需要本地文件、代码、命令或工具操作时，角色本人不能执行，也不能说“我来
执行”“我已经完成”。必须通过 delegation 交给搭档：

{"speech": "角色台词", "delegation": {"type": "task", "instructions": "任务内容", "constraints": ["约束"]}}

修改正在执行的任务：

{"speech": "角色台词", "delegation": {"type": "amendment", "instructions": "修改内容", "target_task_id": "任务id", "revision": 2}}

收到任务结果系统消息时只依据给定状态回应，不带 delegation。未收到成功
结果前，不得把任务描述成已执行或已完成。"""


_ACTION_WORDS = (
    "创建", "新建", "删除", "移除", "重命名", "移动", "复制", "修改",
    "编辑", "写入", "追加", "保存", "运行", "执行", "安装", "构建", "编译",
    "测试", "检查", "读取", "打开", "列出",
)
_LOCAL_OBJECT_WORDS = (
    "文件", "文件夹", "目录", "路径", "代码", "项目", "仓库", "脚本", "命令",
    "测试", "依赖",
)
_QUESTION_CUES = ("怎么", "如何", "为什么", "解释", "教程", "原理")
_REQUEST_CUES = ("请", "帮我", "替我", "麻烦", "让", "把")
_SELF_EXECUTION_RE = re.compile(
    r"我(?:来|去|现在|这就|马上)?(?:帮你|替你)?"
    r"(?:创建|新建|删除|移除|重命名|移动|复制|修改|编辑|写入|追加|保存|运行|执行|安装|构建|编译|测试|检查|读取|打开|处理)"
)
_FAILURE_CUES = ("没做成", "失败", "未执行", "没有完成", "已取消", "取消了")


def _is_explicit_local_task(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if any(cue in normalized for cue in _QUESTION_CUES) and normalized.endswith(("?", "？")):
        return False
    has_action = any(word in normalized for word in _ACTION_WORDS)
    has_object = any(word in normalized for word in _LOCAL_OBJECT_WORDS)
    has_request = any(word in normalized for word in _REQUEST_CUES)
    # 文件名或相对/绝对路径也属于明确本地对象。
    has_path = bool(
        re.search(r"(?:[a-z]:[\\/]|[.]{0,2}[\\/]|\b[\w.-]+\.(?:txt|md|py|json|ya?ml|toml|csv)\b)", normalized)
    )
    return has_action and has_request and (has_object or has_path)


def _claims_self_execution(speech: str) -> bool:
    return bool(_SELF_EXECUTION_RE.search(str(speech or "")))


def _mentions_assistant(speech: str, assistant_name: str) -> bool:
    aliases = {assistant_name, assistant_name.rsplit("的", 1)[-1]}
    return any(alias and alias in speech for alias in aliases)


def _truthful_result_speech(speech: str, status: str, assistant_name: str) -> str:
    text = str(speech or "").strip()
    says_failure = any(cue in text for cue in _FAILURE_CUES)
    if status == "failed":
        return f"这次没做成，{assistant_name}把原因记在执行记录里了。"
    if status == "cancelled":
        return f"任务已经取消，{assistant_name}没有继续执行。"
    if status == "completed" and says_failure:
        return f"做完了，{assistant_name}已经把结果整理好了。"
    return text or (
        f"做完了，{assistant_name}已经把结果整理好了。"
        if status == "completed"
        else f"{assistant_name}已经返回了任务状态。"
    )


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
    if result.user_visible_changes:
        lines.append("可见变更：" + "、".join(result.user_visible_changes))
    if result.limitations:
        lines.append("局限：" + "；".join(result.limitations))
    if result.pending_questions:
        lines.append("待确认：" + "；".join(result.pending_questions))
    return "\n".join(lines)
