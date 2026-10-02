from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .contracts import ApprovalMode, ProjectRef


@dataclass(frozen=True)
class ExecutionContext:
    """一个 Turn 的不可变执行上下文。

    提交被接受时从 SQLite 与搭档目录一次性解析，随该 Turn 传递到角色
    回合、直发助手与任务执行。项目、搭档、对话模式、审批模式与助手
    提示词都只从这里读取，切换界面当前聊天不影响已经运行的 Turn。
    """

    account_id: str
    project: ProjectRef
    conversation_id: str
    pair_id: str
    conversation_mode: Literal["chat", "collaboration"]
    approval_mode: ApprovalMode
    assistant_instructions: str
