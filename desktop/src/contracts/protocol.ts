export type MessageSource = "user" | "character" | "assistant" | "tool" | "system";

export type MessageKind =
  | "user.text"
  | "character.speech"
  | "assistant.natural_language"
  | "assistant.reasoning"
  | "tool.record"
  | "system.status"
  | "system.summary"
  | "system.error"
  | "system.approval"
  | "assistant.code"
  | "assistant.command";

export type MessageTarget = "character" | "assistant";
export type MessageOrigin = "user" | "character_delegation" | "system";
export type MessageStatus =
  | "sending"
  | "queued"
  | "received"
  | "processing"
  | "done"
  | "failed"
  | "cancelled";

export interface Message {
  message_id: string;
  conversation_id: string;
  pair_id: string;
  engine_turn_id: string | null;
  source: MessageSource;
  kind: MessageKind;
  text: string;
  payload: Record<string, unknown>;
  tts_eligible: boolean;
  created_at: string;
  streaming?: boolean;
  target?: MessageTarget;
  origin?: MessageOrigin;
  delegation_id?: string | null;
  status?: MessageStatus;
  /** 助手 segment 归属的任务。 */
  task_id?: string | null;
  /** 同一聊天内消息与工具记录共用的时间线序号，界面只按它排序。 */
  timeline_order: number;
  /**
   * 角色自然语言回复产生时服务端能否真实合成语音（账号专属音色已生成且凭据齐备），
   * 随 message.created 下发。缺省与 false 都不展示朗读入口。
   */
  tts_ready?: boolean;
}

export type ToolRunStatus = "running" | "succeeded" | "failed" | "denied";

export interface ToolRun {
  tool_call_id: string;
  conversation_id: string;
  task_id: string;
  engine_turn_id: string;
  sequence: number;
  status: ToolRunStatus;
  title: string;
  summary: string;
  details: string;
  /** 首次观察到工具事件时分配，更新沿用原序号。 */
  timeline_order: number;
}

export type ApprovalMode = "request_approval" | "review" | "full_auto";
export type ReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max";
export type ConversationMode = "chat" | "collaboration";
export type TaskStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

export type TurnStatus =
  | "queued"
  | "accepted"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface Turn {
  turn_id: string;
  account_id: string;
  project_id: string;
  conversation_id: string;
  target: MessageTarget;
  source_message_id: string;
  status: TurnStatus;
  created_at: string;
  updated_at: string;
}

export type QueueIntent = "followup" | "steer";

export interface QueueItem {
  queue_item_id: string;
  account_id: string;
  conversation_id: string;
  target: MessageTarget;
  text: string;
  intent: QueueIntent;
  position: number;
  status: "queued" | "processing" | "withdrawn" | "failed";
  /** 派发失败的原始原因；其余状态为 null。 */
  error: string | null;
  created_at: string;
  source_message_id: string | null;
  /** 提交来源，派发出的回合沿用。 */
  origin: "desktop" | "remote";
  remote_device_key: string | null;
  remote_device_name: string | null;
}

export interface ProjectRuntimeContext {
  project_name: string;
  project_abs_dir: string;
  local_time: string;
  timezone: string;
  conversation_mode: ConversationMode;
}

export interface AccountRecord {
  account_id: string;
  username: string;
  display_name: string;
  avatar: string;
  last_login_at: string | null;
  onboarding_complete: boolean;
  theme: "dark" | "light";
}

export interface ProjectRecord {
  project_id: string;
  name: string;
  root_path: string;
  approval_mode: ApprovalMode;
  reasoning_effort: ReasoningEffort;
  archived: boolean;
  created_at: string | null;
  last_opened_at: string | null;
  path_available: boolean;
  conversations: ConversationRecord[];
}

export interface ConversationRecord {
  conversation_id: string;
  project_id: string | null;
  pair_id: string;
  title: string;
  last_mode: "chat" | "collaboration" | string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  /** 本聊天绑定的角色卡 id；null 表示使用内置角色。 */
  character_card_id?: string | null;
  /** 创建本聊天时使用的搭档绑定 id；迁移未匹配到绑定的旧会话为 null。 */
  binding_id?: string | null;
  /** 后端统一解析的角色身份；缺失时由界面按 pair_id 回退内置渲染。 */
  character_identity?: CharacterIdentity | null;
}

export interface PairSpeaker {
  id: string;
  name: string;
  voice_id: string;
}

export type PairSpeakerSummary = PairSpeaker;

/** 目录项里的角色侧摘要；卡搭档的名字与头像引用实时取自角色卡。 */
export interface PairCharacterSummary {
  id: string;
  name: string;
  voice_id: string;
  /** 头像资产引用；内置搭档与无头像的卡为 null。 */
  avatar_ref: string | null;
  /** 头像资产版本，随头像变更推进，用于客户端的头像缓存失效。 */
  avatar_version: string | null;
  /** 角色卡已不可用（已删除）时为 true。 */
  missing: boolean;
}

/** 新建聊天目录的一个搭档选项：内置搭档或一条角色卡绑定。 */
export interface PairOption {
  /** 目录内稳定主键；内置项为 `builtin:<pair_id>`，卡项为持久化绑定 id。 */
  binding_id: string;
  /** 运行链路使用的搭档配置 id（卡项的 base pair）。 */
  pair_id: string;
  /** 绑定的角色卡 id；内置项为 null。 */
  character_card_id: string | null;
  source: "builtin" | "card";
  character: PairCharacterSummary;
  assistant: PairSpeaker;
  theme: PairTheme;
}

/** 后端统一身份解析器给出的会话角色身份，会话行与顶栏按它渲染。 */
export interface CharacterIdentity {
  name: string;
  avatar_ref: string | null;
  avatar_version: string | null;
  missing: boolean;
  source: "builtin" | "card";
}

export interface PairTheme {
  character_text: string;
  character_primary: string;
  character_deep: string;
  character_active: string;
  assistant_primary: string;
  assistant_bright: string;
  assistant_shadow: string;
}

export interface PairRecord {
  pair_id: string;
  character: PairSpeaker;
  assistant: PairSpeaker;
  theme: PairTheme;
}

export type PairSummary = PairRecord;

export const PAIR_NOT_FOUND = "PAIR_NOT_FOUND";

/** 角色卡导入导出错误码。 */
export const CARD_IMPORT_FAILED = "card_import_failed";
export const CARD_READ_ONLY = "card_read_only";
export const CARD_PUBLISH_INVALID = "card_publish_invalid";
export const CARD_AVATAR_UNSUPPORTED = "card_avatar_unsupported";
export const CARD_AVATAR_TOO_LARGE = "card_avatar_too_large";

/** PNG 导出与电源状态错误码。 */
export const CARD_EXPORT_FAILED = "card_export_failed";
export const POWER_STATUS_UNAVAILABLE = "power_status_unavailable";

/** 角色卡音色错误码。 */
export const VOICE_NOT_CONFIGURED = "voice_not_configured";
export const VOICE_REFERENCE_MISSING = "voice_reference_missing";
export const VOICE_REFERENCE_INVALID = "voice_reference_invalid";
export const VOICE_CARD_PROVISION_IN_PROGRESS = "voice_card_provision_in_progress";
export const VOICE_CARD_NOT_READY = "voice_card_not_ready";

/** 手机语音与审批仲裁错误码。 */
export const VOICE_AUDIO_SEQ_GAP = "voice_audio_seq_gap";
export const VOICE_TRANSCRIPT_EMPTY = "voice_transcript_empty";
export const APPROVAL_ALREADY_RESOLVED = "approval_already_resolved";

export interface ActiveTask {
  project_id: string;
  conversation_id: string;
  task_id: string;
  engine_turn_id: string | null;
}

export interface PendingApproval {
  approval_id: string;
  conversation_id: string;
  operation: {
    tool_kind: "file_write" | "file_delete" | "shell" | "patch";
    command: string | null;
    paths: string[];
    patch_file_count: number | null;
    summary: string;
  };
  reason: string;
  requested_at?: string;
  expires_at?: string;
  /** 审批归属的任务 id。 */
  task_id?: string;
}

export interface VoiceState {
  supported: boolean;
  /** 语音功能总开关（账号配置 voice.enabled；Composer 据此隐藏语音按钮）。 */
  enabled?: boolean;
  /** 古代机械（助手）自动朗读开关（账号配置 assistant_voice_enabled，默认关闭）。 */
  assistant_voice_enabled: boolean;
  vad: string;
  vad_enabled: boolean;
  ptt: boolean;
  tts: string;
  asr_partial: string;
  error: string | null;
  /** 待播队列条数（不含正在播放的当前条）。 */
  speech_queue_len: number;
}

export interface AccountListItem extends AccountRecord {
  is_last_login: boolean;
}

export interface DesktopSnapshot {
  projects: ProjectRecord[];
  current_account_id: string;
  current_account: AccountRecord;
  accounts: AccountListItem[];
  current_project_id: string;
  current_conversation_id: string;
  current_project: Omit<ProjectRecord, "conversations">;
  current_conversation: ConversationRecord;
  messages: Message[];
  tool_runs: ToolRun[];
  turns: Turn[];
  queue_items: QueueItem[];
  /** 全局当前聊天的活动任务。 */
  active_task: ActiveTask | null;
  /** 全账号活动任务集合，同一聊天同时只有一个活动任务。 */
  active_tasks: ActiveTask[];
  busy: boolean;
  approvals: PendingApproval[];
  remote_control: RemoteControlState;
  voice: VoiceState;
  pair: PairRecord;
  /** 完整可选搭档目录：内置搭档在前，角色卡绑定在后。 */
  pairs: PairOption[];
  /** 目录版本，随绑定与角色卡变更递增；客户端据此丢弃乱序的旧响应。 */
  catalog_version: number;
  sequence: number;
  /** 快照所属连接代次；旧代次快照不能覆盖新代次状态。 */
  stream_id: string;
}

/** conversation.open 的只读装载结果：只装载指定聊天，不改变后端全局当前聊天。 */
export interface ConversationOpenResult {
  conversation: ConversationRecord;
  project: Omit<ProjectRecord, "conversations">;
  pair: PairRecord;
  messages: Message[];
  tool_runs: ToolRun[];
  turns: Turn[];
  queue_items: QueueItem[];
  active_task: ActiveTask | null;
  /** 响应生成时最近已发出的同连接事件序号，用于重放等待期间的实时事件。 */
  sequence: number;
  stream_id: string;
}

/** conversation.create 的结果：bootstrap 快照加 reused。请求带 reuse_active=true 时，
    同项目同绑定已有活跃会话则复用它；无绑定的普通会话不参与复用。 */
export type ConversationCreateResult = DesktopSnapshot & { reused: boolean };

/** pair.list：权威搭档目录与目录版本（与快照 pairs / catalog_version 同形）。 */
export interface PairListResult {
  pairs: PairOption[];
  catalog_version: number;
}

/** card.avatar：卡头像的 base64 数据；卡没有头像时为 null。 */
export interface CardAvatarResult {
  avatar: CardAvatarPayload | null;
}

/** card.updated：角色卡数据变化；catalog_version 是变化后的目录版本。 */
export interface CardUpdatedPayload {
  card_id: string;
  catalog_version: number;
}

/** pair.updated：搭档目录已变化，客户端据此重取 pair.list。 */
export interface PairUpdatedPayload {
  catalog_version: number;
}

/** task.cancel：cancelled=false 表示服务端没有取消任何任务（任务不在运行或已结束）。 */
export interface TaskCancelResult {
  cancelled: boolean;
}

/** config.test_connection：ok 是连通结论，message 是服务端给出的说明原文。 */
export interface ConfigTestConnectionResult {
  ok: boolean;
  message: string;
  provider?: string;
  base_url?: string;
  model?: string;
}

export type DesktopCommandMethod =
  | "ping"
  | "app.bootstrap"
  | "app.shutdown"
  | "pair.list"
  | "project.create"
  | "project.select"
  | "project.update_settings"
  | "project.archive"
  | "conversation.create"
  | "conversation.select"
  | "conversation.open"
  | "conversation.rename"
  | "conversation.archive"
  | "conversation.set_mode"
  | "chat.submit"
  | "queue.edit"
  | "queue.withdraw"
  | "queue.prioritize"
  | "task.cancel"
  | "approval.resolve"
  | "voice.vad_set"
  | "voice.ptt_start"
  | "voice.ptt_stop"
  | "voice.tts_stop"
  | "voice.tts_play"
  | "voice.tts_skip"
  | "voice.preview"
  | "voice.provision"
  | "account.list"
  | "account.register"
  | "account.login"
  | "account.logout"
  | "account.switch"
  | "account.update_profile"
  | "account.change_password"
  | "account.onboarding_complete"
  | "config.get"
  | "config.set"
  | "config.test_connection"
  | "card.list"
  | "card.get"
  | "card.create_draft"
  | "card.update"
  | "card.duplicate"
  | "card.archive"
  | "card.unarchive"
  | "card.delete"
  | "card.select_active"
  | "card.peek_import"
  | "card.import_json"
  | "card.import_png"
  | "card.export_json"
  | "card.export_png"
  | "card.publish"
  | "card.set_avatar"
  | "card.remove_avatar"
  | "card.avatar"
  | "voice.card_bind_reference"
  | "voice.card_create"
  | "voice.card_unbind"
  | "voice.card_preview"
  | "voice.mobile_ptt_start"
  | "voice.mobile_audio_chunk"
  | "voice.mobile_ptt_stop"
  | "voice.mobile_tts_stop"
  | "summary.get"
  | "summary.regenerate"
  | "memory.list"
  | "memory.create"
  | "memory.update"
  | "memory.delete"
  | "metrics.query"
  | "diagnostics.prompt_assembly"
  | "remote.control_status"
  | "remote.issue_code"
  | "remote.pair"
  | "remote.list_devices"
  | "remote.revoke"
  | "remote.claim_control"
  | "remote.release_control"
  | "remote.tunnel_start"
  | "remote.tunnel_stop"
  | "remote.tunnel_status"
  | "power.get_status";

export interface DesktopCommand {
  kind: "request";
  id: string;
  method: DesktopCommandMethod;
  params: Record<string, unknown>;
  /** 发起请求的前端窗口视图命名空间。 */
  view_id?: string;
}

export interface DesktopResponse<T = unknown> {
  kind: "response";
  id: string;
  ok: boolean;
  result?: T;
  error?: { code: string; message: string; details?: Record<string, unknown> };
}

export type DesktopEventName =
  | "backend.ready"
  | "state.snapshot"
  | "message.created"
  | "message.status_changed"
  | "message.delta"
  | "message.finalized"
  | "summary.started"
  | "summary.completed"
  | "summary.failed"
  | "memory.updated"
  | "memory.deleted"
  | "tool_run.upserted"
  | "approval.requested"
  | "approval.resolved"
  | "review.started"
  | "review.completed"
  | "review.failed"
  | "turn.started"
  | "turn.status_changed"
  | "queue.changed"
  | "task.busy_changed"
  | "conversation.changed"
  | "project.changed"
  | "card.updated"
  | "pair.updated"
  | "account.changed"
  | "voice.asr_partial"
  | "voice.state_changed"
  | "voice.provision_changed"
  | "voice.card_provision_changed"
  | "voice.mobile_transcript"
  | "voice.mobile_tts_chunk"
  | "voice.mobile_tts_end"
  | "voice.mobile_tts_failed"
  | "voice.playback_interrupted"
  | "remote.control_changed"
  | "remote.paired"
  | "conversation.card_missing"
  | "error.reported"
  | "diagnostic.warning"
  | "serve.started"
  | "power.status_changed"
  | "tunnel.started"
  | "tunnel.stopped"
  | "tunnel.failed";

/** Sidecar 发出的事件；按 (stream_id, sequence) 去重和查缺。 */
export interface DesktopEvent<T = Record<string, unknown>> {
  kind: "event";
  event: DesktopEventName;
  sequence: number;
  /** 连接代次标识。 */
  stream_id?: string;
  payload: T;
}

/**
 * Rust 宿主合成的事件：连接断开与恢复、断开原因和非法输出报告，不带序号。
 * Sidecar 自己发出的 error.reported 带序号，属于 DesktopEvent。
 */
export interface HostEvent {
  kind: "event";
  event: "connection.status" | "error.reported";
  sequence?: never;
  stream_id?: string;
  payload: Record<string, unknown>;
}

/** 桌面窗口订阅流：Sidecar 事件与宿主事件，按信封是否带 sequence 区分。 */
export type DesktopStreamEvent = DesktopEvent | HostEvent;

export interface MessageCreatedPayload {
  message: Message;
  /** 服务端在创建时给出的真实可朗读能力；store 可合并进本地视图模型。 */
  tts_ready?: boolean;
}

export interface MessageDeltaPayload {
  message_id: string;
  conversation_id: string;
  pair_id?: string;
  source: "assistant" | "character";
  kind: string;
  delta: string;
  task_id?: string;
  channel?: string;
  /** 流式段生命周期；后端在 reasoning/speech 开始与结束时明确下发。 */
  started?: boolean;
  completed?: boolean;
  reasoning_streaming?: boolean;
  /** 助手 segment 的段号。 */
  segment_index?: number | null;
  /** 所属消息的时间线序号。 */
  timeline_order: number;
}

/** voice.provision_changed 事件载荷（不含 Key/Authorization）。 */
export interface VoiceProvisionEventPayload {
  account_id: string;
  speaker_id: string;
  state: "pending" | "creating" | "completed" | "failed" | string;
  completed: number;
  total: number;
  error: string | null;
  voice_id?: string | null;
}

/* 角色卡导入、导出、头像、音色与手机语音的线缆类型。
   字段保持 snake_case；camelCase 视图模型在 view-models.ts。 */

/** 已保留但不运行条目的类别（character_cards/codec.py 的 NotExecutedCategory）。 */
export type NotExecutedCategory = "world_book" | "macro" | "runtime_trigger" | "command_panels";

/** 一条已保留但不运行的内容；text 是字段路径与说明。 */
export interface NotExecutedItemPayload {
  category: NotExecutedCategory;
  text: string;
}

/** 角色卡兼容报告（character_cards/codec.py 的 CompatReport）。 */
export interface CompatReportPayload {
  applied: string[];
  preserved: string[];
  not_executed: NotExecutedItemPayload[];
  normalized_from_root: string[];
  warnings: string[];
  errors: string[];
}

/** card.peek_import 的预览载荷，JSON 与 PNG 共用，format 区分。 */
export interface CardImportPreviewPayload {
  name: string;
  spec_version: string;
  /** 后端按文件签名分派格式，不看扩展名。 */
  format: "json" | "png";
  avatar_available: boolean;
  /** PNG 分支携带 IHDR 宽高（像素）；JSON 分支与解析失败时为 null。 */
  avatar_width: number | null;
  avatar_height: number | null;
  greeting_count: number;
  world_book_entries: number;
  tags: string[];
  report: CompatReportPayload;
}

export interface CardPeekImportResult {
  preview: CardImportPreviewPayload;
}

export interface CardImportJsonResult {
  card_id: string;
  name: string;
  state: CharacterCardState;
  report: CompatReportPayload;
}

export interface CardExportJsonResult {
  exported: boolean;
  path: string;
  avatar_saved: boolean;
}

export interface CardPublishResult {
  card_id: string;
  state: CharacterCardState;
}

export interface CardAvatarPayload {
  mime_type: string;
  data_base64: string;
}

export interface CardSetAvatarResult {
  card_id: string;
  asset_id: string;
  mime_type: string;
}

export interface CardRemoveAvatarResult {
  card_id: string;
  removed: boolean;
}

export interface VoiceCardBindReferenceResult {
  card_id: string;
  asset_id: string;
  duration_seconds: number;
  size_bytes: number;
  mime_type: string;
}

export interface VoiceCardCreateResult {
  card_id: string;
  state: CharacterVoiceState;
  voice_id: string;
}

export interface VoiceCardUnbindResult {
  card_id: string;
  state: CharacterVoiceState;
}

export interface VoiceCardProvisionChangedPayload {
  card_id: string;
  state: CharacterVoiceState;
  voice_id: string | null;
  error: string | null;
}

export interface VoiceMobilePttStartResult {
  session_id: string;
}

export interface VoiceMobilePttStopResult {
  session_id: string;
  transcript: string;
  conversation_id: string;
}

export interface VoiceMobileTranscriptPayload {
  conversation_id: string;
  session_id: string;
  text: string;
  is_final: boolean;
}

export interface VoiceMobileTtsChunkPayload {
  conversation_id: string;
  message_id: string;
  seq: number;
  mime: string;
  data: string;
}

export interface VoiceMobileTtsEndPayload {
  conversation_id: string;
  message_id: string;
}

/**
 * 审批终态；approval_already_resolved 的 error.details 与之同形。
 * request_reason 是触发审批的理由；resolution_reason 是终态原因（取消、超时、
 * 审查结论），用户裁决时为 null。来源缺失保持 null。
 */
export interface ApprovalResolvedPayload {
  approval_id: string;
  conversation_id: string;
  task_id: string;
  decision: "allow" | "allow_for_conversation" | "deny" | "timeout";
  resolved_by: "desktop" | "remote" | "system" | null;
  actor: "user" | "reviewer" | "system";
  request_reason: string;
  resolution_reason: string | null;
  resolved_at: string;
  error_code: "approval_timeout" | null;
}

export interface ConversationSummary {
  summary_id: string; conversation_id: string; status: "idle" | "running" | "completed" | "failed";
  covers_from_message_id: string | null; covers_to_message_id: string | null; covers_message_count: number;
  content: Record<string, unknown> | null; provider: string | null; model: string | null;
  error_code: string | null; error: string | null; created_at: string; updated_at: string;
}

export interface MemoryScope { account_id: string; project_id: string; pair_id: string; character_ref: string; assistant_identity: string; }

/**
 * memory.list 条目与 memory.updated / memory.deleted 事件载荷的真实线缆形状。
 *
 * 来源：`application_service._memory_payload`（读写命令与事件共用），五分量作用域
 * 作为**扁平字段**下发，线缆上没有嵌套 scope 对象。做会话解析（携带 conversation_id）
 * 时载荷再带该字段。
 */
export interface MemoryWirePayload {
  memory_id: string;
  account_id: string;
  project_id: string;
  pair_id: string;
  character_ref: string;
  assistant_identity: string;
  status: "active" | "deleted";
  updated_at: string;
  content: Record<string, unknown>;
  conversation_id?: string;
}

/**
 * 前端记忆记录：线缆五分量 + 由 `pairMemoryFromPayload` 派生的嵌套 scope。
 *
 * scope 是同一批服务端原值的另一种摆放，客户端不拼接、不改写作用域；既有消费方
 * （上下文状态条）按嵌套 scope 读取，因此线缆解码一律经由该函数，避免出现
 * scope 缺失而显示「未报告」。
 */
export interface PairMemory {
  memory_id: string;
  scope: MemoryScope;
  content: Record<string, unknown>;
  status: "active" | "deleted";
  updated_at: string;
  /** 载荷原样携带的扁平分量（本地构造的记录可以没有；线缆解码后一定有）。 */
  account_id?: string;
  project_id?: string;
  pair_id?: string;
  character_ref?: string;
  assistant_identity?: string;
  /** 服务端按会话解析时随载荷下发的会话 id。 */
  conversation_id?: string;
}

/**
 * 线缆载荷 → 前端记录；缺失分量如实保留为空串，不伪造作用域。
 *
 * 结构非法（缺 memory_id、content 不是对象）时如实抛错，不静默吞：命令返回体
 * 一旦不符协议，调用方必须看到失败，而不是拿到一条字段缺失的“记忆”。
 */
export function pairMemoryFromPayload(payload: MemoryWirePayload): PairMemory {
  if (!payload || typeof payload.memory_id !== "string" || !payload.memory_id) {
    throw new Error("记忆载荷缺少 memory_id");
  }
  if (
    !payload.content ||
    typeof payload.content !== "object" ||
    Array.isArray(payload.content)
  ) {
    throw new Error("记忆载荷的 content 必须是对象");
  }
  const text = (value: unknown): string => (typeof value === "string" ? value : "");
  return {
    memory_id: payload.memory_id,
    scope: {
      account_id: text(payload.account_id),
      project_id: text(payload.project_id),
      pair_id: text(payload.pair_id),
      character_ref: text(payload.character_ref),
      assistant_identity: text(payload.assistant_identity),
    },
    content: payload.content,
    status: payload.status,
    updated_at: payload.updated_at,
    account_id: text(payload.account_id),
    project_id: text(payload.project_id),
    pair_id: text(payload.pair_id),
    character_ref: text(payload.character_ref),
    assistant_identity: text(payload.assistant_identity),
    ...(payload.conversation_id === undefined ? {} : { conversation_id: payload.conversation_id }),
  };
}

/** memory.list 的返回体。 */
export interface MemoryListResult { memories: MemoryWirePayload[]; }

/** memory.create / memory.update / memory.delete 的返回体。 */
export interface MemoryWriteResult { memory: MemoryWirePayload; }

export interface TurnMetric {
  metric_id: string; account_id: string; project_id: string; conversation_id: string; pair_id: string; character_ref: string; assistant_identity: string;
  turn_kind: "character_turn" | "assistant_task"; turn_id: string; task_id: string | null; engine_turn_id: string | null;
  provider: string | null; model: string | null; engine_type: string | null; reasoning_effort: string | null;
  status: TurnStatus; started_at: string; first_event_at: string | null; completed_at: string | null; duration_ms: number | null;
  input_tokens: number | null; output_tokens: number | null; total_tokens: number | null; tool_rounds: number; compression_count: number;
  approval_count: number; failure_type: string | null; failure_message: string | null; origin: "desktop" | "remote";
  remote_device_key: string | null; remote_device_name: string | null;
}

export interface RemoteControlState {
  state: "free" | "held" | "grace"; device_key: string | null; expires_at: string | null; grace_expires_at: string | null; reason: string | null;
}

export interface VoiceMobileTtsFailedPayload { conversation_id: string; message_id: string; error_code: string | null; error: string; }

/** card.import_png 的结果（与 card.import_json 同形）。 */
export type CardImportPngResult = CardImportJsonResult;

/** card.export_png 的结果：只写 ccv3 块，图像块为头像原始字节。 */
export interface CardExportPngResult {
  exported: boolean;
  path: string;
  name: string;
  spec_version: string;
  greeting_count: number;
  world_book_entries: number;
  extensions: string[];
}

/** power.get_status 的结果，power.status_changed 事件载荷与它同形。
    Windows 读取成功时两个超时字段为秒数（0 表示「从不」），非 Windows 为 null。 */
export interface PowerStatusPayload {
  supported: boolean;
  platform: string;
  plan_name: string;
  ac_sleep_timeout_seconds: number | null;
  dc_sleep_timeout_seconds: number | null;
  remote_serve_enabled: boolean;
  threshold_seconds: number;
  at_risk: boolean;
  reason: string;
  checked_at: string;
  warnings: string[];
}

/* card.* 与 remote.* 命令的线缆类型。 */

/** 角色卡生命周期（character_cards 表 state 列）。 */
export type CharacterCardState = "draft" | "saved" | "imported" | "invalid";
/** 角色卡来源（character_cards 表 source 列；JSON 与 PNG 导入同为 tavern_import）。 */
export type CharacterCardSource = "builtin" | "user_created" | "tavern_import";
/** 角色卡音色绑定状态（CharacterVoiceState）。 */
export type CharacterVoiceState =
  | "voice_unconfigured"
  | "voice_creating"
  | "voice_ready"
  | "voice_failed";

/** card.list 的单条摘要（内置角色 card_id 形如 builtin:<speaker> 且 read_only=true）。 */
export interface CardSummaryPayload {
  card_id: string;
  name: string;
  state: CharacterCardState;
  source: CharacterCardSource;
  updated_at: string;
  has_avatar: boolean;
  voice_state: CharacterVoiceState;
  active: boolean;
  read_only: boolean;
  /** 是否在归档集合中；只有 include_archived=true 时才会列出已归档的卡。 */
  archived: boolean;
}

export interface CardListResult {
  cards: CardSummaryPayload[];
}

/** card.get：card 为酒馆 v3 JSON 对象（未知扩展原样保留在 data.extensions）；
    有头像时 avatar 为 base64 数据，否则为 null。 */
export interface CardGetResult {
  card_id: string;
  state: CharacterCardState;
  source: CharacterCardSource;
  created_at: string;
  updated_at: string;
  card: Record<string, unknown>;
  read_only: boolean;
  avatar: CardAvatarPayload | null;
  /** 后端对已存储的卡跑导入时同一套静态兼容扫描得到的报告。 */
  compat_report: CompatReportPayload;
}

export interface CardCreateDraftResult {
  card_id: string;
  state: CharacterCardState;
}

export interface CardUpdateResult {
  card_id: string;
  updated_at: string;
}

export interface CardDuplicateResult {
  card_id: string;
  name: string;
}

/** card.archive 与 card.unarchive 的结果；archived 为命令执行后的归档状态。 */
export interface CardArchiveResult {
  card_id: string;
  archived: boolean;
}

export interface CardDeleteResult {
  card_id: string;
  deleted: boolean;
}

/**
 * Sidecar --serve 的地址上报载荷，`serve.started` 事件与 `remote.issue_code` 的
 * `serve_address` 同形。`host` 为 null 表示服务已在监听但没有可用的局域网地址，原因见 `reason`。
 */
export interface ServeAddressPayload {
  host: string | null;
  port: number;
  mode?: "loopback" | "lan" | null;
  tls?: boolean | null;
  reason?: string | null;
}

/** remote.issue_code：配对码一次性、短期有效。返回体同时带上当前 serve 地址
    （远程服务尚未监听时为 null），不只依赖一次性的 serve.started 事件。 */
export interface RemoteIssueCodeResult {
  code: string;
  ttl_seconds: number;
  serve_address: ServeAddressPayload | null;
}

export interface RemotePairResult {
  token: string;
}

export interface RemoteDevice {
  device_name: string;
  issued_at: string;
  last_used_at: string;
  /** 签发后 30 天与最近使用后 7 天中较早的一个。 */
  expires_at: string;
  revoked: boolean;
}

export interface RemoteListDevicesResult {
  devices: RemoteDevice[];
}

/** remote.revoke 按设备名撤销其全部 token。 */
export interface RemoteRevokeResult {
  device_name: string;
  revoked_tokens: number;
}

/* 公网隧道（Cloudflare Quick Tunnel）。 */

export type TunnelState = "off" | "downloading" | "starting" | "ready" | "failed";

export interface RemoteTunnelStatusResult {
  state: TunnelState;
  public_url: string | null;
  hostname: string | null;
  error: string | null;
}

export interface RemoteTunnelStartResult {
  status: "starting";
}

export interface RemoteTunnelStopResult {
  status: "stopping";
}

export interface TunnelStartedPayload {
  public_url: string;
  hostname: string;
}

export interface TunnelStoppedPayload {
  reason: string;
}

export interface TunnelFailedPayload {
  error: string;
}
