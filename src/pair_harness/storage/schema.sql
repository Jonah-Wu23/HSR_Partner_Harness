PRAGMA foreign_keys = ON;

-- V0.2 M3：本地账号（方案 §M3）。密码只存 PBKDF2 派生结果，
-- 头像/显示名/引导状态/主题按账号隔离；密钥进 secret_refs（本地明文，
-- 仅回显掩码，README 已注明单机取舍）。
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

-- V0.2 M3：应用级单值状态（当前登录账号等）。
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- V0.2 M3：账号级偏好（语音/VAD/模式等键值）。
CREATE TABLE IF NOT EXISTS account_preferences (
    account_id TEXT PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
    theme TEXT NOT NULL DEFAULT 'dark',
    vad_enabled INTEGER NOT NULL DEFAULT 0,
    last_mode TEXT NOT NULL DEFAULT 'chat'
);

-- V0.2 M3：账号级非密钥配置（服务商/模型/推理档位等键值）。
CREATE TABLE IF NOT EXISTS provider_configs (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

-- V0.2 M3：账号级密钥（API Key 等）。单机明文存储的取舍见 README；
-- 对外只回显掩码。
CREATE TABLE IF NOT EXISTS secret_refs (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    secret TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    -- V0.2 M3：项目归属账号（旧库迁移归入默认账号）
    account_id TEXT NOT NULL DEFAULT '',
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
    -- V0.2 M3：聊天归属账号（账号是完整隔离边界：项目/聊天/配置/密钥
    -- 互不串扰）。旧库由版本 7 迁移按项目归属回填。
    account_id TEXT NOT NULL DEFAULT '',
    project_id TEXT REFERENCES projects(project_id),
    pair_id TEXT NOT NULL,
    title TEXT NOT NULL,
    last_mode TEXT NOT NULL DEFAULT 'chat',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- V0.3.5：对话绑定的角色卡快照（card_id；内置角色为 NULL）。
    -- 与迁移 v10 的 ALTER 语义一致，新库直建，旧库由迁移补列。
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

-- V0.3.3：角色卡持久化。card_json 存 codec.dump_card_v3 完整文本（酒馆
-- 标准字段 + extensions.hsr，权威位置见 docs/character-card/角色卡数据契约.md）。
-- state/source 存 CharacterCardState 枚举值与来源值；归档集合走 app_state。
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

-- O4.3：新库的完整表结构由本文件保证（IF NOT EXISTS 只影响新库）。
-- 旧库（user_version=0）的补列/删列迁移在 sqlite_store.SCHEMA_VERSION
-- 中逐级执行；新库创建后由 sqlite_store 直接标记当前版本。
-- 注意：此处不得写 PRAGMA user_version（executescript 每次打开都会执行，
-- 会跳过旧库迁移）。
