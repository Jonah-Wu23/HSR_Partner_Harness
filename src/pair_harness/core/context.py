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


class AssistantInstructionError(ValueError):
    """助手提示词装配断言失败：重复注入或混入非助手内容。"""


def assert_single_assistant_markdown(
    instructions: str, expected_markdown: str
) -> None:
    """V0.3.3 装配断言：助手上下文恰好注入一个助手 Markdown。

    正常上下文与未来（V0.3.9）压缩后重建的上下文都必须满足：
    注入文本与 ``load_prompt(pair.assistant.prompt)`` 的单一来源完全一致；
    同一 Markdown 拼接两次、或混入角色卡/世界书等任何其他内容都视为
    装配违规，直接失败（Let It Fail），不得静默截断或修正。
    """
    if instructions != expected_markdown:
        raise AssistantInstructionError(
            "助手提示词装配断言失败：注入内容与单一助手 Markdown 不一致"
            "（可能重复注入或混入了角色卡内容）"
        )
