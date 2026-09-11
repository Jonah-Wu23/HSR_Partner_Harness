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

-- V0.3.9（contract-v1 第 2/4/5 节）：持久化投影、聊天摘要、配对长期记忆与
-- 回合指标。投影只存引用（message_id/summary_id/tool_call_id），不复制原文；
-- messages/tool_runs 继续永久保存原文。
CREATE TABLE IF NOT EXISTS conversation_projections (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL,
    -- 投影内顺序，0 起，按会话唯一（契约第 1 节：不得用 rowid 作权威顺序）
    position INTEGER NOT NULL,
    kind TEXT NOT NULL,
    message_id TEXT,
    summary_id TEXT,
    tool_call_id TEXT,
    -- 已被摘要覆盖时指向摘要；NULL 表示该原文仍进入角色上下文
    covered_by_summary_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (conversation_id, entry_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_projections_position
ON conversation_projections(conversation_id, position);

CREATE INDEX IF NOT EXISTS idx_conversation_projections_kind
ON conversation_projections(conversation_id, kind, position);

-- V0.3.9：聊天级摘要。covers_* 描述连续、已最终落库的消息区间；
-- 摘要键只含 conversation_id，不跨聊天读取。status: idle|running|completed|failed。
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

-- 同一区间重复摘要幂等：投影引用不会因重跑而漂移。
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_summaries_range
ON conversation_summaries(conversation_id, covers_from_message_id, covers_to_message_id);

CREATE INDEX IF NOT EXISTS idx_conversation_summaries_conversation
ON conversation_summaries(conversation_id, updated_at DESC);

-- V0.3.9：配对级长期记忆。作用域唯一键
-- account_id + project_id + pair_id + character_ref + assistant_identity；
-- assistant_identity 是权威搭档配置的 pair.assistant.id，pair_id 不可替代。
-- 项目为空的日常聊天不读写长期记忆（project_id NOT NULL）。
-- conversation_id 只是来源记录，不加外键：记忆跨聊天存活，不随聊天删除。
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

-- 同作用域内同内容只保留一条 active（结构去重，不做关键词筛选）；
-- 已删除记录不阻塞重新写入。
CREATE UNIQUE INDEX IF NOT EXISTS idx_pair_memories_scope_active_content
ON pair_memories(
    account_id, project_id, pair_id, character_ref, assistant_identity, content
)
WHERE status = 'active';

-- V0.3.9：回合/任务指标（contract-v1 第 5 节）。未观测字段为 NULL，
-- 真实零值为 0；禁止用字符数估算 token。每个 (conversation, turn_kind, turn)
-- 只有一行，终态用 UPDATE 收尾。
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

-- O4.3：新库的完整表结构由本文件保证（IF NOT EXISTS 只影响新库）。
-- 旧库（user_version=0）的补列/删列迁移在 sqlite_store.SCHEMA_VERSION
-- 中逐级执行；新库创建后由 sqlite_store 直接标记当前版本。
-- 注意：此处不得写 PRAGMA user_version（executescript 每次打开都会执行，
-- 会跳过旧库迁移）。
