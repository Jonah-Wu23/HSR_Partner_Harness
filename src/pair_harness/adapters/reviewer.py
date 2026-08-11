from __future__ import annotations

import json
from collections.abc import AsyncIterator

from pair_harness.core.contracts import (
    DialogueEvent,
    DialogueRequest,
    Message,
    MessageKind,
    MessageSource,
    PendingOperation,
    ReviewerVerdict,
)
from pair_harness.core.ports import DialogueModel, Reviewer


class ScriptedReviewer:
    """计划 A 的测试实现：按预先给定的 ReviewerVerdict 列表依次返回。"""

    def __init__(self, verdicts: list[ReviewerVerdict] | None = None) -> None:
        self._verdicts = list(verdicts or [])
        self._index = 0
        self.requests: list[tuple[PendingOperation, list[Message]]] = []

    async def review(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict:
        self.requests.append((op, context))
        if self._index >= len(self._verdicts):
            return ReviewerVerdict(allow=True)
        verdict = self._verdicts[self._index]
        self._index += 1
        if not verdict.allow:
            assert verdict.reason, "否决时必须提供理由"
            assert verdict.suggestion, "否决时必须提供调整建议"
        return verdict


class DialogueModelReviewer:
    """计划 B 的真实实现：复用当前 DialogueModel 适配器。

    提示词要求模型只输出 JSON：{"allow": bool, "reason": str, "suggestion": str}。
    输入只包含 PendingOperation 摘要和最近 3 条消息，不给任何工具。
    """

    def __init__(self, model: DialogueModel) -> None:
        self._model = model

    async def review(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict:
        recent_user_messages = [
            message for message in context if message.source == MessageSource.USER
        ][-3:]
        prompt = self._build_prompt(op, recent_user_messages)
        synthetic = Message(
            conversation_id="reviewer",
            pair_id="reviewer",
            source=MessageSource.SYSTEM,
            kind=MessageKind.SYSTEM_STATUS,
            text=prompt,
        )
        request = DialogueRequest(
            pair_id="reviewer",
            conversation_id="reviewer",
            user_message=synthetic,
        )

        # 优先拼接 speech.delta 取模型原始输出：角色适配器的 character.final
        # 是 _parse_output 的二次加工（整体 JSON 会被拆成 speech/delegation，
        # 纯 JSON 输出会被降级成“……”），审查 JSON 会被吞掉；delta 流本身
        # 就是模型输出的完整 content。delta 拼接解析失败（测试/演示模型只
        # 发半截 delta）时回退 final 台词。
        chunks: list[str] = []
        final_speech: str | None = None
        async for event in self._model.stream_reply(request):
            if event.type == "speech.delta":
                chunks.append(event.delta)
            elif event.type == "character.final" and event.turn:
                final_speech = event.turn.speech
        data = self._parse_verdict_json("".join(chunks))
        if data is None and final_speech:
            data = self._parse_verdict_json(final_speech)
        if data is None:
            return ReviewerVerdict(allow=False, reason="审查智能体返回格式错误", suggestion="请重试")
        return ReviewerVerdict(
            allow=bool(data.get("allow", False)),
            reason=str(data.get("reason", "")),
            suggestion=str(data.get("suggestion", "")),
        )

    @staticmethod
    def _parse_verdict_json(speech: str) -> dict | None:
        """从审查智能体台词中解析裁决 JSON。

        B1 联调加固：真实模型输出不稳定——可能包 markdown 代码块、前后
        带解释文字，或适配器降级台词（“……”）。逐级剥离后取首个
        ``{`` 到末个 ``}`` 的子串解析，全部失败返回 None。
        """
        import re

        text = speech.strip()
        if not text or text == "……":
            return None
        # 剥离 markdown 代码块围栏
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        try:
            obj = json.loads(text)
            return DialogueModelReviewer._coerce_verdict(obj)
        except (ValueError, TypeError):
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            obj = json.loads(text[start : end + 1])
            return DialogueModelReviewer._coerce_verdict(obj)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _coerce_verdict(obj: object) -> dict | None:
        """兼容裸裁决 JSON 与角色协议的 ``speech`` 包装。"""
        if not isinstance(obj, dict):
            return None
        if "allow" in obj:
            return obj
        wrapped = obj.get("speech")
        if not isinstance(wrapped, str):
            return None
        try:
            verdict = json.loads(wrapped)
        except (ValueError, TypeError):
            return None
        return verdict if isinstance(verdict, dict) and "allow" in verdict else None

    def _build_prompt(self, op: PendingOperation, context: list[Message]) -> str:
        lines = [
            "你是一名安全审查智能体，只允许输出 JSON。",
            "输入包含一条待审批操作和用户最近发送的最多 3 条消息。",
            "请判断该操作是否允许执行。",
            "先检查这些用户消息里是否直接要求或明确批准了当前这项操作。",
            "用户的明确要求或批准是裁决依据，但不代表可以忽略操作本身的风险。",
            "涉及凭据外传、明显越界或重大不可逆损害时，仍应否决并说明原因。",
            "",
            "输出格式（仅一个 JSON 对象，无其他文字）：",
            '{"speech": "{\\"allow\\": true|false, \\"reason\\": \\"否决时必填的简短理由\\", \\"suggestion\\": \\"否决时必填的调整建议\\"}", "delegation": null}',
            "",
            f"待审批操作摘要：{op.summary}",
            f"操作类型：{op.tool_kind}",
        ]
        if op.command:
            lines.append(f"命令：{op.command}")
        if op.paths:
            lines.append(f"涉及路径：{', '.join(op.paths)}")
        if context:
            lines.append("")
            lines.append("最近用户消息：")
            for message in context:
                lines.append(f"- {message.source}: {message.text}")
        return "\n".join(lines)
