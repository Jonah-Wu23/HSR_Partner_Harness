from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str
    root_path: str
    # V0.2 M3：项目归属账号（默认账号为 "default-local"）
    account_id: str = ""
    # 计划 A6：审批模式按项目保存，默认“请求批准”
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


@dataclass(frozen=True)
class ConversationSnapshot:
    conversation: Conversation
    messages: tuple
    tool_runs: tuple
    engine_session: object | None
