import sqlite3
from pathlib import Path

from pair_harness.storage.sqlite_store import MIGRATIONS

# 发布版 schema.sql 的建表语句（去掉注释），来自 git show <tag>:src/pair_harness/storage/schema.sql。
# 键是该发布版的结构版本。v0.3.2（版本 8）与 v0.2.5 结构相同，迁移 8 只修数据。

_V0_1_0 = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    approval_mode TEXT NOT NULL DEFAULT 'request_approval',
    reasoning_effort TEXT NOT NULL DEFAULT 'low',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_opened_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id),
    pair_id TEXT NOT NULL,
    title TEXT NOT NULL,
    last_mode TEXT NOT NULL DEFAULT 'chat',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_project_updated
ON conversations(project_id, archived, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    message_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS tool_runs (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    tool_call_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    engine_turn_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    status TEXT NOT NULL,
    tool_json TEXT NOT NULL,
    PRIMARY KEY (conversation_id, tool_call_id)
);

CREATE INDEX IF NOT EXISTS idx_tool_runs_conversation_sequence
ON tool_runs(conversation_id, sequence);

CREATE TABLE IF NOT EXISTS engine_sessions (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    engine_type TEXT NOT NULL,
    session_ref TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_V0_2_5 = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    last_login_at TEXT,
    onboarding_complete INTEGER NOT NULL DEFAULT 0,
    theme TEXT NOT NULL DEFAULT 'dark',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_preferences (
    account_id TEXT PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
    theme TEXT NOT NULL DEFAULT 'dark',
    vad_enabled INTEGER NOT NULL DEFAULT 0,
    last_mode TEXT NOT NULL DEFAULT 'chat'
);

CREATE TABLE IF NOT EXISTS provider_configs (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

CREATE TABLE IF NOT EXISTS secret_refs (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    secret TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    approval_mode TEXT NOT NULL DEFAULT 'request_approval',
    reasoning_effort TEXT NOT NULL DEFAULT 'low',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_opened_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL DEFAULT '',
    project_id TEXT REFERENCES projects(project_id),
    pair_id TEXT NOT NULL,
    title TEXT NOT NULL,
    last_mode TEXT NOT NULL DEFAULT 'chat',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_project_updated
ON conversations(project_id, archived, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    message_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS tool_runs (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    tool_call_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    engine_turn_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    status TEXT NOT NULL,
    tool_json TEXT NOT NULL,
    PRIMARY KEY (conversation_id, tool_call_id)
);

CREATE INDEX IF NOT EXISTS idx_tool_runs_conversation_sequence
ON tool_runs(conversation_id, sequence);

CREATE TABLE IF NOT EXISTS engine_sessions (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    engine_type TEXT NOT NULL,
    session_ref TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_inbox (
    queue_item_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL DEFAULT '',
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    target TEXT NOT NULL,
    text TEXT NOT NULL,
    intent TEXT NOT NULL DEFAULT 'followup',
    position INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL,
    source_message_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversation_inbox_dispatch
ON conversation_inbox(conversation_id, status, position);
"""

_V0_4_1 = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    last_login_at TEXT,
    onboarding_complete INTEGER NOT NULL DEFAULT 0,
    theme TEXT NOT NULL DEFAULT 'dark',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_preferences (
    account_id TEXT PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
    theme TEXT NOT NULL DEFAULT 'dark',
    vad_enabled INTEGER NOT NULL DEFAULT 0,
    last_mode TEXT NOT NULL DEFAULT 'chat'
);

CREATE TABLE IF NOT EXISTS provider_configs (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

CREATE TABLE IF NOT EXISTS secret_refs (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    secret TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    approval_mode TEXT NOT NULL DEFAULT 'request_approval',
    reasoning_effort TEXT NOT NULL DEFAULT 'low',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_opened_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL DEFAULT '',
    project_id TEXT REFERENCES projects(project_id),
    pair_id TEXT NOT NULL,
    title TEXT NOT NULL,
    last_mode TEXT NOT NULL DEFAULT 'chat',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    character_card_id TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_project_updated
ON conversations(project_id, archived, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    message_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS tool_runs (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    tool_call_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    engine_turn_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    status TEXT NOT NULL,
    tool_json TEXT NOT NULL,
    PRIMARY KEY (conversation_id, tool_call_id)
);

CREATE INDEX IF NOT EXISTS idx_tool_runs_conversation_sequence
ON tool_runs(conversation_id, sequence);

CREATE TABLE IF NOT EXISTS engine_sessions (
    conversation_id TEXT PRIMARY KEY REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    engine_type TEXT NOT NULL,
    session_ref TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_inbox (
    queue_item_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL DEFAULT '',
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    target TEXT NOT NULL,
    text TEXT NOT NULL,
    intent TEXT NOT NULL DEFAULT 'followup',
    position INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL,
    source_message_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversation_inbox_dispatch
ON conversation_inbox(conversation_id, status, position);

CREATE TABLE IF NOT EXISTS character_cards (
    card_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    card_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character_assets (
    asset_id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_character_assets_card
ON character_assets(card_id);

CREATE TABLE IF NOT EXISTS conversation_projections (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL,
    message_id TEXT,
    summary_id TEXT,
    tool_call_id TEXT,
    covered_by_summary_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (conversation_id, entry_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_projections_position
ON conversation_projections(conversation_id, position);

CREATE INDEX IF NOT EXISTS idx_conversation_projections_kind
ON conversation_projections(conversation_id, kind, position);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    summary_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    covers_from_message_id TEXT NOT NULL,
    covers_to_message_id TEXT NOT NULL,
    covers_message_count INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    provider TEXT,
    model TEXT,
    status TEXT NOT NULL,
    error_code TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_summaries_range
ON conversation_summaries(conversation_id, covers_from_message_id, covers_to_message_id);

CREATE INDEX IF NOT EXISTS idx_conversation_summaries_conversation
ON conversation_summaries(conversation_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS pair_memories (
    memory_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    pair_id TEXT NOT NULL,
    character_ref TEXT NOT NULL,
    assistant_identity TEXT NOT NULL,
    conversation_id TEXT,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    provider TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pair_memories_scope
ON pair_memories(
    account_id, project_id, pair_id, character_ref, assistant_identity,
    status, updated_at DESC
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pair_memories_scope_active_content
ON pair_memories(
    account_id, project_id, pair_id, character_ref, assistant_identity, content
)
WHERE status = 'active';

CREATE TABLE IF NOT EXISTS turn_metrics (
    metric_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    pair_id TEXT NOT NULL,
    character_ref TEXT,
    assistant_identity TEXT,
    turn_kind TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    task_id TEXT,
    engine_turn_id TEXT,
    source_message_id TEXT,
    provider TEXT,
    model TEXT,
    engine_type TEXT,
    reasoning_effort TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    first_event_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    first_event_latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    tool_rounds INTEGER NOT NULL DEFAULT 0,
    compression_count INTEGER NOT NULL DEFAULT 0,
    approval_count INTEGER NOT NULL DEFAULT 0,
    failure_type TEXT,
    failure_message TEXT,
    origin TEXT NOT NULL DEFAULT 'desktop',
    remote_device_key TEXT,
    remote_device_name TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_turn_metrics_turn
ON turn_metrics(conversation_id, turn_kind, turn_id);

CREATE INDEX IF NOT EXISTS idx_turn_metrics_conversation
ON turn_metrics(conversation_id, started_at DESC, metric_id DESC);

CREATE INDEX IF NOT EXISTS idx_turn_metrics_account
ON turn_metrics(account_id, started_at DESC, metric_id DESC);

CREATE INDEX IF NOT EXISTS idx_turn_metrics_project
ON turn_metrics(project_id, started_at DESC, metric_id DESC);

CREATE INDEX IF NOT EXISTS idx_turn_metrics_pair
ON turn_metrics(pair_id, started_at DESC, metric_id DESC);

CREATE INDEX IF NOT EXISTS idx_turn_metrics_status
ON turn_metrics(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_turn_metrics_assistant
ON turn_metrics(assistant_identity, started_at DESC, metric_id DESC);
"""

RELEASE_SCHEMAS: dict[int, str] = {3: _V0_1_0, 7: _V0_2_5, 11: _V0_4_1}


def create_legacy_database(database: Path, version: int) -> sqlite3.Connection:
    """建出结构版本为 version 的旧库，返回连接供测试写入旧数据。

    从不高于 version 的最近发布版建表，再按 MIGRATIONS 逐级补到 version。
    发布版应用打开数据库时都会写入默认账号，这里同样写入。
    """
    release = max(level for level in RELEASE_SCHEMAS if level <= version)
    connection = sqlite3.connect(database)
    connection.executescript(RELEASE_SCHEMAS[release])
    for statements in MIGRATIONS[release:version]:
        for statement in statements:
            connection.execute(statement)
    if version >= 5:
        connection.execute(
            "INSERT OR IGNORE INTO accounts("
            "account_id, username, display_name, password_hash, password_salt,"
            "created_at) VALUES ("
            "'default-local', 'default', '默认账号', '', '', datetime('now'))"
        )
        connection.execute(
            "INSERT OR IGNORE INTO account_preferences(account_id) VALUES ('default-local')"
        )
    connection.execute(f"PRAGMA user_version = {version}")
    connection.commit()
    return connection
