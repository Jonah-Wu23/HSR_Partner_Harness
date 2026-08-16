"""用 Codex app-server 为角色提供对话模型。

OpenAI OAuth 的凭据由 Codex 自己管理，因此角色对话也走同一条
app-server 会话链，模型名与编程助手共用账号配置。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator

from pair_harness.adapters.dialogue.openai_compatible import OpenAICompatibleDialogueModel
from pair_harness.core.contracts import (
    DialogueEvent,
    DialogueRequest,
    EngineEventType,
    EngineSessionRef,
    ProjectRef,
    TaskRequest,
)
from pair_harness.core.ports import DialogueModel

from .engine import CodexAppServerEngine
from .transport import JsonlProcessTransport

logger = logging.getLogger(__name__)


class CodexDialogueModel(DialogueModel):
    """把 Codex app-server 的文本输出收敛成角色 JSON 对话事件。"""

    def __init__(
        self,
        transport: JsonlProcessTransport,
        *,
        model: str = "gpt-5.6-sol",
        reasoning_effort: str = "medium",
    ) -> None:
        self.transport = transport
        self.model = model
        self.engine = CodexAppServerEngine(
            transport, model=model, reasoning_effort=reasoning_effort
        )
        self._sessions: dict[str, EngineSessionRef] = {}
        self._parser = OpenAICompatibleDialogueModel(
            base_url="http://codex-app-server",
            api_key="codex-oauth",
            model=model,
        )

    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        context = request.runtime_context
        root = (context.project_abs_dir if context and context.project_abs_dir else os.getcwd())
        session = await self.engine.open_session(
            ProjectRef(project_id="codex-dialogue", name="角色对话", root_path=root),
            stored_ref=self._sessions.get(request.conversation_id),
            approval_policy="never",
            sandbox="read-only",
            developer_instructions=(
                "你负责角色对话，只输出一个 JSON 对象。不要调用工具，不要修改本地文件。"
            ),
        )
        self._sessions[request.conversation_id] = session
        messages = self._parser.build_messages(request)
        prompt = "\n\n".join(
            f"[{message['role']}]\n{message['content']}" for message in messages
        )
        task = TaskRequest(
            conversation_id=request.conversation_id,
            origin_message_id=request.user_message.message_id,
            instructions=(
                "请按照系统提示完成本轮角色回复。严格只输出 JSON，不要 Markdown。\n\n"
                + prompt
            ),
        )
        raw: list[str] = []
        try:
            async for event in self.engine.run_turn(session, task):
                if event.type == EngineEventType.ASSISTANT_REASONING_DELTA:
                    text = str(event.payload.get("text") or "")
                    if text:
                        yield DialogueEvent(type="reasoning.delta", delta=text)
                elif event.type == EngineEventType.ASSISTANT_DELTA:
                    text = str(event.payload.get("text") or "")
                    if text:
                        raw.append(text)
        except asyncio.CancelledError:
            # 取消后线程可能已处于半中断状态，下一次对话应新开线程而不是
            # 恢复可能被 interrupt 打断的旧线程。
            self._sessions.pop(request.conversation_id, None)
            raise
        # 与 OpenAI 兼容路径共用公开解析入口：空正文/截断 JSON 继续抛出
        # 原始错误；委派自报不一致时由解析入口统一打 delegation_missed。
        turn = self._parser.parse_output("".join(raw), request=request)
        yield DialogueEvent(type="character.final", turn=turn)

    async def generate_title(self, *, pair_id: str, context: tuple) -> str | None:
        del pair_id, context
        return None

    async def aclose(self) -> None:
        await self.transport.close()
