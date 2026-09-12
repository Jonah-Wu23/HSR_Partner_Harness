"""V0.4.0 升级与数据迁移验证（T15）测试套件。

覆盖范围：
1. SQLite 数据库结构从 v0.3.9 及更早版本平滑升级到 V0.4.0；
2. 版本 1 的已配对状态快照加载后，能正确补算 expires_at，原设备不丢失且可继续鉴权；
3. 全新安装零数据环境下初次启动无异常。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from pair_harness.core.contracts import (
    EngineSessionRef,
    Message,
    MessageKind,
    MessageSource,
    ToolRun,
)
from pair_harness.desktop_backend.application_service import (
    DesktopApplicationService,
    ServiceError,
    build_demo_service,
)
from pair_harness.desktop_backend.commands import DesktopCommand
from pair_harness.desktop_backend.pairing import (
    TOKEN_ABSOLUTE_TTL_SECONDS,
    TOKEN_IDLE_TTL_SECONDS,
    PairingService,
)
from pair_harness.storage.sqlite_store import (
    MIGRATIONS,
    SCHEMA_VERSION,
    SQLiteStore,
)


# ============================================================
# 1. SQLite 数据库结构平滑升级验证（从历史各版本至 V0.4.0）
# ============================================================


def _create_v0_db(db_path: Path) -> None:
    """创建 user_version=0 的旧库结构（模拟最早期 v0.1 / v0.2 前期版本）。"""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            root_path TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_opened_at TEXT NOT NULL
        );
        CREATE TABLE conversations (
            conversation_id TEXT PRIMARY KEY,
            project_id TEXT REFERENCES projects(project_id),
            pair_id TEXT NOT NULL,
            title TEXT NOT NULL,
            last_mode TEXT NOT NULL DEFAULT 'chat',
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            message_json TEXT NOT NULL
        );
        CREATE TABLE tool_runs (
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            tool_call_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            engine_turn_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            status TEXT NOT NULL,
            tool_json TEXT NOT NULL,
            PRIMARY KEY (conversation_id, tool_call_id)
        );
        CREATE TABLE engine_sessions (
            conversation_id TEXT PRIMARY KEY REFERENCES conversations(conversation_id) ON DELETE CASCADE,
            engine_type TEXT NOT NULL,
            session_ref TEXT NOT NULL,
            last_turn_id TEXT,
            resume_status TEXT NOT NULL DEFAULT 'ready',
            updated_at TEXT NOT NULL
        );
        PRAGMA user_version = 0;
        """
    )
    conn.commit()
    conn.close()


def _create_v039_db(db_path: Path) -> None:
    """创建 v0.3.9 生产数据库结构与样本数据（user_version=11）。"""
    store = SQLiteStore(db_path)
    # 模拟 v0.3.9 已有数据
    proj = store.create_project(
        name="V039Project",
        root_path=str(db_path.parent / "v039_project"),
        project_id="proj-v039",
        approval_mode="request_approval",
        reasoning_effort="medium",
        account_id="default-local",
    )
    conv = store.create_conversation(
        pair_id="phainon_ancient_machine",
        project_id=proj.project_id,
        title="V039 历史对话",
        conversation_id="conv-v039",
        account_id="default-local",
    )
    msg = Message(
        conversation_id=conv.conversation_id,
        pair_id=conv.pair_id,
        source=MessageSource.USER,
        kind=MessageKind.USER_TEXT,
        text="你好，这是 v0.3.9 写入的会话记录",
    )
    store.save_message(msg)
    store.close()


class TestSQLiteMigrationV040:
    def test_migrate_from_v0_to_v040(self, tmp_path: Path) -> None:
        """验证从 user_version=0 升到 V0.4.0（SCHEMA_VERSION=11）。"""
        db_path = tmp_path / "v0_legacy.db"
        _create_v0_db(db_path)

        # 插入 v0 格式数据
        conn = sqlite3.connect(db_path)
        now = "2026-01-01T00:00:00+00:00"
        conn.execute(
            "INSERT INTO projects VALUES ('p-old', 'OldProj', '/tmp/repo', 0, ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO conversations VALUES ('c-old', 'p-old', 'phainon_ancient_machine', '旧聊天', 'chat', 0, ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO engine_sessions VALUES ('c-old', 'scripted', '{\"engine_type\":\"scripted\"}', 'turn-1', 'ready', ?)",
            (now,),
        )
        conn.commit()
        conn.close()

        # 使用 SQLiteStore 打开触发迁移
        with SQLiteStore(db_path) as store:
            version = store.connection.execute("PRAGMA user_version").fetchone()[0]
            assert version == SCHEMA_VERSION

            # 验证各版本表与列已建齐
            tables = {
                r[0]
                for r in store.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            expected_tables = {
                "projects",
                "conversations",
                "messages",
                "tool_runs",
                "engine_sessions",
                "conversation_inbox",
                "accounts",
                "account_preferences",
                "provider_configs",
                "secret_refs",
                "app_state",
                "character_cards",
                "character_assets",
                "conversation_projections",
                "conversation_summaries",
                "pair_memories",
                "turn_metrics",
            }
            assert expected_tables.issubset(tables)

            # 验证旧数据保留且归入默认账号
            proj = store.get_project("p-old")
            assert proj.name == "OldProj"
            assert proj.account_id == "default-local"
            assert proj.approval_mode == "request_approval"
            assert proj.reasoning_effort == "low"

            conv = store.get_conversation("c-old")
            assert conv.title == "旧聊天"
            assert conv.account_id == "default-local"

    def test_open_v039_db_in_v040_is_smooth_and_idempotent(self, tmp_path: Path) -> None:
        """验证 v0.3.9 数据库在 V0.4.0 环境下无感打开，数据完好无损且再次打开幂等。"""
        db_path = tmp_path / "v039_existing.db"
        _create_v039_db(db_path)

        # 在 V0.4.0 打开
        with SQLiteStore(db_path) as store:
            version = store.connection.execute("PRAGMA user_version").fetchone()[0]
            assert version == SCHEMA_VERSION

            proj = store.get_project("proj-v039")
            assert proj.name == "V039Project"
            assert proj.approval_mode == "request_approval"
            assert proj.reasoning_effort == "medium"

            snapshot = store.load_conversation("conv-v039")
            assert len(snapshot["messages"]) == 1
            assert snapshot["messages"][0].text == "你好，这是 v0.3.9 写入的会话记录"

        # 再次打开验证幂等
        with SQLiteStore(db_path) as reopened:
            assert reopened.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            assert len(reopened.load_conversation("conv-v039")["messages"]) == 1


# ============================================================
# 2. 版本 1 配对快照升级到版本 2 与 expires_at 补算验证
# ============================================================


class _FakeClock:
    def __init__(self, start: float = 100000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class TestPairingStateV1ToV2Migration:
    def test_v1_snapshot_recomputes_expires_at_and_keeps_auth(self) -> None:
        """验证 v1 快照（无 expires_at）加载后补算有效期，且原设备继续鉴权。"""
        issued_at = 1_000_000.0
        last_used_at = 1_050_000.0
        token_str = "test-legacy-v1-token-secret-1234567890"

        v1_state = {
            "version": 1,
            "ttl_seconds": 300,
            "tokens": [
                {
                    "token": token_str,
                    "device_name": "Xiaomi-14-Pro",
                    "issued_at": issued_at,
                    "last_used_at": last_used_at,
                    "revoked": False,
                }
            ],
            "codes": [
                {
                    "code": "888999",
                    "issued_at": issued_at + 100,
                    "ttl_seconds": 300,
                    "claimed": False,
                }
            ],
            "revoked_hashes": [],
            "audit": [
                {"at": "2026-08-01T12:00:00+00:00", "event": "connect", "detail": "device=Xiaomi-14-Pro"}
            ],
        }

        clock = _FakeClock(start=last_used_at + 1000.0)
        svc = PairingService(clock=clock)
        svc.load_state(v1_state)

        # 1. 验证设备不丢失
        devices = svc.list_devices()
        assert len(devices) == 1
        dev = devices[0]
        assert dev["device_name"] == "Xiaomi-14-Pro"
        assert dev["revoked"] is False
        assert "expires_at" in dev

        # 2. 验证补算逻辑：min(issued_at + 30天, last_used_at + 7天)
        expected_expires_at = min(
            issued_at + TOKEN_ABSOLUTE_TTL_SECONDS,
            last_used_at + TOKEN_IDLE_TTL_SECONDS,
        )
        assert svc._tokens[token_str].expires_at == expected_expires_at

        # 3. 验证原设备可以继续鉴权业务方法
        decision = svc.authorize(token_str, "conversation.message", origin="remote")
        assert decision.allowed is True
        assert decision.device_name == "Xiaomi-14-Pro"

        # 4. 验证鉴权成功后刷新了 last_used_at 和 expires_at（空闲期刷新）
        assert svc._tokens[token_str].last_used_at == clock()
        new_expected_expires = min(
            issued_at + TOKEN_ABSOLUTE_TTL_SECONDS,
            clock() + TOKEN_IDLE_TTL_SECONDS,
        )
        assert svc._tokens[token_str].expires_at == new_expected_expires

        # 5. 验证导出的新快照自动升级为版本 2，并包含 rate_limits 和 expires_at
        v2_state = svc.export_state()
        assert v2_state["version"] == 2
        assert len(v2_state["tokens"]) == 1
        assert v2_state["tokens"][0]["expires_at"] == new_expected_expires
        assert "rate_limits" in v2_state

    def test_v1_snapshot_already_expired_by_idle_rejected(self) -> None:
        """验证 v1 快照如果闲置已超过 7 天，加载后鉴权直接按 expired_token 拒绝。"""
        issued_at = 1_000_000.0
        last_used_at = 1_000_000.0
        token_str = "old-idle-token"

        v1_state = {
            "version": 1,
            "tokens": [
                {
                    "token": token_str,
                    "device_name": "Old-iPad",
                    "issued_at": issued_at,
                    "last_used_at": last_used_at,
                    "revoked": False,
                }
            ],
        }

        # 时钟在签发 8 天后
        clock = _FakeClock(start=issued_at + 8 * 86400)
        svc = PairingService(clock=clock)
        svc.load_state(v1_state)

        decision = svc.authorize(token_str, "conversation.message")
        assert decision.allowed is False
        assert decision.reason == "expired_token"

    @pytest.mark.asyncio
    async def test_application_service_loads_v1_pairing_state_from_sqlite(self, tmp_path: Path) -> None:
        """端到端验证：ApplicationService 启动时从 SQLite 恢复 v1 配对状态并成功服务。"""
        db_path = tmp_path / "app_v1_test.db"
        store = SQLiteStore(db_path)

        token_str = "v1-app-test-token-abcdef1234567890"
        t0 = time.time()
        v1_state = {
            "version": 1,
            "ttl_seconds": 300,
            "tokens": [
                {
                    "token": token_str,
                    "device_name": "Honor-Magic-6",
                    "issued_at": t0,
                    "last_used_at": t0,
                    "revoked": False,
                }
            ],
            "codes": [],
            "revoked_hashes": [],
            "audit": [],
        }
        # 将 v1 格式写入 SQLite 的 app_state
        store.set_app_state("remote.pairing_state", json.dumps(v1_state))
        store.close()

        # 启动 ApplicationService
        service = build_demo_service(
            database=db_path,
            project_root=tmp_path / "work",
        )
        try:
            # 1. 验证设备已被恢复
            devices = service.pairing_service.list_devices()
            assert len(devices) == 1
            assert devices[0]["device_name"] == "Honor-Magic-6"

            # 2. 验证手机端可用原 token 正常鉴权业务
            decision = service.pairing_service.authorize(
                token_str, "conversation.message", origin="remote"
            )
            assert decision.allowed is True

            # 3. 验证桌面端可列出设备
            resp = await service.handle_command(
                DesktopCommand("cmd-1", "remote.list_devices", {}, origin="desktop")
            )
            assert len(resp["devices"]) == 1
            assert resp["devices"][0]["device_name"] == "Honor-Magic-6"

            # 4. 验证持久化后的配对状态已自动升级为 v2
            persisted_raw = service.store.get_app_state("remote.pairing_state")
            assert persisted_raw is not None
            persisted_json = json.loads(persisted_raw)
            assert persisted_json["version"] == 2
        finally:
            await service.shutdown()


# ============================================================
# 3. 全新安装零数据环境下初次启动无异常
# ============================================================


class TestFreshInstallZeroData:
    def test_sqlite_fresh_install_initialization(self, tmp_path: Path) -> None:
        """全新的目标数据库不存在，首次初始化应自动建表且 user_version=11。"""
        db_path = tmp_path / "fresh_new" / "nested" / "pair_harness.db"
        assert not db_path.exists()

        with SQLiteStore(db_path) as store:
            assert db_path.exists()
            version = store.connection.execute("PRAGMA user_version").fetchone()[0]
            assert version == SCHEMA_VERSION

            # 验证默认账号与偏好已创建
            acc = store.connection.execute(
                "SELECT * FROM accounts WHERE account_id = 'default-local'"
            ).fetchone()
            assert acc is not None
            assert acc["username"] == "default"

            pref = store.connection.execute(
                "SELECT * FROM account_preferences WHERE account_id = 'default-local'"
            ).fetchone()
            assert pref is not None

            # 项目与聊天列表均为空
            assert store.list_projects() == []
            assert store.list_conversations(None) == []

    @pytest.mark.asyncio
    async def test_application_service_fresh_install_startup_and_operations(self, tmp_path: Path) -> None:
        """零数据环境下启动完整 ApplicationService，各项初始状态正常且可立即操作。"""
        fresh_db = tmp_path / "fresh_app" / "harness.db"
        fresh_root = tmp_path / "fresh_app" / "project_root"

        service = build_demo_service(
            database=fresh_db,
            project_root=fresh_root,
        )
        try:
            # 1. 验证配对服务初始状态干净
            assert service.pairing_service.list_devices() == []
            assert service.pairing_service.audit_entries() == []

            # 2. 验证隧道初始状态为 'off'
            status = service.tunnel_manager.status()
            assert status["state"] == "off"
            assert status["public_url"] is None
            assert status["hostname"] is None
            assert status["error"] is None

            # 3. 验证首次签发配对码
            issue_resp = await service.handle_command(
                DesktopCommand("cmd-issue", "remote.issue_code", {}, origin="desktop")
            )
            assert "code" in issue_resp
            assert len(issue_resp["code"]) == 6
            assert issue_resp["ttl_seconds"] == 300

            # 4. 验证零数据下创建项目与聊天
            proj = service.store.create_project(
                name="首个工程",
                root_path=str(fresh_root),
                project_id="p-first",
            )
            assert proj.name == "首个工程"

            conv = service.store.create_conversation(
                pair_id="phainon_ancient_machine",
                project_id=proj.project_id,
                title="首个聊天",
                conversation_id="c-first",
            )
            assert conv.title == "首个聊天"

            # 5. 验证配对与持久化正常运作
            token = service.pairing_service.claim(
                issue_resp["code"], device_name="首个设备"
            )
            assert isinstance(token, str)
            assert len(service.pairing_service.list_devices()) == 1

            # 6. 验证持久化写出
            service._persist_pairing_state()
            state_raw = service.store.get_app_state("remote.pairing_state")
            assert state_raw is not None
            state_data = json.loads(state_raw)
            assert state_data["version"] == 2
            assert len(state_data["tokens"]) == 1
            assert state_data["tokens"][0]["device_name"] == "首个设备"
        finally:
            await service.shutdown()
