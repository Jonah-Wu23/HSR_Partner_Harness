from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .contracts import ApprovalMode, Message, MessageOrigin, MessageSource, ProjectRef


def recent_roleplay_context(messages: Iterable[Message], limit: int = 12) -> tuple[Message, ...]:
    """只保留用户与角色的真实对话，排除助手与工具内部记录。

    委派卡（origin=character_delegation 的 user 镜像）是任务指令的副本，
    不是用户真实发言——把它留给模型会让模型误以为用户又发了一条要求。
    """
    eligible = [
        message
        for message in messages
        if message.source in (MessageSource.USER, MessageSource.CHARACTER)
        and message.origin != MessageOrigin.CHARACTER_DELEGATION
    ]
    return tuple(eligible[-limit:])


@dataclass(frozen=True)
class ExecutionContext:
    """V0.3.2 M4：不可变执行上下文。

    提交被接受时从 SQLite 与搭档目录一次性解析，随该 Turn 传递到角色
    回合、直发助手与任务执行；切换界面当前聊天只更新视图状态，不影响
    已经运行的 Turn。项目根、pair 提示词、审批模式与推理档位都来自本
    上下文，执行路径不再读取可变全局 ``self.project``。
    """

    account_id: str
    project: ProjectRef
    conversation_id: str
    pair_id: str
    conversation_mode: Literal["chat", "collaboration"] = "collaboration"
    approval_mode: ApprovalMode = ApprovalMode.REQUEST_APPROVAL
    reasoning_effort: str = "low"
    assistant_instructions: str = ""
