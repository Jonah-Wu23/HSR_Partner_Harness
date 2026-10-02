from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from pair_harness.core.contracts import (
    ApprovalDecision,
    ApprovalMode,
    CharacterTurn,
    DialogueEvent,
    DialogueRequest,
    EngineEvent,
    EngineEventType,
    EngineSessionRef,
    Message,
    ProjectRef,
    TaskAmendment,
    TaskRequest,
    TaskRequestDraft,
)
from pair_harness.core.ports import CodingEngine, DialogueModel


class ScriptedDialogueModel(DialogueModel):
    """可预测的演示角色模型，供演示模式与离线测试使用。"""

    def __init__(self) -> None:
        self.title_requests: list[tuple[str, tuple[Message, ...]]] = []

    async def generate_title(
        self, *, pair_id: str, context: tuple[Message, ...]
    ) -> str:
        self.title_requests.append((pair_id, context))
        user_message = next((item for item in context if item.source == "user"), None)
        if user_message is None:
            raise ValueError("演示标题需要至少一条用户消息")
        text = " ".join(user_message.text.split())[:14]
        if not text:
            raise ValueError("演示标题需要非空的用户消息")
        return f"关于{text}"

    async def generate_summary(
        self, *, pair_id: str, assistant_prompt: str, context_text: str
    ) -> dict[str, Any]:
        """确定性摘要：只取上下文前几行组成结构化对象，不改写消息原文。"""
        lines = [line for line in context_text.splitlines() if line.strip()]
        if not lines:
            raise ValueError("演示摘要需要非空的聊天上下文")
        return {
            "title": f"关于{lines[0][:20]}",
            "key_points": [line[:50] for line in lines[:3]],
            "summary": "演示摘要，用于结构化对象形状校验。",
        }

    async def complete_json(
        self, *, system: str, user: str, max_tokens: int
    ) -> dict[str, Any]:
        del system, user, max_tokens
        raise NotImplementedError("演示角色模型没有真实模型，不支持单 JSON 请求")

    async def stream_reply(self, request: DialogueRequest) -> AsyncIterator[DialogueEvent]:
        if request.result_summary is not None:
            result = request.result_summary
            if result.status == "completed":
                speech = "做完了。古代机械已经把结果收好，我们可以继续往前走。"
            elif result.status == "cancelled":
                speech = "已经停下来了。先缓一缓，等你决定下一步。"
            else:
                speech = "这次没有成功。我在这里，问题留给古代机械如实说明。"
            delegation = None
        else:
            text = request.user_message.text
            should_delegate = "请让古代机械" in text or "交给古代机械" in text
            if should_delegate:
                speech = "好，我和你一起盯着。古代机械，这件事交给你。"
                delegation = TaskRequestDraft(instructions=text)
            else:
                speech = "我听着呢。先在这里陪你把这件事慢慢说清楚。"
                delegation = None

        midpoint = max(1, len(speech) // 2)
        yield DialogueEvent(type="speech.delta", delta=speech[:midpoint])
        await asyncio.sleep(0)
        yield DialogueEvent(
            type="character.final",
            turn=CharacterTurn(speech=speech, delegation=delegation),
        )


class ScriptedCodingEngine(CodingEngine):
    """不接触文件系统的演示引擎，按脚本发出工具形状的事件。

    与真实 ACP 引擎一样，工具执行前先发 approval.requested，等编排器经
    ``resolve_approval`` 回复裁决：允许时继续演示工具，否决时跳过工具并
    正常结束本轮。
    """

    engine_type = "scripted"

    def __init__(
        self,
        *,
        fail_tool: bool = False,
        tool_payload: dict | None = None,
        patch_path: str = "hello.txt",
        reasoning: str = "",
    ) -> None:
        self.fail_tool = fail_tool
        self.tool_payload = tool_payload or {}
        # 演示脚本发出 file.patch 事件，回执的变更文件列表据此形成。
        self.patch_path = patch_path
        self.reasoning = reasoning
        self.opened_sessions: list[tuple[ProjectRef, EngineSessionRef | None]] = []
        # 记录 open_session 收到的审批模式，供测试断言
        self.opened_approval_modes: list[ApprovalMode] = []
        self.requests: list[TaskRequest] = []
        self.cancelled: list[tuple[EngineSessionRef, str]] = []
        self.amendments: list[tuple[EngineSessionRef, str, TaskAmendment]] = []
        self.decisions: dict[str, ApprovalDecision] = {}

    async def open_session(
        self,
        project: ProjectRef,
        stored_ref: EngineSessionRef | None = None,
        *,
        approval_mode: ApprovalMode,
        developer_instructions: str | None = None,
    ) -> EngineSessionRef:
        del developer_instructions
        self.opened_approval_modes.append(approval_mode)
        self.opened_sessions.append((project, stored_ref))
        return stored_ref or EngineSessionRef(
            engine_type="scripted",
            opaque_ref=f"demo-session:{project.project_id}:{uuid4()}",
        )

    async def run_turn(
        self, session_ref: EngineSessionRef, request: TaskRequest
    ) -> AsyncIterator[EngineEvent]:
        del session_ref
        self.requests.append(request)
        engine_turn_id = f"demo-turn-{uuid4()}"
        tool_call_id = f"demo-tool-{uuid4()}"
        common = {
            "conversation_id": request.conversation_id,
            "task_id": request.task_id,
            "engine_turn_id": engine_turn_id,
        }
        yield EngineEvent(sequence=0, type=EngineEventType.TURN_STARTED, **common)
        yield EngineEvent(
            sequence=1,
            type=EngineEventType.ASSISTANT_DELTA,
            payload={"text": "正在进行本地演示。"},
            **common,
        )
        if self.reasoning:
            yield EngineEvent(
                sequence=1,
                type=EngineEventType.ASSISTANT_REASONING_DELTA,
                payload={"text": self.reasoning, "channel": "summary"},
                **common,
            )
        started_payload = {"title": "演示文件操作", "details": request.instructions}
        started_payload.update(self.tool_payload)
        yield EngineEvent(
            sequence=2,
            type=EngineEventType.TOOL_STARTED,
            tool_call_id=tool_call_id,
            payload=started_payload,
            **common,
        )
        approval_id = f"demo-approval-{uuid4()}"
        yield EngineEvent(
            sequence=3,
            type=EngineEventType.APPROVAL_REQUESTED,
            tool_call_id=tool_call_id,
            payload={
                **started_payload,
                "approval_id": approval_id,
                "summary": started_payload["title"],
            },
            **common,
        )
        if self.decisions.pop(approval_id) == ApprovalDecision.DENY:
            yield EngineEvent(
                sequence=4,
                type=EngineEventType.ASSISTANT_FINAL,
                payload={"text": "演示文件操作被否决，没有执行。"},
                **common,
            )
            yield EngineEvent(
                sequence=5,
                type=EngineEventType.TURN_COMPLETED,
                payload={"summary": "本地演示结束"},
                **common,
            )
            return
        yield EngineEvent(
            sequence=3,
            type=EngineEventType.TOOL_PROGRESS,
            tool_call_id=tool_call_id,
            payload={"summary": "模拟执行中；未调用真实文件工具"},
            **common,
        )
        tool_status = "failed" if self.fail_tool else "succeeded"
        yield EngineEvent(
            sequence=4,
            type=EngineEventType.TOOL_FINISHED,
            tool_call_id=tool_call_id,
            payload={
                "status": tool_status,
                "title": "演示文件操作",
                "summary": "未执行真实文件工具",
                "details": "Plan A 使用可预测测试适配器，不修改项目文件。",
                "error": "模拟工具失败" if self.fail_tool else None,
            },
            **common,
        )
        yield EngineEvent(
            sequence=5,
            type=EngineEventType.FILE_PATCH,
            payload={"path": self.patch_path, "patch": "演示补丁，不写磁盘"},
            **common,
        )
        yield EngineEvent(
            sequence=6,
            type=EngineEventType.ASSISTANT_FINAL,
            payload={"text": "演示流程已完成；未执行真实文件工具。"},
            **common,
        )
        terminal_type = (
            EngineEventType.TURN_FAILED if self.fail_tool else EngineEventType.TURN_COMPLETED
        )
        yield EngineEvent(
            sequence=7,
            type=terminal_type,
            payload={"summary": "本地演示结束"},
            **common,
        )

    async def cancel_turn(self, session_ref: EngineSessionRef, turn_id: str) -> None:
        self.cancelled.append((session_ref, turn_id))

    async def amend_turn(
        self,
        session_ref: EngineSessionRef,
        engine_turn_id: str,
        amendment: TaskAmendment,
    ) -> None:
        self.amendments.append((session_ref, engine_turn_id, amendment))

    async def resolve_approval(
        self,
        session_ref: EngineSessionRef,
        approval_id: str,
        decision: ApprovalDecision,
    ) -> None:
        del session_ref
        self.decisions[approval_id] = decision
