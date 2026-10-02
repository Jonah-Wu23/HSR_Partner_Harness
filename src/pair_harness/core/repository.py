from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .contracts import EngineSessionRef, Message, ToolRun
from .summary import ConversationSummary


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str
    root_path: str
    # 项目归属账号（默认账号为 "default-local"）
    account_id: str = ""
    # 审批模式按项目保存，默认“请求批准”
    approval_mode: str = "request_approval"
    reasoning_effort: str = "low"
    archived: bool = False
    created_at: datetime | None = None
    last_opened_at: datetime | None = None

    @property
    def path_available(self) -> bool:
        return Path(self.root_path).is_dir()


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    project_id: str | None
    pair_id: str
    title: str
    last_mode: str
    archived: bool
    created_at: datetime
    updated_at: datetime
    # 会话归属账号；旧库迁移按项目归属回填。
    account_id: str = ""
    # 对话绑定的角色卡快照（card_id；内置角色为 None）。
    character_card_id: str | None = None
    # 标题来源：default 初始名、auto 助手生成、user 用户命名。
    title_source: str = "default"


@dataclass(frozen=True)
class ConversationSnapshot:
    """打开旧聊天时从存储读出的完整快照。

    ``summary`` 是该聊天最近一条摘要记录，没有摘要时为 None。
    """

    conversation: Conversation
    messages: tuple[Message, ...]
    tool_runs: tuple[ToolRun, ...]
    engine_session: EngineSessionRef | None
    summary: ConversationSummary | None
