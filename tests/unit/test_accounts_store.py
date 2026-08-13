"""V0.2 M3：本地账号与账号级配置的存储层（方案 §M3）。"""

from pathlib import Path

import pytest

from pair_harness.storage.sqlite_store import SQLiteStore


def make_store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "data" / "pair_harness.db")


@pytest.fixture
def store(tmp_path: Path):
    store = make_store(tmp_path)
    yield store
    store.close()


def test_default_account_exists_after_migration(store: SQLiteStore) -> None:
    """旧库升级：自动创建默认账号，未设置密码（空密码可登录）。"""
    accounts = store.list_accounts()
    assert any(a["account_id"] == "default-local" for a in accounts)
    default = store.get_account("default-local")
    assert store.verify_password("default-local", "") is True
    assert store.verify_password("default-local", "任意密码") is False
    assert default["onboarding_complete"] is False


def test_register_login_and_password_verification(store: SQLiteStore) -> None:
    account = store.create_account(
        username="alice", display_name="爱丽丝", password="s3cret"
    )
    assert account["username"] == "alice"
    assert "password_hash" not in account  # 快照不含派生结果
    assert store.verify_password(account["account_id"], "s3cret") is True
    assert store.verify_password(account["account_id"], "wrong") is False
    # 重复用户名拒绝
    with pytest.raises(ValueError, match="登录名已存在"):
        store.create_account(username="alice", display_name="另一个", password="x")


def test_password_hash_is_derived_never_plaintext(store: SQLiteStore) -> None:
    """F6：密码本地派生——存储值必须不是明文，且同密码不同账号不同散列。

    ``get_account`` 刻意不暴露派生字段，这里直查库表验证存储值：
    若 ``_derive_password`` 被改为明文存储（hash 列直接存明文），
    本测试立即变红：派生实现的唯一护栏。
    """
    first = store.create_account(
        username="hash-guard-a", display_name="", password="s3cret-pass"
    )
    second = store.create_account(
        username="hash-guard-b", display_name="", password="s3cret-pass"
    )

    def stored_hash(account_id: str) -> tuple[str, str]:
        row = store.connection.execute(
            "SELECT password_hash, password_salt FROM accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        assert row is not None
        return row[0], row[1]

    first_hash, first_salt = stored_hash(first["account_id"])
    second_hash, second_salt = stored_hash(second["account_id"])
    # 存储值不是明文
    assert first_hash != "s3cret-pass"
    assert first_hash != ""
    # 随机 salt：同密码不同账号散列不同
    assert first_hash != second_hash
    assert first_salt != second_salt
    # 验证仍然可用（散列可被 verify 反向校验）
    assert store.verify_password(first["account_id"], "s3cret-pass") is True


def test_change_password_requires_old_password(store: SQLiteStore) -> None:
    account = store.create_account(
        username="bob", display_name="鲍勃", password="old-pass"
    )
    assert store.change_password(account["account_id"], "bad", "new-pass") is False
    assert store.verify_password(account["account_id"], "old-pass") is True
    assert store.change_password(account["account_id"], "old-pass", "new-pass") is True
    assert store.verify_password(account["account_id"], "new-pass") is True


def test_update_profile_and_login_timestamp(store: SQLiteStore) -> None:
    account = store.create_account(
        username="carol", display_name="卡罗", password="p"
    )
    updated = store.update_account_profile(
        account["account_id"], display_name="卡洛琳", avatar="avatar://carol.png"
    )
    assert updated["display_name"] == "卡洛琳"
    assert updated["avatar"] == "avatar://carol.png"
    logged = store.update_last_login(account["account_id"])
    assert logged["last_login_at"] is not None


def test_account_config_and_secret_roundtrip(store: SQLiteStore) -> None:
    account = store.create_account(username="dave", display_name="戴夫", password="p")
    store.set_configs(
        account["account_id"],
        {"dialogue.model": "deepseek-chat", "engine": "codex"},
    )
    assert store.get_config(account["account_id"], "dialogue.model") == "deepseek-chat"
    assert store.get_config(account["account_id"], "engine") == "codex"
    assert store.get_config(account["account_id"], "missing") is None

    store.set_secret(account["account_id"], "dialogue.api_key", "sk-abc123")
    assert store.get_secret(account["account_id"], "dialogue.api_key") == "sk-abc123"
    # 账号间隔离：另一个账号读不到
    other = store.create_account(username="erin", display_name="艾琳", password="p")
    assert store.get_config(other["account_id"], "engine") is None
    assert store.get_secret(other["account_id"], "dialogue.api_key") is None


def test_projects_isolated_by_account(store: SQLiteStore) -> None:
    alice = store.create_account(username="alice2", display_name="爱丽丝", password="p")
    bob = store.create_account(username="bob2", display_name="鲍勃", password="p")
    alice_project = store.create_project(
        name="A 项目", root_path="C:/a", account_id=alice["account_id"]
    )
    bob_project = store.create_project(
        name="B 项目", root_path="C:/b", account_id=bob["account_id"]
    )
    assert alice_project.account_id == alice["account_id"]
    ids = {p.project_id for p in store.list_projects_for_account(alice["account_id"])}
    assert alice_project.project_id in ids
    assert bob_project.project_id not in ids
    # 默认账号不混入其他账号的项目
    default_ids = {p.project_id for p in store.list_projects_for_account("default-local")}
    assert alice_project.project_id not in default_ids


def test_migration_assigns_existing_projects_to_default_account(
    tmp_path: Path,
) -> None:
    """模拟 v4 旧库：projects 无 account_id 列 → 升级后归入默认账号。"""
    import sqlite3

    database = tmp_path / "data" / "pair_harness.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.executescript(
        """
        CREATE TABLE projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            root_path TEXT NOT NULL,
            approval_mode TEXT NOT NULL DEFAULT 'request_approval',
            reasoning_effort TEXT NOT NULL DEFAULT 'low',
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_opened_at TEXT NOT NULL
        );
        INSERT INTO projects(project_id, name, root_path, created_at, last_opened_at)
        VALUES ('legacy-1', '旧项目', 'C:/legacy', '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    store = SQLiteStore(database)
    try:
        default_ids = {p.project_id for p in store.list_projects_for_account("default-local")}
        assert "legacy-1" in default_ids
        # 新项目默认归属当前默认账号
        fresh = store.create_project(name="新项目", root_path="C:/new")
        assert fresh.account_id == "default-local"
    finally:
        store.close()
