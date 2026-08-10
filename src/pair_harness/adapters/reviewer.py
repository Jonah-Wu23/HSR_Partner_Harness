from __future__ import annotations

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
    输入只包含 PendingOperation 摘要和最近 10 条消息，不给任何工具。
    """

    def __init__(self, model: DialogueModel) -> None:
        self._model = model

    async def review(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict:
        prompt = self._build_prompt(op, context[-10:])
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
        text_parts: list[str] = []
        async for event in self._model.stream_reply(request):
            if event.type == "speech.delta" and event.delta:
                text_parts.append(event.delta)
            elif event.type == "character.final" and event.turn:
                text_parts.append(event.turn.speech)
        import json

        try:
            data = json.loads("".join(text_parts).strip())
        except json.JSONDecodeError:
            return ReviewerVerdict(allow=False, reason="审查智能体返回格式错误", suggestion="请重试")
        return ReviewerVerdict(
            allow=bool(data.get("allow", False)),
            reason=str(data.get("reason", "")),
            suggestion=str(data.get("suggestion", "")),
        )

    def _build_prompt(self, op: PendingOperation, context: list[Message]) -> str:
        lines = [
            "你是一名安全审查智能体，只允许输出 JSON。",
            "输入包含一条待审批操作和最近对话上下文。",
            "请判断该操作是否允许执行。",
            "",
            "输出格式（仅 JSON，无其他文字）：",
            '{"allow": true|false, "reason": "否决时必填的简短理由", "suggestion": "否决时必填的调整建议"}',
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
            lines.append("最近上下文：")
            for message in context:
                lines.append(f"- {message.source}: {message.text}")
        return "\n".join(lines)
