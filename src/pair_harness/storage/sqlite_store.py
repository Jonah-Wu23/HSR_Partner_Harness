from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pair_harness.core.contracts import EngineSessionRef, Message, ToolRun, enum_value
from pair_harness.core.ports import StateStore
from pair_harness.core.repository import Conversation, ConversationSnapshot, Project
from pair_harness.core.summary import ConversationSummary as CoreConversationSummary

from .records import (
    ConversationSummary,
    SummaryStatus,
    MemoryScope,
    MemoryStatus,
    PairMemory,
    TERMINAL_METRIC_STATUSES,
    TurnMetric,
    TurnMetricPage,
    TurnMetricQuery,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class DatabaseVersionError(RuntimeError):
    """数据库结构版本高于当前代码支持的版本。"""


# 数据库结构版本。新库由 schema.sql 一次建全并直接标记为该版本；已有库只按
# MIGRATIONS 从 user_version 逐级升级，每一级是从上一版本到该版本的完整步骤
# （建表、加列、回填），不依赖 schema.sql。每次结构变更 +1 并补对应迁移。
SCHEMA_VERSION = 14

# 索引 i 对应“从版本 i 升到 i+1”的迁移步骤（每级一条或多条 SQL）。
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    # 版本 1：projects 表补审批模式列
    (
        "ALTER TABLE projects ADD COLUMN approval_mode "
        "TEXT NOT NULL DEFAULT 'request_approval'",
    ),
    # 版本 2：移除 engine_sessions 的 last_turn_id 与 resume_status 列
    (
        "ALTER TABLE engine_sessions DROP COLUMN last_turn_id",
        "ALTER TABLE engine_sessions DROP COLUMN resume_status",
    ),
    # 版本 3：保存项目的角色对话思考档位
    (
        "ALTER TABLE projects ADD COLUMN reasoning_effort "
        "TEXT NOT NULL DEFAULT 'low'",
    ),
    # 版本 4：持久化会话队列（conversation_inbox）
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
    # 版本 5：本地账号与账号级配置。建表，创建默认账号，现有项目与队列项归入默认账号。
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
    # 版本 7：聊天归属账号，按项目归属回填。
    (
        "ALTER TABLE conversations ADD COLUMN account_id TEXT NOT NULL DEFAULT ''",
        "UPDATE conversations SET account_id = COALESCE("
        "(SELECT account_id FROM projects WHERE projects.project_id = conversations.project_id), "
        "'default-local') WHERE account_id = ''",
    ),
    # 版本 8：消息的 pair_id 以所属聊天的 pair_id 为准，修正与聊天不一致的记录。
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
    # 版本 9：角色卡持久化（character_cards / character_assets）。
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
    # 版本 10：聊天绑定的自定义角色卡（character_card_id，NULL 为内置角色）。
    (
        "ALTER TABLE conversations ADD COLUMN character_card_id TEXT NULL",
    ),
    # 版本 11：持久化投影、聊天摘要、配对长期记忆与回合指标。
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
    # 版本 12：聊天标题来源与队列项的提交来源、失败原因。已有聊天标题仍是
    # 「新聊天」的记 default，其余视为用户命名（user）。
    (
        "ALTER TABLE conversations ADD COLUMN title_source "
        "TEXT NOT NULL DEFAULT 'default'",
        "UPDATE conversations SET title_source = 'user' WHERE title <> '新聊天'",
        "ALTER TABLE conversation_inbox ADD COLUMN origin "
        "TEXT NOT NULL DEFAULT 'desktop'",
        "ALTER TABLE conversation_inbox ADD COLUMN remote_device_key TEXT",
        "ALTER TABLE conversation_inbox ADD COLUMN remote_device_name TEXT",
        "ALTER TABLE conversation_inbox ADD COLUMN error TEXT",
    ),
    # 版本 13：统一时间线序号。同一聊天的全部消息与工具记录共用一个序号，
    # 从 1 起重排回填：消息按 (created_at, message_id) 排序；已有序号的工具
    # 记录插在第一条序号更大的助手消息之前，没有这样的消息时接在最后一条
    # 序号更小的助手消息之后，因此已有序号的助手消息与工具记录保持彼此的
    # 相对顺序；没有可比序号的工具记录接在同一任务的最后一条消息之后，
    # 再没有则排到聊天末尾。
    (
        "CREATE TEMP TABLE _v13_messages AS SELECT conversation_id, message_id, "
        "ROW_NUMBER() OVER ("
        "PARTITION BY conversation_id ORDER BY created_at, message_id) AS rank, "
        "json_extract(message_json, '$.timeline_order') AS old_order, "
        "json_extract(message_json, '$.source') = 'assistant' AS is_assistant, "
        "json_extract(message_json, '$.task_id') AS task_id "
        "FROM messages",
        "CREATE TEMP TABLE _v13_tools AS SELECT t.conversation_id, t.tool_call_id, "
        "t.sequence, json_extract(t.tool_json, '$.timeline_order') AS old_order, "
        "(SELECT MIN(m.rank) FROM _v13_messages m "
        "WHERE m.conversation_id = t.conversation_id AND m.is_assistant "
        "AND m.old_order > json_extract(t.tool_json, '$.timeline_order')) AS before_rank, "
        "(SELECT MAX(m.rank) FROM _v13_messages m "
        "WHERE m.conversation_id = t.conversation_id AND m.is_assistant "
        "AND m.old_order < json_extract(t.tool_json, '$.timeline_order')) AS after_rank, "
        "(SELECT MAX(m.rank) FROM _v13_messages m "
        "WHERE m.conversation_id = t.conversation_id AND m.task_id = t.task_id) AS task_rank, "
        "(SELECT COALESCE(MAX(m.rank), 0) FROM _v13_messages m "
        "WHERE m.conversation_id = t.conversation_id) AS last_rank "
        "FROM tool_runs t",
        # slot 0 排在锚点消息之前，1 是消息本身，2 排在锚点消息之后。
        "CREATE TEMP TABLE _v13_orders AS SELECT conversation_id, kind, item_key, "
        "ROW_NUMBER() OVER (PARTITION BY conversation_id "
        "ORDER BY pos, slot, tie_order, tie_sequence, item_key) AS new_order "
        "FROM ("
        "SELECT conversation_id, 'message' AS kind, message_id AS item_key, "
        "rank AS pos, 1 AS slot, 0 AS tie_order, 0 AS tie_sequence FROM _v13_messages "
        "UNION ALL "
        "SELECT conversation_id, 'tool', tool_call_id, "
        "COALESCE(before_rank, after_rank, task_rank, last_rank), "
        "CASE WHEN before_rank IS NOT NULL THEN 0 ELSE 2 END, "
        "COALESCE(old_order, 0), sequence FROM _v13_tools)",
        "UPDATE messages SET message_json = json_set(message_json, '$.timeline_order', "
        "(SELECT o.new_order FROM _v13_orders o WHERE o.kind = 'message' "
        "AND o.conversation_id = messages.conversation_id "
        "AND o.item_key = messages.message_id))",
        "UPDATE tool_runs SET tool_json = json_set(tool_json, '$.timeline_order', "
        "(SELECT o.new_order FROM _v13_orders o WHERE o.kind = 'tool' "
        "AND o.conversation_id = tool_runs.conversation_id "
        "AND o.item_key = tool_runs.tool_call_id))",
        "DROP TABLE _v13_messages",
        "DROP TABLE _v13_tools",
        "DROP TABLE _v13_orders",
    ),
    # 版本 14：持久化搭档绑定（partner_bindings）与聊天绑定的 binding_id。
    # 三个内置搭档各建一行 character_card_id 为 NULL 的绑定；既有可用角色卡
    # （saved/imported 且不在 app_state 归档集合）补建默认搭档
    # 「神秘的古代机械」的绑定；既有聊天按 (character_card_id, pair_id)
    # 匹配回填 binding_id，匹配不到（卡已删除、草稿或归档）保持 NULL。
    (
        "CREATE TABLE IF NOT EXISTS partner_bindings ("
        "binding_id TEXT PRIMARY KEY,"
        "character_card_id TEXT NULL,"
        "base_pair_id TEXT NOT NULL,"
        "enabled INTEGER NOT NULL DEFAULT 1,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_partner_bindings_scope "
        "ON partner_bindings(character_card_id, base_pair_id)",
        "ALTER TABLE conversations ADD COLUMN binding_id TEXT NULL",
        "INSERT OR IGNORE INTO partner_bindings("
        "binding_id, character_card_id, base_pair_id, enabled, created_at, updated_at) "
        "SELECT 'builtin:' || pair_id, NULL, pair_id, 1, "
        "strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'), "
        "strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now') "
        "FROM (SELECT 'firefly_sam' AS pair_id "
        "UNION ALL SELECT 'march7_fourth_mirror' "
        "UNION ALL SELECT 'phainon_ancient_machine')",
        "INSERT OR IGNORE INTO partner_bindings("
        "binding_id, character_card_id, base_pair_id, enabled, created_at, updated_at) "
        "SELECT 'card:' || c.card_id, c.card_id, 'phainon_ancient_machine', 1, "
        "strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'), "
        "strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now') "
        "FROM character_cards AS c "
        "WHERE c.state IN ('saved', 'imported') "
        "AND NOT EXISTS ("
        "SELECT 1 FROM app_state AS s, json_each(s.value) AS j "
        "WHERE s.key = 'character_cards.archived' AND j.value = c.card_id)",
        "UPDATE conversations SET binding_id = ("
        "SELECT b.binding_id FROM partner_bindings AS b "
        "WHERE b.base_pair_id = conversations.pair_id "
        "AND b.character_card_id IS conversations.character_card_id) "
        "WHERE EXISTS ("
        "SELECT 1 FROM partner_bindings AS b "
        "WHERE b.base_pair_id = conversations.pair_id "
        "AND b.character_card_id IS conversations.character_card_id)",
    ),
)


class SQLiteStore(StateStore):
    def __init__(self, database: Path) -> None:
        """打开数据库：新库按 schema.sql 建表，已有库按 user_version 逐级迁移。"""
        database.parent.mkdir(parents=True, exist_ok=True)
        fresh = not database.exists() or database.stat().st_size == 0
        self.database = database
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if fresh:
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            self.connection.executescript(schema)
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.connection.execute(
                "INSERT INTO accounts("
                "account_id, username, display_name, password_hash, password_salt,"
                "created_at) VALUES ("
                "'default-local', 'default', '默认账号', '', '', datetime('now'))"
            )
            self.connection.commit()
            return
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            # 更新版本的应用写过这个库，当前代码不认识新结构，不能打开。
            self.connection.close()
            raise DatabaseVersionError(
                f"数据库 {database} 的结构版本 {version} 高于当前应用支持的 "
                f"{SCHEMA_VERSION}，请使用更新版本的应用打开"
            )
        self._migrate(version)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _migrate(self, version: int) -> None:
        """从 version 逐级执行 MIGRATIONS，每完成一级立即写入对应 user_version。"""
        for target in range(version + 1, SCHEMA_VERSION + 1):
            # sqlite3 默认隔离级别下 DDL 不进隐式事务，必须显式 BEGIN，
            # 失败时整级回滚且 user_version 不推进，重开即可重试。
            self.connection.execute("BEGIN")
            try:
                for statement in MIGRATIONS[target - 1]:
                    self.connection.execute(statement)
                self.connection.execute(f"PRAGMA user_version = {target}")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            self.connection.commit()

    def _update_existing(self, sql: str, params: tuple[Any, ...], missing: str) -> None:
        """执行针对单个已有对象的 UPDATE；没有命中任何行时回滚并抛 KeyError。"""
        cursor = self.connection.execute(sql, params)
        if cursor.rowcount == 0:
            self.connection.rollback()
            raise KeyError(missing)

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
        self._update_existing(sql, params, f"unknown project: {project_id}")
        self.connection.commit()

    def update_project_approval_mode(self, project_id: str, approval_mode: str) -> None:
        """保存输入区下拉框选择的审批模式。"""
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

        检查范围包含已归档项目，再次选择已归档目录时复用原记录。
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
        binding_id: str | None = None,
        title_source: str = "default",
    ) -> Conversation:
        conversation_id = conversation_id or str(uuid4())
        now = _now()
        self.connection.execute(
            """
            INSERT INTO conversations(
                conversation_id, account_id, project_id, pair_id, title, title_source,
                last_mode, archived, created_at, updated_at, character_card_id, binding_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                updated_at=excluded.updated_at
            """,
            (
                conversation_id,
                account_id,
                project_id,
                pair_id,
                title,
                title_source,
                last_mode,
                now,
                now,
                character_card_id,
                binding_id,
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
            account_id=row["account_id"],
            project_id=row["project_id"],
            pair_id=row["pair_id"],
            title=row["title"],
            title_source=row["title_source"],
            last_mode=row["last_mode"],
            archived=bool(row["archived"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            character_card_id=row["character_card_id"],
            binding_id=row["binding_id"],
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
        binding_id: str | None = None,
        character_card_id: str | None = None,
        pair_id: str | None = None,
        account_id: str | None = None,
    ) -> Conversation | None:
        """按项目与搭档绑定找最新的未归档会话。

        conversation.create 的 ``reuse_active`` 复用键是 ``binding_id``：同一
        搭档绑定只复用一条会话。``binding_id`` 为空时退回按 ``character_card_id``
        与 ``pair_id`` 匹配，兼容尚未提交绑定 id 的调用点。只匹配 archived=0 的
        会话，无匹配返回 None。
        """
        where = ["project_id = ?", "archived = 0"]
        params: list[Any] = [project_id]
        if binding_id is not None:
            where.append("binding_id = ?")
            params.append(binding_id)
        else:
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
        with self.connection:
            self._write_message_row(message)
            self._touch_conversation(message.conversation_id, _now())

    def save_tool_run(self, tool_run: ToolRun) -> None:
        with self.connection:
            self._write_tool_run_row(tool_run)
            self._touch_conversation(tool_run.conversation_id, _now())

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

    def clear_project_engine_sessions(self, project_id: str) -> list[str]:
        """删除指定项目下全部聊天的引擎会话引用，返回这些聊天的 id。

        项目目录变化后旧 session 绑定的是旧目录，下一次任务必须新开。
        """
        conversation_ids = [
            row["conversation_id"]
            for row in self.connection.execute(
                "SELECT conversation_id FROM conversations WHERE project_id = ?",
                (project_id,),
            )
        ]
        self.connection.execute(
            "DELETE FROM engine_sessions WHERE conversation_id IN ("
            "SELECT conversation_id FROM conversations WHERE project_id = ?"
            ")",
            (project_id,),
        )
        self.connection.commit()
        return conversation_ids

    def load_conversation(self, conversation_id: str) -> ConversationSnapshot:
        conversation = self.get_conversation(conversation_id)
        message_rows = self.connection.execute(
            # 权威顺序是 (created_at, message_id)，不使用 rowid。
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
        # 覆盖终点最新的 completed 摘要；存储层 content 是 JSON 文本。
        summary_record = self.latest_completed_summary(conversation_id)
        return ConversationSnapshot(
            conversation=conversation,
            messages=tuple(
                Message.model_validate_json(row["message_json"]) for row in message_rows
            ),
            tool_runs=tuple(
                ToolRun.model_validate_json(row["tool_json"]) for row in tool_rows
            ),
            engine_session=(
                EngineSessionRef.model_validate_json(session_row["session_ref"])
                if session_row is not None
                else None
            ),
            summary=(
                CoreConversationSummary.model_validate(
                    {
                        **summary_record.model_dump(),
                        "content": json.loads(summary_record.content),
                    }
                )
                if summary_record is not None
                else None
            ),
        )

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        """用户改名：标题来源记为 user，之后自动标题不再写入。"""
        self._update_existing(
            "UPDATE conversations SET title = ?, title_source = 'user', updated_at = ? "
            "WHERE conversation_id = ?",
            (title, _now(), conversation_id),
            f"unknown conversation: {conversation_id}",
        )
        self.connection.commit()

    def set_auto_title(self, conversation_id: str, title: str) -> bool:
        """写入助手生成的标题；只在标题来源仍为 default 时生效，返回是否写入。"""
        cursor = self.connection.execute(
            "UPDATE conversations SET title = ?, title_source = 'auto', updated_at = ? "
            "WHERE conversation_id = ? AND title_source = 'default'",
            (title, _now(), conversation_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def update_conversation_mode(self, conversation_id: str, mode: str) -> None:
        """保存桌面端当前聊天模式，不改变历史消息语义。"""
        self._update_existing(
            "UPDATE conversations SET last_mode = ?, updated_at = ? WHERE conversation_id = ?",
            (mode, _now(), conversation_id),
            f"unknown conversation: {conversation_id}",
        )
        self.connection.commit()

    def archive_conversation(self, conversation_id: str) -> None:
        """归档单个聊天；项目和其他聊天保持不变。"""
        self._update_existing(
            "UPDATE conversations SET archived = 1, updated_at = ? WHERE conversation_id = ?",
            (_now(), conversation_id),
            f"unknown conversation: {conversation_id}",
        )
        self.connection.commit()

    def archive_project(self, project_id: str) -> None:
        self._update_existing(
            "UPDATE projects SET archived = 1 WHERE project_id = ?",
            (project_id,),
            f"unknown project: {project_id}",
        )
        self.connection.execute(
            "UPDATE conversations SET archived = 1 WHERE project_id = ?", (project_id,)
        )
        self.connection.commit()

    def unarchive_project(self, project_id: str) -> Project:
        """恢复已归档项目及其聊天，供再次选择同一目录时复用旧记录。"""
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

    # ------------------------------------------------------------------ 会话队列

    def enqueue_queue_item(
        self,
        *,
        conversation_id: str,
        target: str,
        text: str,
        intent: str = "followup",
        account_id: str = "",
        origin: str = "desktop",
        remote_device_key: str | None = None,
        remote_device_name: str | None = None,
    ) -> dict:
        """入队（先持久化，再向前端确认）。steer 置队首并重排其余 queued 项。

        ``origin`` 与 ``remote_device_*`` 是提交来源，派发出的回合沿用。
        """
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
            "position, status, created_at, source_message_id,"
            "origin, remote_device_key, remote_device_name"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, NULL, ?, ?, ?)",
            (
                queue_item_id,
                account_id,
                conversation_id,
                target,
                text,
                intent,
                position,
                _now(),
                origin,
                remote_device_key,
                remote_device_name,
            ),
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
        self._update_existing(
            "UPDATE conversation_inbox SET text = ? WHERE queue_item_id = ? AND status = 'queued'",
            (text, queue_item_id),
            f"queue_item 不存在或已派发: {queue_item_id}",
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

    def mark_queue_item_failed(self, queue_item_id: str, error: str) -> dict:
        """派发失败：状态置 failed 并保留原因，不再自动派发。"""
        self.connection.execute(
            "UPDATE conversation_inbox SET status = 'failed', error = ? "
            "WHERE queue_item_id = ?",
            (error, queue_item_id),
        )
        self.connection.commit()
        return self.get_queue_item(queue_item_id)

    def requeue_processing_queue_items(self) -> None:
        """启动恢复：全部 processing 队列项退回 queued（派发进程已不存在）。"""
        self.connection.execute(
            "UPDATE conversation_inbox SET status = 'queued' WHERE status = 'processing'"
        )
        self.connection.commit()

    def conversations_with_processing_delegations(self) -> list[str]:
        """启动恢复：仍有 processing 委派卡的聊天 id（全部账号）。"""
        rows = self.connection.execute(
            "SELECT DISTINCT conversation_id FROM messages "
            "WHERE json_extract(message_json, '$.origin') = 'character_delegation' "
            "AND json_extract(message_json, '$.status') = 'processing'"
        ).fetchall()
        return [row["conversation_id"] for row in rows]

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
            "origin": row["origin"],
            "remote_device_key": row["remote_device_key"],
            "remote_device_name": row["remote_device_name"],
            "error": row["error"],
        }

    # ------------------------------------------------------------------ 本地账号

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
        self._update_existing(
            "UPDATE accounts SET onboarding_complete = ? WHERE account_id = ?",
            (1 if completed else 0, account_id),
            f"unknown account: {account_id}",
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

    # ------------------------------------------------------------------ 账号级配置

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

    def get_secret(self, account_id: str, key: str) -> str | None:
        return self._get_account_config("secret_refs", "secret", account_id, key)

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
            account_id=row["account_id"],
            name=row["name"],
            root_path=row["root_path"],
            approval_mode=row["approval_mode"],
            reasoning_effort=row["reasoning_effort"],
            archived=bool(row["archived"]),
            created_at=_dt(row["created_at"]),
            last_opened_at=_dt(row["last_opened_at"]),
        )

    def _touch_conversation(self, conversation_id: str, now: str) -> None:
        """更新聊天最近业务变化时间，聊天列表按它排序。"""
        self.connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
            (now, conversation_id),
        )

    def _write_message_row(self, message: Message) -> None:
        """写单条消息。ON CONFLICT DO UPDATE 保留原行，INSERT OR REPLACE 会换掉 rowid。"""
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

    # ------------------------------------------------------------------ 聊天摘要

    def upsert_summary(self, summary: ConversationSummary) -> ConversationSummary:
        """写入或更新一条摘要（按会话 + 覆盖区间幂等）。

        区间已存在时保留原 summary_id 与 created_at，只更新内容与状态；
        返回值以数据库当前行为准。
        """
        with self.connection:
            rows = self.connection.execute(
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
                RETURNING *
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
            ).fetchall()
        return self._summary_from_row(rows[0])

    def get_summary(self, summary_id: str) -> ConversationSummary:
        row = self.connection.execute(
            "SELECT * FROM conversation_summaries WHERE summary_id = ?", (summary_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown summary_id: {summary_id}")
        return self._summary_from_row(row)

    def list_summaries(
        self, conversation_id: str, *, status: str | None = None
    ) -> list[ConversationSummary]:
        """列出该聊天的摘要，按覆盖区间起点消息的时间排序。"""
        status_clause = "" if status is None else "AND s.status = ? "
        params: tuple[str, ...] = (
            (conversation_id,) if status is None else (conversation_id, status)
        )
        rows = self.connection.execute(
            "SELECT s.* FROM conversation_summaries AS s "
            "LEFT JOIN messages AS m ON m.message_id = s.covers_from_message_id "
            f"WHERE s.conversation_id = ? {status_clause}"
            "ORDER BY m.created_at, m.message_id, s.summary_id",
            params,
        ).fetchall()
        return [self._summary_from_row(row) for row in rows]

    def latest_completed_summary(
        self, conversation_id: str
    ) -> ConversationSummary | None:
        """覆盖终点最新的 completed 摘要（按覆盖终点消息的时间取）。"""
        row = self.connection.execute(
            "SELECT s.* FROM conversation_summaries AS s "
            "JOIN messages AS m ON m.message_id = s.covers_to_message_id "
            "WHERE s.conversation_id = ? AND s.status = ? "
            "ORDER BY m.created_at DESC, m.message_id DESC, s.summary_id DESC LIMIT 1",
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
            content=row["content"],
            provider=row["provider"],
            model=row["model"],
            status=row["status"],
            error_code=row["error_code"],
            error=row["error"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    # ------------------------------------------------------------------ 配对长期记忆

    def upsert_memory(self, memory: PairMemory) -> PairMemory:
        """写入或更新一条长期记忆（同作用域同内容幂等）。

        作用域五个分量必须全部非空，否则 ValueError——项目为空的日常
        聊天不读写长期记忆。返回值以数据库当前行为准（已存在时保留
        原 memory_id 与 created_at）。
        """
        memory.scope()
        with self.connection:
            rows = self.connection.execute(
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
                RETURNING *
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
            ).fetchall()
        return self._memory_from_row(rows[0])

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

    # ------------------------------------------------------------------ 回合指标

    def upsert_turn_metric(self, metric: TurnMetric) -> TurnMetric:
        """写入或更新指标行（每个会话 + turn_kind + turn_id 一行）。

        终态不可回退：已存在终态行时只允许同状态幂等重写，退回
        accepted/running 直接 ValueError。
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
            rows = self.connection.execute(
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
                RETURNING *
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
            ).fetchall()
        return self._metric_from_row(rows[0])

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
