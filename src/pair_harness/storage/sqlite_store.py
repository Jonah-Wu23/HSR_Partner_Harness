from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from pair_harness.core.contracts import EngineSessionRef, Message, ToolRun
from pair_harness.core.ports import StateStore
from pair_harness.core.repository import Conversation, Project


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


class SQLiteStore(StateStore):
    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.connection.executescript(schema)
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _migrate(self) -> None:
        """旧库轻量迁移：为 projects 表补 approval_mode 列。

        schema.sql 使用 CREATE TABLE IF NOT EXISTS，已存在的数据库文件
        不会自动获得新列，这里显式补列保证旧数据目录可继续打开。
        """
        columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(projects)"
            ).fetchall()
        }
        if "approval_mode" not in columns:
            self.connection.execute(
                "ALTER TABLE projects ADD COLUMN approval_mode "
                "TEXT NOT NULL DEFAULT 'request_approval'"
            )
            self.connection.commit()

    def create_project(
        self,
        *,
        name: str,
        root_path: str,
        project_id: str | None = None,
        approval_mode: str = "request_approval",
    ) -> Project:
        project_id = project_id or str(uuid4())
        now = _now()
        self.connection.execute(
            """
            INSERT INTO projects(
                project_id, name, root_path, approval_mode, archived, created_at, last_opened_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                name=excluded.name,
                root_path=excluded.root_path,
                approval_mode=excluded.approval_mode,
                last_opened_at=excluded.last_opened_at
            """,
            (project_id, name, root_path, approval_mode, now, now),
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

    def get_project(self, project_id: str) -> Project:
        row = self.connection.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return Project(
            project_id=row["project_id"],
            name=row["name"],
            root_path=row["root_path"],
            approval_mode=row["approval_mode"],
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
                project_id=excluded.project_id,
                pair_id=excluded.pair_id,
                title=excluded.title,
                last_mode=excluded.last_mode,
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
                str(message.source),
                str(message.kind),
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
                resume_status='ready',
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
            "messages": tuple(Message.model_validate_json(row["message_json"]) for row in message_rows),
            "tool_runs": tuple(self._parse_tool_run(row["tool_json"]) for row in tool_rows),
            "engine_session": (
                EngineSessionRef.model_validate_json(session_row["session_ref"])
                if session_row is not None
                else None
            ),
        }

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

    def archive_project(self, project_id: str) -> None:
        self.connection.execute("UPDATE projects SET archived = 1 WHERE project_id = ?", (project_id,))
        self.connection.execute(
            "UPDATE conversations SET archived = 1 WHERE project_id = ?", (project_id,)
        )
        self.connection.commit()

    def _touch_conversation(self, conversation_id: str) -> None:
        self.connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
            (_now(), conversation_id),
        )

