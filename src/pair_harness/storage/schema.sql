PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    -- 计划 A6：输入区审批模式下拉框的选择，取值为 ApprovalMode 的三个枚举值
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

-- V0.2 M2（问题 9）：持久化会话队列（conversation_inbox）。
-- 忙碌时提交先入队（followup），明确选择“立即插入”才是 steer（置队首）。
-- status: queued / processing / withdrawn；派发完成即删除，withdrawn 供撤回历史。
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
-- O4.3：新库的完整表结构由本文件保证（IF NOT EXISTS 只影响新库）。
-- 旧库（user_version=0）的补列/删列迁移在 sqlite_store.SCHEMA_VERSION
-- 中逐级执行；新库创建后由 sqlite_store 直接标记当前版本。
-- 注意：此处不得写 PRAGMA user_version（executescript 每次打开都会执行，
-- 会跳过旧库迁移）。
