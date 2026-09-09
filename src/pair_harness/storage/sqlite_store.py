from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from pair_harness.core.contracts import EngineSessionRef, Message, ToolRun, enum_value
from pair_harness.core.ports import StateStore
from pair_harness.core.repository import Conversation, Project

from .records import (
    ConversationSummary,
    SummaryStatus,
    MemoryScope,
    MemoryStatus,
    MetricStatus,
    PairMemory,
    ProjectionEntry,
    ProjectionKind,
    TERMINAL_METRIC_STATUSES,
    TurnMetric,
    TurnMetricPage,
    TurnMetricQuery,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


# O4.3：数据库结构版本。新库由 schema.sql 一次建全，直接标记为该版本；
# 旧库（user_version=0）按 MIGRATIONS 逐级升级。每次结构变更 +1，
# 并在 MIGRATIONS 里补对应迁移步骤。
SCHEMA_VERSION = 11

# contract-v1 第 4 节：普通增量最多 50 条或 50ms 形成一个非空事务，
# 任一先到即刷盘。关键强刷点（用户提交确认、摘要/记忆完成或失败、审批、
# 取消、回合/任务终态、账号切换、正常退出）由接线方调用 flush()。
BATCH_MAX_WRITES = 50
BATCH_MAX_DELAY_SECONDS = 0.05

# 索引 i 对应“从版本 i 升到 i+1”的迁移步骤（每级一条或多条 SQL）。
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    # 版本 1：计划 A6 为 projects 表补审批模式列（旧代码手写 ALTER 的迁移）
    (
        "ALTER TABLE projects ADD COLUMN approval_mode "
        "TEXT NOT NULL DEFAULT 'request_approval'",
    ),
    # 版本 2：移除 engine_sessions 从未写入、从未读取的死列
    # （last_turn_id 无接线；resume_status 恒为 'ready'，删除后新库不再建）
    (
        "ALTER TABLE engine_sessions DROP COLUMN last_turn_id",
        "ALTER TABLE engine_sessions DROP COLUMN resume_status",
    ),
    # 版本 3：保存项目的角色对话思考档位
    (
        "ALTER TABLE projects ADD COLUMN reasoning_effort "
        "TEXT NOT NULL DEFAULT 'low'",
    ),
    # 版本 4：V0.2 M2 持久化会话队列（conversation_inbox）
    (
        "CREATE TABLE IF NOT EXISTS conversation_inbox ("
        "queue_item_id TEXT PRIMARY KEY,"
        "account_id TEXT NOT NULL DEFAULT '',"
        "conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,"
        "target TEXT NOT NULL,"
        "text TEXT NOT NULL,"
        "intent TEXT NOT NULL DEFAULT 'followup',"
        "position INTEGER NOT NULL DEFAULT 0,"
        "status TEXT NOT NULL DEFAULT 'queued',"
        "created_at TEXT NOT NULL,"
        "source_message_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_conversation_inbox_dispatch "
        "ON conversation_inbox(conversation_id, status, position)",
    ),
    # 版本 5：V0.2 M3 本地账号与账号级配置（方案 §M3）。
    # 旧库：建表 → 创建默认账号 → 现有项目归入默认账号。
    (
        "ALTER TABLE projects ADD COLUMN account_id TEXT NOT NULL DEFAULT ''",
        "CREATE TABLE IF NOT EXISTS accounts ("
        "account_id TEXT PRIMARY KEY,"
        "username TEXT NOT NULL UNIQUE,"
        "display_name TEXT NOT NULL,"
        "avatar TEXT NOT NULL DEFAULT '',"
        "password_hash TEXT NOT NULL,"
        "password_salt TEXT NOT NULL,"
        "last_login_at TEXT,"
        "onboarding_complete INTEGER NOT NULL DEFAULT 0,"
        "theme TEXT NOT NULL DEFAULT 'dark',"
        "created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS account_preferences ("
        "account_id TEXT PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,"
        "theme TEXT NOT NULL DEFAULT 'dark',"
        "vad_enabled INTEGER NOT NULL DEFAULT 0,"
        "last_mode TEXT NOT NULL DEFAULT 'chat')",
        "CREATE TABLE IF NOT EXISTS provider_configs ("
        "account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,"
        "key TEXT NOT NULL,"
        "value TEXT NOT NULL,"
        "PRIMARY KEY (account_id, key))",
        "CREATE TABLE IF NOT EXISTS secret_refs ("
        "account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,"
        "key TEXT NOT NULL,"
        "secret TEXT NOT NULL,"
        "PRIMARY KEY (account_id, key))",
        "INSERT OR IGNORE INTO accounts("
        "account_id, username, display_name, password_hash, password_salt,"
        "created_at) VALUES ("
        "'default-local', 'default', '默认账号', "
        "'', '', datetime('now'))",
        "INSERT OR IGNORE INTO account_preferences(account_id) VALUES ('default-local')",
        "UPDATE projects SET account_id = 'default-local' WHERE account_id = ''",
        "UPDATE conversation_inbox SET account_id = 'default-local' WHERE account_id = ''",
    ),
    # 版本 6：应用级单值状态（当前登录账号等）
    (
        "CREATE TABLE IF NOT EXISTS app_state ("
        "key TEXT PRIMARY KEY,"
        "value TEXT NOT NULL)",
    ),
    # 版本 7：聊天归属账号——聊天/引擎数据（工具记录、引擎会话随会话
    # 级联）成为账号隔离边界的一部分。旧库按项目归属回填。
    (
        "ALTER TABLE conversations ADD COLUMN account_id TEXT NOT NULL DEFAULT ''",
        "UPDATE conversations SET account_id = COALESCE("
        "(SELECT account_id FROM projects WHERE projects.project_id = conversations.project_id), "
        "'default-local') WHERE account_id = ''",
    ),
    # 版本 8：V0.3.2 多聊天切换期间，旧实现曾用可变全局
    # pair_id 写消息。会话本身的 pair_id 是固定权威值，据此
    # 修复已经落库的串搭档记录。
    (
        "UPDATE messages SET message_json = json_set("
        "message_json, '$.pair_id', (SELECT pair_id FROM conversations "
        "WHERE conversations.conversation_id = messages.conversation_id)) "
        "WHERE json_valid(message_json) "
        "AND EXISTS (SELECT 1 FROM conversations "
        "WHERE conversations.conversation_id = messages.conversation_id) "
        "AND COALESCE(json_extract(message_json, '$.pair_id'), '') <> "
        "(SELECT pair_id FROM conversations "
        "WHERE conversations.conversation_id = messages.conversation_id)",
    ),
    # 版本 9：V0.3.3 角色卡持久化（character_cards / character_assets）。
    # 旧库升级只建新表，不触碰已有表数据；新库由 schema.sql 直建同构表。
    (
        "CREATE TABLE IF NOT EXISTS character_cards ("
        "card_id TEXT PRIMARY KEY,"
        "state TEXT NOT NULL,"
        "name TEXT NOT NULL,"
        "source TEXT NOT NULL,"
        "card_json TEXT NOT NULL,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS character_assets ("
        "asset_id TEXT PRIMARY KEY,"
        "card_id TEXT NOT NULL,"
        "kind TEXT NOT NULL,"
        "mime_type TEXT NOT NULL,"
        "file_path TEXT NOT NULL,"
        "source_ref TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_character_assets_card "
        "ON character_assets(card_id)",
    ),
    # 版本 10：V0.3.5 对话绑定自定义角色卡快照。
    # conversations 补 character_card_id 列（NULL = 内置角色）；只加列
    # 不改动既有数据，新库由 schema.sql 直建同结构。
    (
        "ALTER TABLE conversations ADD COLUMN character_card_id TEXT NULL",
    ),
    # 版本 11：V0.3.9（contract-v1 第 2/4/5 节）持久化投影、聊天摘要、
    # 配对长期记忆与回合指标。全部是 CREATE ... IF NOT EXISTS，可重入；
    # 旧库只建新表，不触碰既有数据；新库由 schema.sql 直建同构表。
    (
        "CREATE TABLE IF NOT EXISTS conversation_projections ("
        "conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,"
        "entry_id TEXT NOT NULL,"
        "position INTEGER NOT NULL,"
        "kind TEXT NOT NULL,"
        "message_id TEXT,"
        "summary_id TEXT,"
        "tool_call_id TEXT,"
        "covered_by_summary_id TEXT,"
        "created_at TEXT NOT NULL,"
        "PRIMARY KEY (conversation_id, entry_id))",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_projections_position "
        "ON conversation_projections(conversation_id, position)",
        "CREATE INDEX IF NOT EXISTS idx_conversation_projections_kind "
        "ON conversation_projections(conversation_id, kind, position)",
        "CREATE TABLE IF NOT EXISTS conversation_summaries ("
        "summary_id TEXT PRIMARY KEY,"
        "conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,"
        "covers_from_message_id TEXT NOT NULL,"
        "covers_to_message_id TEXT NOT NULL,"
        "covers_message_count INTEGER NOT NULL,"
        "content TEXT NOT NULL DEFAULT '',"
        "provider TEXT,"
        "model TEXT,"
        "status TEXT NOT NULL,"
        "error_code TEXT,"
        "error TEXT,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_summaries_range "
        "ON conversation_summaries("
        "conversation_id, covers_from_message_id, covers_to_message_id)",
        "CREATE INDEX IF NOT EXISTS idx_conversation_summaries_conversation "
        "ON conversation_summaries(conversation_id, updated_at DESC)",
        "CREATE TABLE IF NOT EXISTS pair_memories ("
        "memory_id TEXT PRIMARY KEY,"
        "account_id TEXT NOT NULL,"
        "project_id TEXT NOT NULL,"
        "pair_id TEXT NOT NULL,"
        "character_ref TEXT NOT NULL,"
        "assistant_identity TEXT NOT NULL,"
        "conversation_id TEXT,"
        "content TEXT NOT NULL,"
        "status TEXT NOT NULL DEFAULT 'active',"
        "provider TEXT,"
        "model TEXT,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_pair_memories_scope ON pair_memories("
        "account_id, project_id, pair_id, character_ref, assistant_identity, "
        "status, updated_at DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_pair_memories_scope_active_content "
        "ON pair_memories("
        "account_id, project_id, pair_id, character_ref, assistant_identity, content) "
        "WHERE status = 'active'",
        "CREATE TABLE IF NOT EXISTS turn_metrics ("
        "metric_id TEXT PRIMARY KEY,"
        "account_id TEXT NOT NULL,"
        "project_id TEXT NOT NULL,"
        "conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,"
        "pair_id TEXT NOT NULL,"
        "character_ref TEXT,"
        "assistant_identity TEXT,"
        "turn_kind TEXT NOT NULL,"
        "turn_id TEXT NOT NULL,"
        "task_id TEXT,"
        "engine_turn_id TEXT,"
        "source_message_id TEXT,"
        "provider TEXT,"
        "model TEXT,"
        "engine_type TEXT,"
        "reasoning_effort TEXT,"
        "status TEXT NOT NULL,"
        "started_at TEXT NOT NULL,"
        "first_event_at TEXT,"
        "completed_at TEXT,"
        "duration_ms INTEGER,"
        "first_event_latency_ms INTEGER,"
        "input_tokens INTEGER,"
        "output_tokens INTEGER,"
        "total_tokens INTEGER,"
        "tool_rounds INTEGER NOT NULL DEFAULT 0,"
        "compression_count INTEGER NOT NULL DEFAULT 0,"
        "approval_count INTEGER NOT NULL DEFAULT 0,"
        "failure_type TEXT,"
        "failure_message TEXT,"
        "origin TEXT NOT NULL DEFAULT 'desktop',"
        "remote_device_key TEXT,"
        "remote_device_name TEXT,"
        "created_at TEXT NOT NULL)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_turn_metrics_turn "
        "ON turn_metrics(conversation_id, turn_kind, turn_id)",
        "CREATE INDEX IF NOT EXISTS idx_turn_metrics_conversation "
        "ON turn_metrics(conversation_id, started_at DESC, metric_id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_turn_metrics_account "
        "ON turn_metrics(account_id, started_at DESC, metric_id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_turn_metrics_project "
        "ON turn_metrics(project_id, started_at DESC, metric_id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_turn_metrics_pair "
        "ON turn_metrics(pair_id, started_at DESC, metric_id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_turn_metrics_status "
        "ON turn_metrics(status, started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_turn_metrics_assistant "
        "ON turn_metrics(assistant_identity, started_at DESC, metric_id DESC)",
    ),
)


class SQLiteStore(StateStore):
    def __init__(
        self,
        database: Path,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """打开数据库并完成迁移。

        clock 只用于批量刷盘的 50ms 判定（默认 time.monotonic）；
        注入固定时钟后测试可以确定性地断言刷新时机。
        """
        database.parent.mkdir(parents=True, exist_ok=True)
        # O4.3：区分新库与旧库——新库 schema.sql 已建完整表结构，
        # 直接标记当前版本；旧库（有内容的文件）按 user_version 迁移
        fresh = not database.exists() or database.stat().st_size == 0
        self.database = database
        self._clock: Callable[[], float] = clock or time.monotonic
        # contract-v1 第 4 节：普通增量缓冲区。同一主键保留最后状态、
        # 位置保持首次出现，因此刷盘不会改变消息顺序。
        self._pending_writes: list[tuple[str, Any]] = []
        self._pending_index: dict[tuple[str, str], int] = {}
        self._first_pending_at: float | None = None
        self._stats: dict[str, int] = {
            "batch_transactions": 0,
            "batch_rows": 0,
            "max_batch_rows": 0,
            "flushes": 0,
            "immediate_writes": 0,
            "messages_written": 0,
            "tool_runs_written": 0,
        }
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.connection.executescript(schema)
        if fresh:
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.connection.commit()
        else:
            self._migrate()
        # V0.2 M3：默认本地账号对旧库（迁移里归入）与新库都保证存在
        self.connection.execute(
            "INSERT OR IGNORE INTO accounts("
            "account_id, username, display_name, password_hash, password_salt,"
            "created_at) VALUES ("
            "'default-local', 'default', '默认账号', '', '', datetime('now'))"
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO account_preferences(account_id) "
            "VALUES ('default-local')"
        )
        self.connection.commit()

    def close(self) -> None:
        """退出前强制刷盘再关闭连接。

        contract-v1 第 4 节：正常退出必须刷盘，且刷盘失败要原样暴露给
        调用链——这里不做 try/except 吞掉；连接仍在 finally 中关闭，
        避免失败时泄漏句柄。
        """
        try:
            self.flush()
        finally:
            self.connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _migrate(self) -> None:
        """旧库版本化迁移：按 ``PRAGMA user_version`` 逐级升级。

        schema.sql 用 CREATE TABLE IF NOT EXISTS，已存在的旧库不会自动
        补列/删列，依赖这里的迁移步骤。每完成一级立即写入对应
        user_version，中途失败不会重复执行已完成步骤。

        迁移语句带存在性守卫（B1 联调发现）：早期未版本化版本的库
        user_version=0 但 projects 已含 approval_mode 列、engine_sessions
        仍含死列，直接 ALTER 会报 duplicate/no such column，跳过即可。
        """
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        for target in range(version + 1, SCHEMA_VERSION + 1):
            # V0.3.9：每一级迁移是一个真实事务。sqlite3 默认隔离级别下
            # DDL 不进隐式事务（实测 CREATE/ALTER 直接自动提交），因此必须
            # 显式 BEGIN，失败时整级回滚且 user_version 不推进，重开即可
            # 干净重试；否则中断会留下“部分建表 + 版本未推进”的中间态。
            self.connection.execute("BEGIN")
            try:
                for statement in MIGRATIONS[target - 1]:
                    self._apply_migration(statement)
                self.connection.execute(f"PRAGMA user_version = {target}")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            self.connection.commit()

    def _apply_migration(self, statement: str) -> None:
        """执行单条迁移语句；ALTER TABLE ADD/DROP COLUMN 按现状跳过。"""
        match = re.match(r"ALTER TABLE (\w+) (ADD|DROP) COLUMN (\w+)", statement)
        if match:
            table, action, column = match.groups()
            names = [row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")]
            if (action == "ADD" and column in names) or (action == "DROP" and column not in names):
                return
        self.connection.execute(statement)

    def create_project(
        self,
        *,
        name: str,
        root_path: str,
        project_id: str | None = None,
        approval_mode: str = "request_approval",
        reasoning_effort: str = "low",
        account_id: str = "default-local",
    ) -> Project:
        project_id = project_id or str(uuid4())
        now = _now()
        self.connection.execute(
            """
            INSERT INTO projects(
                project_id, account_id, name, root_path, approval_mode,
                reasoning_effort, archived, created_at, last_opened_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                name=excluded.name,
                root_path=excluded.root_path,
                last_opened_at=excluded.last_opened_at
            """,
            (
                project_id,
                account_id,
                name,
                root_path,
                approval_mode,
                reasoning_effort,
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.get_project(project_id)

    def _update_project_column(
        self, column: str, value: str, project_id: str, *, touch_opened: bool
    ) -> None:
        if touch_opened:
            sql = f"UPDATE projects SET {column} = ?, last_opened_at = ? WHERE project_id = ?"
            params = (value, _now(), project_id)
        else:
            sql = f"UPDATE projects SET {column} = ? WHERE project_id = ?"
            params = (value, project_id)
        self.connection.execute(sql, params)
        self.connection.commit()

    def update_project_approval_mode(self, project_id: str, approval_mode: str) -> None:
        """保存输入区下拉框选择的审批模式（计划 A6）。"""
        self._update_project_column(
            "approval_mode", approval_mode, project_id, touch_opened=False
        )

    def update_project_reasoning_effort(
        self, project_id: str, reasoning_effort: str
    ) -> None:
        self._update_project_column(
            "reasoning_effort", reasoning_effort, project_id, touch_opened=False
        )

    def update_project_name(self, project_id: str, name: str) -> None:
        self._update_project_column("name", name, project_id, touch_opened=True)

    def update_project_root_path(self, project_id: str, root_path: str) -> None:
        self._update_project_column(
            "root_path", root_path, project_id, touch_opened=True
        )

    def mark_project_opened(self, project_id: str) -> Project:
        """记录最近打开项目，并返回更新后的项目对象。"""
        self.connection.execute(
            "UPDATE projects SET last_opened_at = ? WHERE project_id = ?",
            (_now(), project_id),
        )
        self.connection.commit()
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> Project:
        row = self.connection.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return self._project_from_row(row)

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        where = "" if include_archived else "WHERE archived = 0"
        rows = self.connection.execute(
            f"SELECT project_id FROM projects {where} "
            "ORDER BY julianday(last_opened_at) DESC"
        ).fetchall()
        return [self.get_project(row["project_id"]) for row in rows]

    def find_project_by_root_path(self, root_path: str) -> Project | None:
        """按规范化目录查找项目，避免同一目录重复创建项目记录。

        M4.5：必须检查所有项目（含已归档），否则再次选择已归档目录会
        静默创建第二条同根记录。
        """
        wanted = str(Path(root_path).resolve())
        for project in self.list_projects(include_archived=True):
            try:
                current = str(Path(project.root_path).resolve())
            except OSError:
                current = project.root_path
            if current.casefold() == wanted.casefold():
                return project
        return None

    def create_conversation(
        self,
        *,
        pair_id: str,
        project_id: str | None,
        title: str = "新聊天",
        last_mode: str = "chat",
        conversation_id: str | None = None,
        account_id: str = "",
        character_card_id: str | None = None,
    ) -> Conversation:
        conversation_id = conversation_id or str(uuid4())
        now = _now()
        self.connection.execute(
            """
            INSERT INTO conversations(
                conversation_id, account_id, project_id, pair_id, title, last_mode,
                archived, created_at, updated_at, character_card_id
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                updated_at=excluded.updated_at
            """,
            (
                conversation_id,
                account_id,
                project_id,
                pair_id,
                title,
                last_mode,
                now,
                now,
                character_card_id,
            ),
        )
        self.connection.commit()
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> Conversation:
        row = self.connection.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return Conversation(
            conversation_id=row["conversation_id"],
            account_id=row["account_id"] or "",
            project_id=row["project_id"],
            pair_id=row["pair_id"],
            title=row["title"],
            last_mode=row["last_mode"],
            archived=bool(row["archived"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            character_card_id=row["character_card_id"],
        )

    def list_conversations(
        self,
        project_id: str | None,
        *,
        include_archived: bool = False,
        account_id: str | None = None,
    ) -> list[Conversation]:
        """列出项目下的会话；``account_id`` 给定时按账号过滤。

        账号是完整隔离边界：即使会话挂到了不属于当前账号的项目，
        带账号过滤的列表也不会泄露。
        """
        archived_clause = "" if include_archived else "AND archived = 0"
        if project_id is None:
            if account_id:
                rows = self.connection.execute(
                    f"""SELECT conversation_id FROM conversations
                    WHERE project_id IS NULL AND account_id = ? {archived_clause}
                    ORDER BY julianday(updated_at) DESC""",
                    (account_id,),
                ).fetchall()
            else:
                rows = self.connection.execute(
                    f"""SELECT conversation_id FROM conversations
                    WHERE project_id IS NULL {archived_clause} ORDER BY julianday(updated_at) DESC"""
                ).fetchall()
        else:
            if account_id:
                rows = self.connection.execute(
                    f"""SELECT conversation_id FROM conversations
                    WHERE project_id = ? AND account_id = ? {archived_clause}
                    ORDER BY julianday(updated_at) DESC""",
                    (project_id, account_id),
                ).fetchall()
            else:
                rows = self.connection.execute(
                    f"""SELECT conversation_id FROM conversations
                    WHERE project_id = ? {archived_clause} ORDER BY julianday(updated_at) DESC""",
                    (project_id,),
                ).fetchall()
        return [self.get_conversation(row["conversation_id"]) for row in rows]

    def find_active_conversation(
        self,
        project_id: str,
        *,
        character_card_id: str | None = None,
        pair_id: str | None = None,
        account_id: str | None = None,
    ) -> Conversation | None:
        """V0.3.8 T6 / V0.3.9 契约 §1：按项目、角色卡与搭档找最新活跃会话。

        conversation.create 的 ``reuse_active`` 复用键；只匹配
        archived=0 的会话。无匹配返回 None。
        """
        where = ["project_id = ?", "archived = 0"]
        params: list[Any] = [project_id]
        if character_card_id is not None:
            where.append("character_card_id = ?")
            params.append(character_card_id)
        if pair_id is not None:
            where.append("pair_id = ?")
            params.append(pair_id)
        if account_id is not None:
            where.append("account_id = ?")
            params.append(account_id)
        sql = (
            f"SELECT conversation_id FROM conversations WHERE {' AND '.join(where)} "
            "ORDER BY julianday(updated_at) DESC LIMIT 1"
        )
        row = self.connection.execute(sql, tuple(params)).fetchone()
        if row is None:
            return None
        return self.get_conversation(row["conversation_id"])

    def save_message(self, message: Message) -> None:
        """同步落库单条消息（用户提交确认等强刷点使用）。

        contract-v1 第 4 节：必须用 ON CONFLICT DO UPDATE，不得用
        INSERT OR REPLACE——后者会换掉 rowid，让更新过的消息在按
        (created_at, message_id) 之外的历史排序里跳位。
        """
        with self.connection:
            self._write_message_row(message)
            self._touch_conversation(message.conversation_id, _now())
        self._stats["immediate_writes"] += 1

    def save_tool_run(self, tool_run: ToolRun) -> None:
        """同步落库单条工具记录（强刷点使用）。"""
        with self.connection:
            self._write_tool_run_row(tool_run)
            self._touch_conversation(tool_run.conversation_id, _now())
        self._stats["immediate_writes"] += 1

    def save_engine_session(
        self, conversation_id: str, session_ref: EngineSessionRef
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO engine_sessions(
                conversation_id, engine_type, session_ref, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                engine_type=excluded.engine_type,
                session_ref=excluded.session_ref,
                updated_at=excluded.updated_at
            """,
            (
                conversation_id,
                session_ref.engine_type,
                session_ref.model_dump_json(),
                _now(),
            ),
        )
        self.connection.commit()

    def clear_engine_sessions(self, account_id: str | None = None) -> None:
        """使指定账号（缺省全部）的引擎会话引用失效。

        运行时替换（供应商/引擎/项目根变化）后，旧 session 不能在新
        transport 上 resume；删除持久化引用后下一次任务会新开 session。
        """
        if account_id is None:
            self.connection.execute("DELETE FROM engine_sessions")
        else:
            self.connection.execute(
                "DELETE FROM engine_sessions WHERE conversation_id IN ("
                "SELECT conversation_id FROM conversations WHERE account_id = ?"
                ")",
                (account_id,),
            )
        self.connection.commit()

    def load_conversation(self, conversation_id: str) -> dict:
        conversation = self.get_conversation(conversation_id)
        message_rows = self.connection.execute(
            # contract-v1 第 1 节：不得用 rowid 作权威顺序；
            # 用 (created_at, message_id) 稳定排序，与 INSERT OR REPLACE
            # 换成 ON CONFLICT 后的行为一致。
            """SELECT message_json FROM messages
            WHERE conversation_id = ? ORDER BY created_at, message_id""",
            (conversation_id,),
        ).fetchall()
        tool_rows = self.connection.execute(
            """SELECT tool_json FROM tool_runs
            WHERE conversation_id = ? ORDER BY sequence, tool_call_id""",
            (conversation_id,),
        ).fetchall()
        session_row = self.connection.execute(
            "SELECT session_ref FROM engine_sessions WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return {
            "conversation": conversation,
            "messages": tuple(self._parse_message(row["message_json"]) for row in message_rows),
            "tool_runs": tuple(self._parse_tool_run(row["tool_json"]) for row in tool_rows),
            "engine_session": (
                EngineSessionRef.model_validate_json(session_row["session_ref"])
                if session_row is not None
                else None
            ),
        }

    @staticmethod
    def _parse_message(raw: str) -> Message:
        """解析持久化的消息，兼容旧协议的字段名。

        O4.4 把 Message.turn_id 更名为 engine_turn_id（extra="forbid"
        使旧 JSON 直接校验失败），这里把旧字段名重映射为新字段名，
        保证旧聊天重开时历史消息可以恢复。
        """
        try:
            return Message.model_validate_json(raw)
        except ValidationError:
            data = json.loads(raw)
            if "turn_id" in data:
                data["engine_turn_id"] = data.pop("turn_id")
                return Message.model_validate(data)
            raise

    @staticmethod
    def _parse_tool_run(raw: str) -> ToolRun:
        """解析持久化的工具卡片，兼容旧协议的状态值。

        A1 对齐协议前，工具状态使用过 "completed"；当前协议只允许
        running / succeeded / failed / denied，这里把旧值映射为 succeeded，
        保证旧聊天重开时工具卡片可以恢复。
        """
        try:
            return ToolRun.model_validate_json(raw)
        except ValidationError:
            data = json.loads(raw)
            if data.get("status") == "completed":
                data["status"] = "succeeded"
                return ToolRun.model_validate(data)
            raise

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        self.connection.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE conversation_id = ?",
            (title, _now(), conversation_id),
        )
        self.connection.commit()

    def update_conversation_mode(self, conversation_id: str, mode: str) -> None:
        """保存桌面端当前聊天模式，不改变历史消息语义。"""
        self.connection.execute(
            "UPDATE conversations SET last_mode = ?, updated_at = ? WHERE conversation_id = ?",
            (mode, _now(), conversation_id),
        )
        self.connection.commit()

    def archive_conversation(self, conversation_id: str) -> None:
        """归档单个聊天；项目和其他聊天保持不变。"""
        self.connection.execute(
            "UPDATE conversations SET archived = 1, updated_at = ? WHERE conversation_id = ?",
            (_now(), conversation_id),
        )
        self.connection.commit()

    def archive_project(self, project_id: str) -> None:
        self.connection.execute("UPDATE projects SET archived = 1 WHERE project_id = ?", (project_id,))
        self.connection.execute(
            "UPDATE conversations SET archived = 1 WHERE project_id = ?", (project_id,)
        )
        self.connection.commit()

    def unarchive_project(self, project_id: str) -> Project:
        """M4.5：恢复已归档项目（含其聊天），供再次选择同一目录时复用旧记录。"""
        self.connection.execute(
            "UPDATE projects SET archived = 0, last_opened_at = ? WHERE project_id = ?",
            (_now(), project_id),
        )
        self.connection.execute(
            "UPDATE conversations SET archived = 0 WHERE project_id = ?",
            (project_id,),
        )
        self.connection.commit()
        return self.get_project(project_id)

    # ------------------------------------------------------------------ V0.2 M2 会话队列

    def enqueue_queue_item(
        self,
        *,
        conversation_id: str,
        target: str,
        text: str,
        intent: str = "followup",
        account_id: str = "",
    ) -> dict:
        """入队（先持久化，再向前端确认）。steer 置队首并重排其余 queued 项。"""
        queue_item_id = str(uuid4())
        if intent == "steer":
            position = 0
            self.connection.execute(
                "UPDATE conversation_inbox SET position = position + 1 "
                "WHERE conversation_id = ? AND status = 'queued'",
                (conversation_id,),
            )
        else:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(position), -1) FROM conversation_inbox "
                "WHERE conversation_id = ? AND status = 'queued'",
                (conversation_id,),
            ).fetchone()
            position = int(row[0]) + 1
        self.connection.execute(
            "INSERT INTO conversation_inbox("
            "queue_item_id, account_id, conversation_id, target, text, intent,"
            "position, status, created_at, source_message_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, NULL)",
            (queue_item_id, account_id, conversation_id, target, text, intent, position, _now()),
        )
        self.connection.commit()
        return self.get_queue_item(queue_item_id)

    def get_queue_item(self, queue_item_id: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM conversation_inbox WHERE queue_item_id = ?", (queue_item_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown queue_item_id: {queue_item_id}")
        return self._queue_item_dict(row)

    def list_queue_items(self, conversation_id: str) -> list[dict]:
        """会话内按 position 升序的队列快照（含 withdrawn 历史）。"""
        rows = self.connection.execute(
            "SELECT * FROM conversation_inbox WHERE conversation_id = ? "
            "ORDER BY position, created_at",
            (conversation_id,),
        ).fetchall()
        return [self._queue_item_dict(row) for row in rows]

    def peek_queue_item(self, conversation_id: str) -> dict | None:
        """下一个待派发项（最前 queued）。"""
        row = self.connection.execute(
            "SELECT * FROM conversation_inbox WHERE conversation_id = ? AND status = 'queued' "
            "ORDER BY position, created_at LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return self._queue_item_dict(row) if row is not None else None

    def edit_queue_item(self, queue_item_id: str, text: str) -> dict:
        """编辑尚未派发的队列项文本。"""
        self.connection.execute(
            "UPDATE conversation_inbox SET text = ? WHERE queue_item_id = ? AND status = 'queued'",
            (text, queue_item_id),
        )
        self.connection.commit()
        return self.get_queue_item(queue_item_id)

    def withdraw_queue_item(self, queue_item_id: str) -> dict:
        """撤回队列项（状态置 withdrawn，不再派发）。"""
        self.connection.execute(
            "UPDATE conversation_inbox SET status = 'withdrawn' WHERE queue_item_id = ?",
            (queue_item_id,),
        )
        self.connection.commit()
        return self.get_queue_item(queue_item_id)

    def prioritize_queue_item(self, queue_item_id: str) -> None:
        """把 queued 项置队首，其余 queued 项依次后移。"""
        row = self.connection.execute(
            "SELECT * FROM conversation_inbox WHERE queue_item_id = ? AND status = 'queued'",
            (queue_item_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"queue_item 不存在或已派发: {queue_item_id}")
        self.connection.execute(
            "UPDATE conversation_inbox SET position = position + 1 "
            "WHERE conversation_id = ? AND status = 'queued' AND queue_item_id != ?",
            (row["conversation_id"], queue_item_id),
        )
        self.connection.execute(
            "UPDATE conversation_inbox SET position = 0 WHERE queue_item_id = ?",
            (queue_item_id,),
        )
        self.connection.commit()

    def set_queue_item_status(self, queue_item_id: str, status: str) -> dict:
        self.connection.execute(
            "UPDATE conversation_inbox SET status = ? WHERE queue_item_id = ?",
            (status, queue_item_id),
        )
        self.connection.commit()
        return self.get_queue_item(queue_item_id)

    def delete_queue_item(self, queue_item_id: str) -> None:
        """派发完成即删除（不再占快照）。"""
        self.connection.execute(
            "DELETE FROM conversation_inbox WHERE queue_item_id = ?", (queue_item_id,)
        )
        self.connection.commit()

    @staticmethod
    def _queue_item_dict(row: sqlite3.Row) -> dict:
        return {
            "queue_item_id": row["queue_item_id"],
            "account_id": row["account_id"],
            "conversation_id": row["conversation_id"],
            "target": row["target"],
            "text": row["text"],
            "intent": row["intent"],
            "position": int(row["position"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "source_message_id": row["source_message_id"],
        }

    # ------------------------------------------------------------------ V0.2 M3 本地账号

    @staticmethod
    def _derive_password(password: str, salt_b64: str) -> str:
        """PBKDF2-SHA256 派生（200k 迭代），与 salt 一起存库。"""
        salt = base64.b64decode(salt_b64)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, 200_000
        )
        return base64.b64encode(digest).decode()

    @staticmethod
    def _new_salt() -> str:
        return base64.b64encode(os.urandom(16)).decode()

    def create_account(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        account_id: str | None = None,
    ) -> dict:
        """注册本地账号；密码只存派生结果。"""
        account_id = account_id or str(uuid4())
        salt = self._new_salt()
        now = _now()
        try:
            self.connection.execute(
                "INSERT INTO accounts("
                "account_id, username, display_name, password_hash, password_salt,"
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    account_id,
                    username,
                    display_name,
                    self._derive_password(password, salt),
                    salt,
                    now,
                ),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO account_preferences(account_id) VALUES (?)",
                (account_id,),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("登录名已存在") from exc
        self.connection.commit()
        return self.get_account(account_id)

    def get_account(self, account_id: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown account: {account_id}")
        return self._account_dict(row)

    def get_account_by_username(self, username: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        return self._account_dict(row) if row is not None else None

    def list_accounts(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM accounts ORDER BY created_at"
        ).fetchall()
        return [self._account_dict(row) for row in rows]

    def verify_password(self, account_id: str, password: str) -> bool:
        row = self.connection.execute(
            "SELECT password_hash, password_salt FROM accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            return False
        # 未设置密码（迁移默认账号）→ 空密码可登录，首次引导时设置
        if not row["password_hash"]:
            return password == ""
        return (
            self._derive_password(password, row["password_salt"]) == row["password_hash"]
        )

    def update_last_login(self, account_id: str) -> dict:
        self.connection.execute(
            "UPDATE accounts SET last_login_at = ? WHERE account_id = ?",
            (_now(), account_id),
        )
        self.connection.commit()
        return self.get_account(account_id)

    def update_account_profile(
        self, account_id: str, *, display_name: str | None = None, avatar: str | None = None
    ) -> dict:
        row = self.connection.execute(
            "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown account: {account_id}")
        self.connection.execute(
            "UPDATE accounts SET display_name = ?, avatar = ? WHERE account_id = ?",
            (
                display_name if display_name is not None else row["display_name"],
                avatar if avatar is not None else row["avatar"],
                account_id,
            ),
        )
        self.connection.commit()
        return self.get_account(account_id)

    def change_password(self, account_id: str, old_password: str, new_password: str) -> bool:
        """改密：旧密码校验通过才更新。"""
        if not self.verify_password(account_id, old_password):
            return False
        salt = self._new_salt()
        self.connection.execute(
            "UPDATE accounts SET password_hash = ?, password_salt = ? WHERE account_id = ?",
            (self._derive_password(new_password, salt), salt, account_id),
        )
        self.connection.commit()
        return True

    def set_onboarding_complete(self, account_id: str, completed: bool = True) -> None:
        self.connection.execute(
            "UPDATE accounts SET onboarding_complete = ? WHERE account_id = ?",
            (1 if completed else 0, account_id),
        )
        self.connection.commit()

    @staticmethod
    def _account_dict(row: sqlite3.Row) -> dict:
        return {
            "account_id": row["account_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "avatar": row["avatar"],
            "last_login_at": row["last_login_at"],
            "onboarding_complete": bool(row["onboarding_complete"]),
            "theme": row["theme"],
        }

    # ------------------------------------------------------------------ V0.2 M3 账号级配置

    def _get_account_config(
        self, table: str, column: str, account_id: str, key: str
    ) -> str | None:
        row = self.connection.execute(
            f"SELECT {column} FROM {table} WHERE account_id = ? AND key = ?",
            (account_id, key),
        ).fetchone()
        return row[column] if row is not None else None

    def _set_account_config(
        self, table: str, column: str, account_id: str, key: str, value: str
    ) -> None:
        self.connection.execute(
            f"INSERT INTO {table}(account_id, key, {column}) VALUES (?, ?, ?) "
            f"ON CONFLICT(account_id, key) DO UPDATE SET {column} = excluded.{column}",
            (account_id, key, value),
        )
        self.connection.commit()

    def get_config(self, account_id: str, key: str) -> str | None:
        return self._get_account_config("provider_configs", "value", account_id, key)

    def set_config(self, account_id: str, key: str, value: str) -> None:
        self._set_account_config("provider_configs", "value", account_id, key, value)

    def set_configs(self, account_id: str, updates: dict[str, str]) -> None:
        for key, value in updates.items():
            self.set_config(account_id, key, value)

    def get_secret(self, account_id: str, key: str) -> str | None:
        return self._get_account_config("secret_refs", "secret", account_id, key)

    def set_secret(self, account_id: str, key: str, secret: str) -> None:
        self._set_account_config("secret_refs", "secret", account_id, key, secret)

    def set_configs_and_secrets(
        self,
        account_id: str,
        config_updates: dict[str, str] | None = None,
        secret_updates: dict[str, str] | None = None,
    ) -> None:
        """在一个 SQLite 事务里写入全部配置与密钥。

        任一条写入失败都会回滚整个事务，调用方数据库保持旧值；成功后才
        提交，供配置保存的“先验证后提交”流程使用。
        """
        config_updates = config_updates or {}
        secret_updates = secret_updates or {}
        with self.connection:
            for key, value in config_updates.items():
                self.connection.execute(
                    "INSERT INTO provider_configs(account_id, key, value) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(account_id, key) DO UPDATE SET value = excluded.value",
                    (account_id, key, value),
                )
            for key, value in secret_updates.items():
                self.connection.execute(
                    "INSERT INTO secret_refs(account_id, key, secret) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(account_id, key) DO UPDATE SET secret = excluded.secret",
                    (account_id, key, value),
                )

    def get_preference(self, account_id: str, key: str) -> str | None:
        row = self.connection.execute(
            f"SELECT {key} FROM account_preferences WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return str(row[key]) if row is not None else None

    def set_preference(self, account_id: str, key: str, value: str) -> None:
        allowed = {"theme", "vad_enabled", "last_mode"}
        if key not in allowed:
            raise ValueError(f"unknown preference: {key}")
        self.connection.execute(
            f"UPDATE account_preferences SET {key} = ? WHERE account_id = ?",
            (value, account_id),
        )
        self.connection.commit()

    def get_app_state(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row is not None else None

    def set_app_state(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO app_state(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.connection.commit()

    def list_projects_for_account(self, account_id: str) -> list[Project]:
        rows = self.connection.execute(
            "SELECT * FROM projects WHERE account_id = ? AND archived = 0 "
            "ORDER BY julianday(last_opened_at) DESC",
            (account_id,),
        ).fetchall()
        return [self._project_from_row(row) for row in rows]

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> Project:
        return Project(
            project_id=row["project_id"],
            account_id=row["account_id"] or "",
            name=row["name"],
            root_path=row["root_path"],
            approval_mode=row["approval_mode"],
            reasoning_effort=row["reasoning_effort"],
            archived=bool(row["archived"]),
            created_at=_dt(row["created_at"]),
            last_opened_at=_dt(row["last_opened_at"]),
        )

    def _touch_conversation(self, conversation_id: str, now: str | None = None) -> None:
        """更新聊天最近持久化业务变化时间（列表排序用，契约第 1 节）。

        批量刷盘时整批只调用一次/会话，避免每条消息都写一次。
        """
        self.connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
            (now or _now(), conversation_id),
        )

    # ------------------------------------------------------------------ V0.3.9 批量增量落库

    def enqueue_message(self, message: Message) -> None:
        """把消息放入普通增量缓冲（contract-v1 第 4 节）。

        同一 message_id 只保留最后状态，位置保持首次出现；达到 50 条
        立即刷盘。用户提交确认等强刷点仍走同步的 save_message。
        """
        self._buffer_write("message", message, ("message", message.message_id))

    def enqueue_tool_run(self, tool_run: ToolRun) -> None:
        """把工具记录放入普通增量缓冲；主键是 (conversation_id, tool_call_id)。"""
        key = ("tool_run", f"{tool_run.conversation_id}\x00{tool_run.tool_call_id}")
        self._buffer_write("tool_run", tool_run, key)

    def save_messages(self, messages: Iterable[Message]) -> int:
        """一个事务写入多条消息（导入/迁移/测试），顺序按入参顺序。"""
        return self._write_rows([("message", item) for item in messages])

    def save_tool_runs(self, tool_runs: Iterable[ToolRun]) -> int:
        """一个事务写入多条工具记录，顺序按入参顺序。"""
        return self._write_rows([("tool_run", item) for item in tool_runs])

    @property
    def pending_writes(self) -> int:
        """当前缓冲区中的普通增量条数。"""
        return len(self._pending_writes)

    def next_flush_deadline(self, now: float | None = None) -> float | None:
        """返回最老挂起写应刷盘的绝对单调时间；没有挂起写时返回 None。

        接线方用它调度定时刷盘（loop.call_at），到点调用 flush_if_due。
        """
        if not self._pending_writes or self._first_pending_at is None:
            return None
        return self._first_pending_at + BATCH_MAX_DELAY_SECONDS

    def flush_if_due(self, now: float | None = None) -> bool:
        """按 50 条 / 50ms 阈值刷盘；未到阈值返回 False，不做任何写入。"""
        if not self._pending_writes:
            return False
        current = self._clock() if now is None else now
        due = len(self._pending_writes) >= BATCH_MAX_WRITES
        if not due and self._first_pending_at is not None:
            due = (current - self._first_pending_at) >= BATCH_MAX_DELAY_SECONDS
        if not due:
            return False
        self.flush()
        return True

    def flush(self) -> int:
        """把缓冲写入一个非空事务；失败原样抛出且缓冲保留。

        返回写入行数。事务失败时不丢弃缓冲，调用链拿到原始异常后可以
        决定重试或退出，不把失败写成成功。
        """
        if not self._pending_writes:
            return 0
        rows = list(self._pending_writes)
        written = self._write_rows(rows)
        del self._pending_writes[: len(rows)]
        self._pending_index.clear()
        self._first_pending_at = None
        return written

    def stats(self) -> dict[str, int]:
        """写入计数器（测试与诊断用，不参与业务语义）。"""
        return dict(self._stats)

    def _buffer_write(self, kind: str, payload: Any, key: tuple[str, str]) -> None:
        if self._first_pending_at is None:
            self._first_pending_at = self._clock()
        index = self._pending_index.get(key)
        if index is None:
            self._pending_index[key] = len(self._pending_writes)
            self._pending_writes.append((kind, payload))
        else:
            # 同一主键保留最后状态，位置保持首次出现——刷盘顺序稳定。
            self._pending_writes[index] = (kind, payload)
        if len(self._pending_writes) >= BATCH_MAX_WRITES:
            self.flush()

    def _write_rows(self, rows: Sequence[tuple[str, Any]]) -> int:
        """一个事务写入若干行；每个受影响聊天只更新一次 updated_at。"""
        if not rows:
            return 0
        touched: list[str] = []
        seen: set[str] = set()
        with self.connection:
            for kind, payload in rows:
                if kind == "message":
                    self._write_message_row(payload)
                elif kind == "tool_run":
                    self._write_tool_run_row(payload)
                else:
                    raise ValueError(f"未知增量类型：{kind}")
                conversation_id = payload.conversation_id
                if conversation_id not in seen:
                    seen.add(conversation_id)
                    touched.append(conversation_id)
            now = _now()
            for conversation_id in touched:
                self._touch_conversation(conversation_id, now)
        self._stats["batch_transactions"] += 1
        self._stats["batch_rows"] += len(rows)
        self._stats["max_batch_rows"] = max(self._stats["max_batch_rows"], len(rows))
        self._stats["flushes"] += 1
        self._stats["messages_written"] += sum(1 for kind, _ in rows if kind == "message")
        self._stats["tool_runs_written"] += sum(1 for kind, _ in rows if kind == "tool_run")
        return len(rows)

    def _write_message_row(self, message: Message) -> None:
        """写单条消息；ON CONFLICT DO UPDATE 保持主键与稳定顺序。"""
        self.connection.execute(
            """
            INSERT INTO messages(
                message_id, conversation_id, source, kind, created_at, message_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                conversation_id=excluded.conversation_id,
                source=excluded.source,
                kind=excluded.kind,
                created_at=excluded.created_at,
                message_json=excluded.message_json
            """,
            (
                message.message_id,
                message.conversation_id,
                enum_value(message.source),
                enum_value(message.kind),
                message.created_at.isoformat(),
                message.model_dump_json(),
            ),
        )

    def _write_tool_run_row(self, tool_run: ToolRun) -> None:
        self.connection.execute(
            """
            INSERT INTO tool_runs(
                conversation_id, tool_call_id, task_id, engine_turn_id,
                sequence, status, tool_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id, tool_call_id) DO UPDATE SET
                task_id=excluded.task_id,
                engine_turn_id=excluded.engine_turn_id,
                sequence=excluded.sequence,
                status=excluded.status,
                tool_json=excluded.tool_json
            """,
            (
                tool_run.conversation_id,
                tool_run.tool_call_id,
                tool_run.task_id,
                tool_run.engine_turn_id,
                tool_run.sequence,
                tool_run.status,
                tool_run.model_dump_json(),
            ),
        )

    def load_messages_page(
        self,
        conversation_id: str,
        *,
        limit: int = 200,
        before_message_id: str | None = None,
    ) -> list[Message]:
        """按 (created_at, message_id) 稳定顺序读取一页消息（升序返回）。

        before_message_id 给定时返回它之前的 limit 条；缺省返回最新
        limit 条。供长聊天分页装载使用，不改变 load_conversation 的全量语义。
        """
        if limit < 1:
            raise ValueError("limit 必须 >= 1")
        params: list[Any] = [conversation_id]
        where = "conversation_id = ?"
        if before_message_id is not None:
            anchor = self.connection.execute(
                "SELECT created_at, message_id FROM messages "
                "WHERE message_id = ? AND conversation_id = ?",
                (before_message_id, conversation_id),
            ).fetchone()
            if anchor is None:
                raise KeyError(
                    f"unknown message_id in conversation: {before_message_id}"
                )
            where += " AND (created_at, message_id) < (?, ?)"
            params.extend([anchor["created_at"], anchor["message_id"]])
        params.append(limit)
        rows = self.connection.execute(
            f"SELECT message_json FROM messages WHERE {where} "
            "ORDER BY created_at DESC, message_id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [self._parse_message(row["message_json"]) for row in reversed(rows)]

    # ------------------------------------------------------------------ V0.3.9 聊天摘要

    def upsert_summary(self, summary: ConversationSummary) -> ConversationSummary:
        """写入或更新一条摘要（按会话 + 覆盖区间幂等）。

        区间已存在时保留原 summary_id 与 created_at，只更新内容与状态，
        使投影引用不会因重跑而漂移；返回值以数据库当前行为准。
        """
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO conversation_summaries(
                    summary_id, conversation_id, covers_from_message_id,
                    covers_to_message_id, covers_message_count, content,
                    provider, model, status, error_code, error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    conversation_id, covers_from_message_id, covers_to_message_id
                ) DO UPDATE SET
                    covers_message_count=excluded.covers_message_count,
                    content=excluded.content,
                    provider=excluded.provider,
                    model=excluded.model,
                    status=excluded.status,
                    error_code=excluded.error_code,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    summary.summary_id,
                    summary.conversation_id,
                    summary.covers_from_message_id,
                    summary.covers_to_message_id,
                    summary.covers_message_count,
                    summary.content,
                    summary.provider,
                    summary.model,
                    summary.status,
                    summary.error_code,
                    summary.error,
                    summary.created_at.isoformat(),
                    summary.updated_at.isoformat(),
                ),
            )
        return self.get_summary_by_range(
            summary.conversation_id,
            covers_from_message_id=summary.covers_from_message_id,
            covers_to_message_id=summary.covers_to_message_id,
        )

    def update_summary(self, summary_id: str, **fields: Any) -> ConversationSummary:
        """按字段更新摘要；未传字段保持原值，失败原样抛出。"""
        allowed = {
            "content",
            "provider",
            "model",
            "status",
            "error_code",
            "error",
            "covers_message_count",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"不支持的摘要字段：{unknown}")
        if "status" in fields:
            allowed_status = {item.value for item in SummaryStatus}
            if fields["status"] not in allowed_status:
                raise ValueError(f"未知摘要状态：{fields['status']}")
        if not fields:
            return self.get_summary(summary_id)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        params = list(fields.values())
        params.extend([_now(), summary_id])
        with self.connection:
            cursor = self.connection.execute(
                f"UPDATE conversation_summaries SET {assignments}, updated_at = ? "
                "WHERE summary_id = ?",
                tuple(params),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown summary_id: {summary_id}")
        return self.get_summary(summary_id)

    def get_summary(self, summary_id: str) -> ConversationSummary:
        row = self.connection.execute(
            "SELECT * FROM conversation_summaries WHERE summary_id = ?", (summary_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown summary_id: {summary_id}")
        return self._summary_from_row(row)

    def get_summary_by_range(
        self,
        conversation_id: str,
        *,
        covers_from_message_id: str,
        covers_to_message_id: str,
    ) -> ConversationSummary:
        row = self.connection.execute(
            "SELECT * FROM conversation_summaries WHERE conversation_id = ? "
            "AND covers_from_message_id = ? AND covers_to_message_id = ?",
            (conversation_id, covers_from_message_id, covers_to_message_id),
        ).fetchone()
        if row is None:
            raise KeyError(
                "unknown summary range: "
                f"{conversation_id} {covers_from_message_id}..{covers_to_message_id}"
            )
        return self._summary_from_row(row)

    def list_summaries(
        self, conversation_id: str, *, status: str | None = None
    ) -> list[ConversationSummary]:
        """列出该聊天的摘要（按覆盖区间起点排序，只在本聊天内读取）。"""
        if status is None:
            rows = self.connection.execute(
                "SELECT * FROM conversation_summaries WHERE conversation_id = ? "
                "ORDER BY covers_from_message_id, summary_id",
                (conversation_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM conversation_summaries WHERE conversation_id = ? "
                "AND status = ? ORDER BY covers_from_message_id, summary_id",
                (conversation_id, status),
            ).fetchall()
        return [self._summary_from_row(row) for row in rows]

    def latest_completed_summary(
        self, conversation_id: str
    ) -> ConversationSummary | None:
        """最近一条 completed 摘要（压缩终点查询用）。"""
        row = self.connection.execute(
            "SELECT * FROM conversation_summaries WHERE conversation_id = ? "
            "AND status = ? ORDER BY updated_at DESC, summary_id DESC LIMIT 1",
            (conversation_id, SummaryStatus.COMPLETED.value),
        ).fetchone()
        return self._summary_from_row(row) if row is not None else None

    @staticmethod
    def _summary_from_row(row: sqlite3.Row) -> ConversationSummary:
        return ConversationSummary(
            summary_id=row["summary_id"],
            conversation_id=row["conversation_id"],
            covers_from_message_id=row["covers_from_message_id"],
            covers_to_message_id=row["covers_to_message_id"],
            covers_message_count=int(row["covers_message_count"]),
            content=row["content"] or "",
            provider=row["provider"],
            model=row["model"],
            status=row["status"],
            error_code=row["error_code"],
            error=row["error"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    # ------------------------------------------------------------------ V0.3.9 持久化投影

    def append_projection_entries(self, entries: Sequence[ProjectionEntry]) -> int:
        """批量追加投影条目（一个事务）。位置冲突直接报 IntegrityError。"""
        if not entries:
            return 0
        with self.connection:
            for entry in entries:
                self.connection.execute(
                    """
                    INSERT INTO conversation_projections(
                        conversation_id, entry_id, position, kind, message_id,
                        summary_id, tool_call_id, covered_by_summary_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(conversation_id, entry_id) DO UPDATE SET
                        position=excluded.position,
                        kind=excluded.kind,
                        message_id=excluded.message_id,
                        summary_id=excluded.summary_id,
                        tool_call_id=excluded.tool_call_id,
                        covered_by_summary_id=excluded.covered_by_summary_id
                    """,
                    (
                        entry.conversation_id,
                        entry.entry_id,
                        entry.position,
                        entry.kind,
                        entry.message_id,
                        entry.summary_id,
                        entry.tool_call_id,
                        entry.covered_by_summary_id,
                        entry.created_at.isoformat(),
                    ),
                )
        return len(entries)

    def append_projection_entry(self, entry: ProjectionEntry) -> ProjectionEntry:
        self.append_projection_entries([entry])
        return entry

    def list_projection(self, conversation_id: str) -> list[ProjectionEntry]:
        """按 position 升序返回投影条目（顺序权威是 position，不是 rowid）。"""
        rows = self.connection.execute(
            "SELECT * FROM conversation_projections WHERE conversation_id = ? "
            "ORDER BY position, entry_id",
            (conversation_id,),
        ).fetchall()
        return [self._projection_from_row(row) for row in rows]

    def delete_projection_entry(self, conversation_id: str, entry_id: str) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM conversation_projections "
            "WHERE conversation_id = ? AND entry_id = ?",
            (conversation_id, entry_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def collapse_projection_span(
        self,
        conversation_id: str,
        *,
        covers_from_message_id: str,
        covers_to_message_id: str,
        summary_id: str,
    ) -> int:
        """把一段连续原文条目折叠为一条摘要引用（契约第 2 节）。

        - 区间必须连续且只包含 kind=message 的条目，否则 ValueError；
        - 被折叠的原文条目从投影中删除（原文仍在 messages 永久保留），
          投影里换成一条 kind=summary 的条目，位置保持区间起点；
        - 区间之后的条目位置整体前移，position 保持 0..n-1 稠密。
        返回被折叠的原文条目数。
        """
        entries = self.list_projection(conversation_id)
        from_index = None
        to_index = None
        for index, entry in enumerate(entries):
            if entry.kind != ProjectionKind.MESSAGE.value:
                continue
            if entry.message_id == covers_from_message_id:
                from_index = index
            if entry.message_id == covers_to_message_id:
                to_index = index
        if from_index is None or to_index is None:
            raise KeyError("投影中找不到摘要区间端点")
        if to_index < from_index:
            raise ValueError("摘要区间终点在起点之前")
        span = entries[from_index : to_index + 1]
        if any(entry.kind != ProjectionKind.MESSAGE.value for entry in span):
            raise ValueError("摘要区间必须连续且只包含原文条目")
        base_position = span[0].position
        removed = len(span)
        with self.connection:
            self.connection.execute(
                "DELETE FROM conversation_projections "
                f"WHERE conversation_id = ? AND entry_id IN ({','.join('?' * removed)})",
                (conversation_id, *(entry.entry_id for entry in span)),
            )
            self.connection.execute(
                "UPDATE conversation_projections SET position = position - ? "
                "WHERE conversation_id = ? AND position > ?",
                (removed - 1, conversation_id, span[-1].position),
            )
            self.connection.execute(
                """
                INSERT INTO conversation_projections(
                    conversation_id, entry_id, position, kind, message_id,
                    summary_id, tool_call_id, covered_by_summary_id, created_at
                ) VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, ?)
                """,
                (
                    conversation_id,
                    str(uuid4()),
                    base_position,
                    ProjectionKind.SUMMARY.value,
                    summary_id,
                    _now(),
                ),
            )
        return removed

    def role_message_stats_since(
        self, conversation_id: str, *, after_message_id: str | None = None
    ) -> dict[str, int]:
        """自上次摘要终点以来的角色消息条数与 UTF-8 正文字节数（契约第 2 节）。

        计数口径是结构性的：source 为 user/character、origin 不为
        character_delegation、正文非空；流式 delta、助手、工具、思考、
        系统状态都不计。这里不做任何语义判断。
        """
        params: list[Any] = [conversation_id]
        where = (
            "conversation_id = ? "
            "AND source IN ('user', 'character') "
            "AND COALESCE(json_extract(message_json, '$.origin'), '') "
            "<> 'character_delegation' "
            "AND COALESCE(json_extract(message_json, '$.text'), '') <> ''"
        )
        if after_message_id is not None:
            anchor_row = self.connection.execute(
                "SELECT created_at, message_id FROM messages WHERE message_id = ?",
                (after_message_id,),
            ).fetchone()
            if anchor_row is None:
                raise KeyError(f"unknown message_id: {after_message_id}")
            where += " AND (created_at, message_id) > (?, ?)"
            params.extend([anchor_row["created_at"], anchor_row["message_id"]])
        row = self.connection.execute(
            "SELECT COUNT(*) AS message_count, "
            "COALESCE(SUM(LENGTH(CAST(json_extract(message_json, '$.text') AS BLOB))), 0) "
            "AS text_bytes "
            f"FROM messages WHERE {where}",
            tuple(params),
        ).fetchone()
        return {
            "message_count": int(row["message_count"]),
            "text_bytes": int(row["text_bytes"]),
        }

    @staticmethod
    def _projection_from_row(row: sqlite3.Row) -> ProjectionEntry:
        return ProjectionEntry(
            conversation_id=row["conversation_id"],
            entry_id=row["entry_id"],
            position=int(row["position"]),
            kind=row["kind"],
            message_id=row["message_id"],
            summary_id=row["summary_id"],
            tool_call_id=row["tool_call_id"],
            covered_by_summary_id=row["covered_by_summary_id"],
            created_at=_dt(row["created_at"]),
        )

    # ------------------------------------------------------------------ V0.3.9 配对长期记忆

    def upsert_memory(self, memory: PairMemory) -> PairMemory:
        """写入或更新一条长期记忆（同作用域同内容幂等）。

        作用域五个分量必须全部非空，否则 ValueError——项目为空的日常
        聊天不读写长期记忆。返回值以数据库当前行为准（已存在时保留
        原 memory_id 与 created_at）。
        """
        memory.scope()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO pair_memories(
                    memory_id, account_id, project_id, pair_id, character_ref,
                    assistant_identity, conversation_id, content, status,
                    provider, model, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    account_id, project_id, pair_id, character_ref,
                    assistant_identity, content
                ) WHERE status = 'active' DO UPDATE SET
                    conversation_id=excluded.conversation_id,
                    status=excluded.status,
                    provider=excluded.provider,
                    model=excluded.model,
                    updated_at=excluded.updated_at
                """,
                (
                    memory.memory_id,
                    memory.account_id,
                    memory.project_id,
                    memory.pair_id,
                    memory.character_ref,
                    memory.assistant_identity,
                    memory.conversation_id,
                    memory.content,
                    memory.status,
                    memory.provider,
                    memory.model,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                ),
            )
        return self.get_memory_by_content(memory.scope(), content=memory.content)

    def update_memory(
        self,
        memory_id: str,
        *,
        scope: MemoryScope | None = None,
        **fields: Any,
    ) -> PairMemory:
        """更新记忆内容或状态；未传字段保持原值。

        可选传入 scope 校验并锁定作用域（含 assistant_identity），不匹配报 KeyError(memory_scope_mismatch)。
        """
        allowed = {"content", "status", "provider", "model"}
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"不支持的记忆字段：{unknown}")
        if "status" in fields:
            allowed_status = {item.value for item in MemoryStatus}
            if fields["status"] not in allowed_status:
                raise ValueError(f"未知记忆状态：{fields['status']}")
        if scope is not None:
            self.get_memory(memory_id, scope=scope)
        if not fields:
            return self.get_memory(memory_id, scope=scope)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        params = list(fields.values())
        params.append(_now())
        where = "WHERE memory_id = ?"
        params.append(memory_id)
        if scope is not None:
            where += (
                " AND account_id = ? AND project_id = ? AND pair_id = ? "
                "AND character_ref = ? AND assistant_identity = ?"
            )
            params.extend(scope.as_key())
        with self.connection:
            cursor = self.connection.execute(
                f"UPDATE pair_memories SET {assignments}, updated_at = ? {where}",
                tuple(params),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown memory_id: {memory_id}")
        return self.get_memory(memory_id, scope=scope)

    def delete_memory(
        self, memory_id: str, *, scope: MemoryScope | None = None
    ) -> PairMemory:
        """软删除：status 置 deleted 并持久化（真实状态，不物理删除）。"""
        return self.update_memory(
            memory_id, scope=scope, status=MemoryStatus.DELETED.value
        )

    def get_memory(
        self, memory_id: str, *, scope: MemoryScope | None = None
    ) -> PairMemory:
        if scope is not None:
            row = self.connection.execute(
                "SELECT * FROM pair_memories WHERE memory_id = ? AND account_id = ? "
                "AND project_id = ? AND pair_id = ? AND character_ref = ? "
                "AND assistant_identity = ?",
                (memory_id, *scope.as_key()),
            ).fetchone()
            if row is None:
                existing = self.connection.execute(
                    "SELECT 1 FROM pair_memories WHERE memory_id = ?", (memory_id,)
                ).fetchone()
                if existing is not None:
                    raise KeyError(f"memory_scope_mismatch: {memory_id}")
                raise KeyError(f"unknown memory_id: {memory_id}")
            return self._memory_from_row(row)
        row = self.connection.execute(
            "SELECT * FROM pair_memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown memory_id: {memory_id}")
        return self._memory_from_row(row)

    def get_memory_by_content(self, scope: MemoryScope, *, content: str) -> PairMemory:
        row = self.connection.execute(
            "SELECT * FROM pair_memories WHERE account_id = ? AND project_id = ? "
            "AND pair_id = ? AND character_ref = ? AND assistant_identity = ? "
            "AND content = ?",
            (*scope.as_key(), content),
        ).fetchone()
        if row is None:
            raise KeyError("unknown memory content in scope")
        return self._memory_from_row(row)

    def list_memories(
        self,
        scope: MemoryScope,
        *,
        status: str | None = MemoryStatus.ACTIVE.value,
        limit: int | None = None,
    ) -> list[PairMemory]:
        """按作用域读取记忆；作用域任一分量不同都读不到（默认只读 active）。"""
        params: list[Any] = list(scope.as_key())
        where = (
            "account_id = ? AND project_id = ? AND pair_id = ? "
            "AND character_ref = ? AND assistant_identity = ?"
        )
        if status is not None:
            where += " AND status = ?"
            params.append(status)
        sql = (
            f"SELECT * FROM pair_memories WHERE {where} "
            "ORDER BY updated_at DESC, memory_id DESC"
        )
        if limit is not None:
            if limit < 1:
                raise ValueError("limit 必须 >= 1")
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.connection.execute(sql, tuple(params)).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def count_memories(
        self, scope: MemoryScope, *, status: str | None = MemoryStatus.ACTIVE.value
    ) -> int:
        params: list[Any] = list(scope.as_key())
        where = (
            "account_id = ? AND project_id = ? AND pair_id = ? "
            "AND character_ref = ? AND assistant_identity = ?"
        )
        if status is not None:
            where += " AND status = ?"
            params.append(status)
        row = self.connection.execute(
            f"SELECT COUNT(*) AS n FROM pair_memories WHERE {where}", tuple(params)
        ).fetchone()
        return int(row["n"])

    @staticmethod
    def _memory_from_row(row: sqlite3.Row) -> PairMemory:
        return PairMemory(
            memory_id=row["memory_id"],
            account_id=row["account_id"],
            project_id=row["project_id"],
            pair_id=row["pair_id"],
            character_ref=row["character_ref"],
            assistant_identity=row["assistant_identity"],
            conversation_id=row["conversation_id"],
            content=row["content"],
            status=row["status"],
            provider=row["provider"],
            model=row["model"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    # ------------------------------------------------------------------ V0.3.9 回合指标

    def upsert_turn_metric(self, metric: TurnMetric) -> TurnMetric:
        """写入或更新指标行（每个会话 + turn_kind + turn_id 一行）。

        contract-v1 第 5 节：终态不可回退。已存在终态行时，只有同状态
        幂等重写允许；试图退回 accepted/running 直接 ValueError。
        """
        current = self._find_turn_metric(
            metric.conversation_id, turn_kind=metric.turn_kind, turn_id=metric.turn_id
        )
        if (
            current is not None
            and current.status in TERMINAL_METRIC_STATUSES
            and metric.status != current.status
        ):
            raise ValueError(
                f"指标终态不可回退：{current.status} -> {metric.status}"
            )
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO turn_metrics(
                    metric_id, account_id, project_id, conversation_id, pair_id,
                    character_ref, assistant_identity, turn_kind, turn_id,
                    task_id, engine_turn_id, source_message_id, provider, model,
                    engine_type, reasoning_effort, status, started_at,
                    first_event_at, completed_at, duration_ms,
                    first_event_latency_ms, input_tokens, output_tokens,
                    total_tokens, tool_rounds, compression_count, approval_count,
                    failure_type, failure_message, origin, remote_device_key,
                    remote_device_name, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(conversation_id, turn_kind, turn_id) DO UPDATE SET
                    task_id=excluded.task_id,
                    engine_turn_id=excluded.engine_turn_id,
                    source_message_id=excluded.source_message_id,
                    provider=excluded.provider,
                    model=excluded.model,
                    engine_type=excluded.engine_type,
                    reasoning_effort=excluded.reasoning_effort,
                    status=excluded.status,
                    first_event_at=excluded.first_event_at,
                    completed_at=excluded.completed_at,
                    duration_ms=excluded.duration_ms,
                    first_event_latency_ms=excluded.first_event_latency_ms,
                    input_tokens=excluded.input_tokens,
                    output_tokens=excluded.output_tokens,
                    total_tokens=excluded.total_tokens,
                    tool_rounds=excluded.tool_rounds,
                    compression_count=excluded.compression_count,
                    approval_count=excluded.approval_count,
                    failure_type=excluded.failure_type,
                    failure_message=excluded.failure_message,
                    origin=excluded.origin,
                    remote_device_key=excluded.remote_device_key,
                    remote_device_name=excluded.remote_device_name
                """,
                (
                    metric.metric_id,
                    metric.account_id,
                    metric.project_id,
                    metric.conversation_id,
                    metric.pair_id,
                    metric.character_ref,
                    metric.assistant_identity,
                    metric.turn_kind,
                    metric.turn_id,
                    metric.task_id,
                    metric.engine_turn_id,
                    metric.source_message_id,
                    metric.provider,
                    metric.model,
                    metric.engine_type,
                    metric.reasoning_effort,
                    metric.status,
                    metric.started_at.isoformat(),
                    metric.first_event_at.isoformat() if metric.first_event_at else None,
                    metric.completed_at.isoformat() if metric.completed_at else None,
                    metric.duration_ms,
                    metric.first_event_latency_ms,
                    metric.input_tokens,
                    metric.output_tokens,
                    metric.total_tokens,
                    metric.tool_rounds,
                    metric.compression_count,
                    metric.approval_count,
                    metric.failure_type,
                    metric.failure_message,
                    metric.origin,
                    metric.remote_device_key,
                    metric.remote_device_name,
                    metric.created_at.isoformat(),
                ),
            )
        return self.get_turn_metric_by_turn(
            metric.conversation_id, turn_kind=metric.turn_kind, turn_id=metric.turn_id
        )

    def update_turn_metric(self, metric_id: str, **fields: Any) -> TurnMetric:
        """按字段更新指标行；未传字段保持原值（None 表示真实缺失）。"""
        allowed = {
            "task_id",
            "engine_turn_id",
            "source_message_id",
            "provider",
            "model",
            "engine_type",
            "reasoning_effort",
            "status",
            "first_event_at",
            "completed_at",
            "duration_ms",
            "first_event_latency_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "tool_rounds",
            "compression_count",
            "approval_count",
            "failure_type",
            "failure_message",
            "origin",
            "remote_device_key",
            "remote_device_name",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"不支持的指标字段：{unknown}")
        if "status" in fields:
            allowed_status = {item.value for item in MetricStatus}
            if fields["status"] not in allowed_status:
                raise ValueError(f"未知指标状态：{fields['status']}")
        if not fields:
            return self.get_turn_metric(metric_id)
        current = self.get_turn_metric(metric_id)
        if (
            "status" in fields
            and current.status in TERMINAL_METRIC_STATUSES
            and fields["status"] != current.status
        ):
            raise ValueError(
                f"指标终态不可回退：{current.status} -> {fields['status']}"
            )
        params: list[Any] = []
        assignments: list[str] = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            params.append(value.isoformat() if isinstance(value, datetime) else value)
        params.append(metric_id)
        with self.connection:
            cursor = self.connection.execute(
                f"UPDATE turn_metrics SET {', '.join(assignments)} WHERE metric_id = ?",
                tuple(params),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown metric_id: {metric_id}")
        return self.get_turn_metric(metric_id)

    def bump_turn_metric(
        self,
        metric_id: str,
        *,
        tool_rounds: int = 0,
        compression_count: int = 0,
        approval_count: int = 0,
    ) -> TurnMetric:
        """按增量累加计数列（只改真实计数，不把 None 写成 0）。"""
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE turn_metrics SET "
                "tool_rounds = tool_rounds + ?, "
                "compression_count = compression_count + ?, "
                "approval_count = approval_count + ? "
                "WHERE metric_id = ?",
                (tool_rounds, compression_count, approval_count, metric_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown metric_id: {metric_id}")
        return self.get_turn_metric(metric_id)

    def get_turn_metric(self, metric_id: str) -> TurnMetric:
        row = self.connection.execute(
            "SELECT * FROM turn_metrics WHERE metric_id = ?", (metric_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown metric_id: {metric_id}")
        return self._metric_from_row(row)

    def get_turn_metric_by_turn(
        self, conversation_id: str, *, turn_kind: str, turn_id: str
    ) -> TurnMetric:
        metric = self._find_turn_metric(
            conversation_id, turn_kind=turn_kind, turn_id=turn_id
        )
        if metric is None:
            raise KeyError(
                f"unknown turn metric: {conversation_id}/{turn_kind}/{turn_id}"
            )
        return metric

    def _find_turn_metric(
        self, conversation_id: str, *, turn_kind: str, turn_id: str
    ) -> TurnMetric | None:
        row = self.connection.execute(
            "SELECT * FROM turn_metrics WHERE conversation_id = ? AND turn_kind = ? "
            "AND turn_id = ?",
            (conversation_id, turn_kind, turn_id),
        ).fetchone()
        return self._metric_from_row(row) if row is not None else None

    def query_turn_metrics(self, query: TurnMetricQuery) -> TurnMetricPage:
        """按过滤条件分页查询指标（started_at DESC, metric_id DESC）。

        cursor 是不透明游标，只编码上一页最后一行；limit 默认 50、上限 200。
        """
        where, params = self._metric_filters(query)
        if query.cursor:
            started_at, metric_id = self._decode_metric_cursor(query.cursor)
            where += " AND (started_at < ? OR (started_at = ? AND metric_id < ?))"
            params.extend([started_at, started_at, metric_id])
        rows = self.connection.execute(
            f"SELECT * FROM turn_metrics WHERE {where} "
            "ORDER BY started_at DESC, metric_id DESC LIMIT ?",
            (*params, query.limit + 1),
        ).fetchall()
        items = [self._metric_from_row(row) for row in rows[: query.limit]]
        next_cursor = None
        if len(rows) > query.limit and items:
            next_cursor = self._encode_metric_cursor(
                items[-1].started_at.isoformat(), items[-1].metric_id
            )
        return TurnMetricPage(items=tuple(items), next_cursor=next_cursor)

    def count_turn_metrics(self, query: TurnMetricQuery) -> int:
        where, params = self._metric_filters(query)
        row = self.connection.execute(
            f"SELECT COUNT(*) AS n FROM turn_metrics WHERE {where}", tuple(params)
        ).fetchone()
        return int(row["n"])

    @staticmethod
    def _metric_filters(query: TurnMetricQuery) -> tuple[str, list[Any]]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        for column in (
            "account_id",
            "project_id",
            "conversation_id",
            "pair_id",
            "character_ref",
            "assistant_identity",
            "turn_kind",
            "status",
            "origin",
        ):
            value = getattr(query, column)
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if query.since is not None:
            clauses.append("started_at >= ?")
            params.append(query.since.isoformat())
        if query.until is not None:
            clauses.append("started_at <= ?")
            params.append(query.until.isoformat())
        return " AND ".join(clauses), params

    @staticmethod
    def _encode_metric_cursor(started_at: str, metric_id: str) -> str:
        raw = json.dumps({"s": started_at, "m": metric_id}, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")

    @staticmethod
    def _decode_metric_cursor(cursor: str) -> tuple[str, str]:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
            payload = json.loads(raw)
            return str(payload["s"]), str(payload["m"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            raise ValueError(f"非法 metrics 游标：{cursor}") from exc

    @staticmethod
    def _metric_from_row(row: sqlite3.Row) -> TurnMetric:
        return TurnMetric(
            metric_id=row["metric_id"],
            account_id=row["account_id"],
            project_id=row["project_id"],
            conversation_id=row["conversation_id"],
            pair_id=row["pair_id"],
            character_ref=row["character_ref"],
            assistant_identity=row["assistant_identity"],
            turn_kind=row["turn_kind"],
            turn_id=row["turn_id"],
            task_id=row["task_id"],
            engine_turn_id=row["engine_turn_id"],
            source_message_id=row["source_message_id"],
            provider=row["provider"],
            model=row["model"],
            engine_type=row["engine_type"],
            reasoning_effort=row["reasoning_effort"],
            status=row["status"],
            started_at=_dt(row["started_at"]),
            first_event_at=_dt(row["first_event_at"]) if row["first_event_at"] else None,
            completed_at=_dt(row["completed_at"]) if row["completed_at"] else None,
            duration_ms=row["duration_ms"],
            first_event_latency_ms=row["first_event_latency_ms"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            total_tokens=row["total_tokens"],
            tool_rounds=int(row["tool_rounds"]),
            compression_count=int(row["compression_count"]),
            approval_count=int(row["approval_count"]),
            failure_type=row["failure_type"],
            failure_message=row["failure_message"],
            origin=row["origin"],
            remote_device_key=row["remote_device_key"],
            remote_device_name=row["remote_device_name"],
            created_at=_dt(row["created_at"]),
        )
