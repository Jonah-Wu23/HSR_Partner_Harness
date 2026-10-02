from __future__ import annotations

from pair_harness.core.contracts import (
    Message,
    MessageSource,
    PendingOperation,
    ReviewerVerdict,
)
from pair_harness.core.ports import DialogueModel


_REVIEW_SYSTEM_PROMPT = "\n".join(
    [
        "你是一名安全审查智能体，只允许输出 JSON。",
        "输入包含一条待审批操作和用户最近发送的最多 3 条消息。",
        "请判断该操作是否允许执行。",
        "先检查这些用户消息里是否直接要求或明确批准了当前这项操作。",
        "用户的明确要求或批准是裁决依据，但不代表可以忽略操作本身的风险。",
        "涉及凭据外传、明显越界或重大不可逆损害时，仍应否决并说明原因。",
        "",
        "只输出一个 JSON 对象，无其他文字：",
        '{"allow": true 或 false, "reason": "否决时必填的简短理由，放行时为空字符串",'
        ' "suggestion": "否决时必填的调整建议，放行时为空字符串"}',
    ]
)


class DialogueModelReviewer:
    """用 DialogueModel.complete_json 裁决待审批操作。

    输入只有 PendingOperation 摘要和用户最近 3 条消息，不给任何工具。裁决
    格式不符直接抛错，由 ApprovalManager 发出 review.failed 并否决。
    """

    def __init__(self, model: DialogueModel) -> None:
        self._model = model

    async def review(
        self, op: PendingOperation, context: list[Message]
    ) -> ReviewerVerdict:
        recent_user_messages = [
            message for message in context if message.source == MessageSource.USER
        ][-3:]
        data = await self._model.complete_json(
            system=_REVIEW_SYSTEM_PROMPT,
            user=self._build_input(op, recent_user_messages),
            max_tokens=512,
        )
        allow = data.get("allow")
        if not isinstance(allow, bool):
            raise ValueError(f"审查智能体裁决的 allow 不是布尔值：{data!r}")
        return ReviewerVerdict(
            allow=allow,
            reason=data.get("reason", ""),
            suggestion=data.get("suggestion", ""),
        )

    @staticmethod
    def _build_input(op: PendingOperation, context: list[Message]) -> str:
        lines = [
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
