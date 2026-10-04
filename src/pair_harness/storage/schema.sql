PRAGMA foreign_keys = ON;

-- 本地账号。密码只存 PBKDF2 派生结果；头像、显示名、引导状态与主题按账号隔离。
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

-- 应用级单值状态（当前登录账号等）。
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 账号偏好表由版本 5 迁移建立，当前没有读写方。
CREATE TABLE IF NOT EXISTS account_preferences (
    account_id TEXT PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
    theme TEXT NOT NULL DEFAULT 'dark',
    vad_enabled INTEGER NOT NULL DEFAULT 0,
    last_mode TEXT NOT NULL DEFAULT 'chat'
);

-- 账号级非密钥配置（服务商、模型、推理档位等键值）。
CREATE TABLE IF NOT EXISTS provider_configs (
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (account_id, key)
);

-- 账号级密钥（API Key 等），本地明文存储，对外只回显掩码。
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
    -- ApprovalMode 枚举值
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
    -- 标题来源：default 初始名「新聊天」，auto 助手生成，user 用户命名。
    -- 自动标题只写入 default 的聊天，用户命名后不再被覆盖。
    title_source TEXT NOT NULL DEFAULT 'default',
    last_mode TEXT NOT NULL DEFAULT 'chat',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- 聊天绑定的自定义角色卡 card_id；内置角色为 NULL。
    character_card_id TEXT NULL,
    -- 聊天创建时使用的搭档绑定；旧数据或匹配不到时为 NULL。
    binding_id TEXT NULL
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

-- 持久化会话队列。忙碌时提交先入队（followup），明确选择“立即插入”才是
-- steer（置队首）。
-- status: queued / processing / withdrawn / failed；派发完成即删除，withdrawn
-- 供撤回历史，failed 保留派发失败的原因（error）。origin 与 remote_device_*
-- 记录提交来源，派发出的回合沿用它。
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
    source_message_id TEXT,
    origin TEXT NOT NULL DEFAULT 'desktop',
    remote_device_key TEXT,
    remote_device_name TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversation_inbox_dispatch
ON conversation_inbox(conversation_id, status, position);

-- 角色卡。card_json 存 codec.dump_card_v3 完整文本（酒馆标准字段 +
-- extensions.hsr，权威位置见 docs/character-card/角色卡数据契约.md）；
-- 归档集合存在 app_state。
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

-- 搭档绑定：base_pair_id 指向 YAML 搭档配置（助手、主题与运行配置），
-- binding_id 是用户真正选择的搭档身份。character_card_id 为 NULL 表示内置角色。
-- 唯一索引把同一张卡与同一个内置搭档约束成一行；SQLite 唯一索引下多个 NULL
-- 互不冲突，内置搭档靠绑定主键保证每个 base_pair_id 一行。
CREATE TABLE IF NOT EXISTS partner_bindings (
    binding_id TEXT PRIMARY KEY,
    character_card_id TEXT NULL,
    base_pair_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_partner_bindings_scope
ON partner_bindings(character_card_id, base_pair_id);

-- 三个内置搭档的绑定随新库一次建全，binding_id 稳定为 builtin:<pair_id>。
INSERT OR IGNORE INTO partner_bindings(
    binding_id, character_card_id, base_pair_id, enabled, created_at, updated_at
)
SELECT 'builtin:' || pair_id, NULL, pair_id, 1,
    strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'),
    strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
FROM (
    SELECT 'firefly_sam' AS pair_id
    UNION ALL SELECT 'march7_fourth_mirror'
    UNION ALL SELECT 'phainon_ancient_machine'
);

-- 投影表由版本 11 迁移建立，当前没有读写方。
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

-- 聊天级摘要。covers_* 描述连续、已最终落库的消息区间；
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

-- 同一区间重复摘要幂等。
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_summaries_range
ON conversation_summaries(conversation_id, covers_from_message_id, covers_to_message_id);

CREATE INDEX IF NOT EXISTS idx_conversation_summaries_conversation
ON conversation_summaries(conversation_id, updated_at DESC);

-- 配对级长期记忆。作用域唯一键
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

-- 回合与任务指标。未观测字段为 NULL，真实零值为 0；每个
-- (conversation, turn_kind, turn) 只有一行。
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

