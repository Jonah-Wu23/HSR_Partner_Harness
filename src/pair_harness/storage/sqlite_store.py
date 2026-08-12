from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from pair_harness.core.contracts import EngineSessionRef, Message, ToolRun, enum_value
from pair_harness.core.ports import StateStore
from pair_harness.core.repository import Conversation, Project


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


# O4.3：数据库结构版本。新库由 schema.sql 一次建全，直接标记为该版本；
# 旧库（user_version=0）按 MIGRATIONS 逐级升级。每次结构变更 +1，
# 并在 MIGRATIONS 里补对应迁移步骤。
SCHEMA_VERSION = 6

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
    ),
    # 版本 6：应用级单值状态（当前登录账号等）
    (
        "CREATE TABLE IF NOT EXISTS app_state ("
        "key TEXT PRIMARY KEY,"
        "value TEXT NOT NULL)",
    ),
)


class SQLiteStore(StateStore):
    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        # O4.3：区分新库与旧库——新库 schema.sql 已建完整表结构，
        # 直接标记当前版本；旧库（有内容的文件）按 user_version 迁移
        fresh = not database.exists() or database.stat().st_size == 0
        self.database = database
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
            for statement in MIGRATIONS[target - 1]:
                self._apply_migration(statement)
            self.connection.execute(f"PRAGMA user_version = {target}")
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

    def update_project_approval_mode(self, project_id: str, approval_mode: str) -> None:
        """保存输入区下拉框选择的审批模式（计划 A6）。"""
        self.connection.execute(
            "UPDATE projects SET approval_mode = ? WHERE project_id = ?",
            (approval_mode, project_id),
        )
        self.connection.commit()

    def update_project_reasoning_effort(
        self, project_id: str, reasoning_effort: str
    ) -> None:
        self.connection.execute(
            "UPDATE projects SET reasoning_effort = ? WHERE project_id = ?",
            (reasoning_effort, project_id),
        )
        self.connection.commit()

    def update_project_name(self, project_id: str, name: str) -> None:
        self.connection.execute(
            "UPDATE projects SET name = ?, last_opened_at = ? WHERE project_id = ?",
            (name, _now(), project_id),
        )
        self.connection.commit()

    def update_project_root_path(self, project_id: str, root_path: str) -> None:
        self.connection.execute(
            "UPDATE projects SET root_path = ?, last_opened_at = ? WHERE project_id = ?",
            (root_path, _now(), project_id),
        )
        self.connection.commit()

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

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        where = "" if include_archived else "WHERE archived = 0"
        rows = self.connection.execute(
            f"SELECT project_id FROM projects {where} ORDER BY last_opened_at DESC"
        ).fetchall()
        return [self.get_project(row["project_id"]) for row in rows]

    def find_project_by_root_path(self, root_path: str) -> Project | None:
        """按规范化目录查找项目，避免同一目录重复创建项目记录。"""
        wanted = str(Path(root_path).resolve())
        for project in self.list_projects():
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
    ) -> Conversation:
        conversation_id = conversation_id or str(uuid4())
        now = _now()
        self.connection.execute(
            """
            INSERT INTO conversations(
                conversation_id, project_id, pair_id, title, last_mode, archived, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                updated_at=excluded.updated_at
            """,
            (conversation_id, project_id, pair_id, title, last_mode, now, now),
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
            project_id=row["project_id"],
            pair_id=row["pair_id"],
            title=row["title"],
            last_mode=row["last_mode"],
            archived=bool(row["archived"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def list_conversations(
        self, project_id: str | None, *, include_archived: bool = False
    ) -> list[Conversation]:
        archived_clause = "" if include_archived else "AND archived = 0"
        if project_id is None:
            rows = self.connection.execute(
                f"""SELECT conversation_id FROM conversations
                WHERE project_id IS NULL {archived_clause} ORDER BY updated_at DESC"""
            ).fetchall()
        else:
            rows = self.connection.execute(
                f"""SELECT conversation_id FROM conversations
                WHERE project_id = ? {archived_clause} ORDER BY updated_at DESC""",
                (project_id,),
            ).fetchall()
        return [self.get_conversation(row["conversation_id"]) for row in rows]

    def save_message(self, message: Message) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO messages(
                message_id, conversation_id, source, kind, created_at, message_json
            ) VALUES (?, ?, ?, ?, ?, ?)
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
        self._touch_conversation(message.conversation_id)
        self.connection.commit()

    def save_tool_run(self, tool_run: ToolRun) -> None:
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
        self._touch_conversation(tool_run.conversation_id)
        self.connection.commit()

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

    def load_conversation(self, conversation_id: str) -> dict:
        conversation = self.get_conversation(conversation_id)
        message_rows = self.connection.execute(
            """SELECT message_json FROM messages
            WHERE conversation_id = ? ORDER BY created_at, rowid""",
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

    def get_config(self, account_id: str, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM provider_configs WHERE account_id = ? AND key = ?",
            (account_id, key),
        ).fetchone()
        return row["value"] if row is not None else None

    def set_config(self, account_id: str, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO provider_configs(account_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(account_id, key) DO UPDATE SET value = excluded.value",
            (account_id, key, value),
        )
        self.connection.commit()

    def set_configs(self, account_id: str, updates: dict[str, str]) -> None:
        for key, value in updates.items():
            self.set_config(account_id, key, value)

    def get_secret(self, account_id: str, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT secret FROM secret_refs WHERE account_id = ? AND key = ?",
            (account_id, key),
        ).fetchone()
        return row["secret"] if row is not None else None

    def set_secret(self, account_id: str, key: str, secret: str) -> None:
        self.connection.execute(
            "INSERT INTO secret_refs(account_id, key, secret) VALUES (?, ?, ?) "
            "ON CONFLICT(account_id, key) DO UPDATE SET secret = excluded.secret",
            (account_id, key, secret),
        )
        self.connection.commit()

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
            "ORDER BY last_opened_at DESC",
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

    def _touch_conversation(self, conversation_id: str) -> None:
        self.connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
            (_now(), conversation_id),
        )
