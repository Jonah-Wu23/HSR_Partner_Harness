export type MessageSource = "user" | "character" | "assistant" | "tool" | "system";

export type MessageKind =
  | "user.text"
  | "character.speech"
  | "assistant.natural_language"
  | "assistant.reasoning"
  | "tool.record"
  | "system.status"
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
  /** V0.3.2 M1：助手 segment 归属的任务与统一时间线序号；旧记录为空。 */
  task_id?: string | null;
  timeline_order?: number | null;
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
  /** V0.3.2 M1：首次观察到工具事件时分配一次，更新沿用原序号。 */
  timeline_order?: number | null;
}

export type ApprovalMode = "request_approval" | "review" | "full_auto";
export type ReasoningEffort = "low" | "medium" | "high" | "xhigh" | "max";
export type ConversationMode = "chat" | "collaboration";

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
  status: "queued" | "processing" | "withdrawn";
  created_at: string;
  source_message_id: string | null;
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

export type ErrorSeverity = "fatal" | "recoverable" | "info";
export type ErrorSource =
  | "voice.asr"
  | "voice.tts"
  | "dialogue.deepseek"
  | "codex"
  | "sidecar";

export type ConnectionStatus = "connected" | "connecting" | "disconnected";

export interface ProjectRecord {
  project_id: string;
  name: string;
  root_path: string;
  approval_mode: ApprovalMode;
  reasoning_effort: string;
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
  /** V0.3.5 迁移 v10：本聊天绑定的角色卡 id；null 表示使用内置角色。 */
  character_card_id?: string | null;
}

export interface PairSpeaker {
  id: string;
  name: string;
  voice_id: string;
}

export type PairSpeakerSummary = PairSpeaker;

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

/** V0.3.5 角色卡导入导出错误码。 */
export const CARD_IMPORT_FAILED = "card_import_failed";
export const CARD_READ_ONLY = "card_read_only";
export const CARD_PUBLISH_INVALID = "card_publish_invalid";
export const CARD_AVATAR_UNSUPPORTED = "card_avatar_unsupported";
export const CARD_AVATAR_TOO_LARGE = "card_avatar_too_large";

/** V0.3.7 PNG 导出与电源状态错误码（契约冻结 §1.3/§1.5）。 */
export const CARD_EXPORT_FAILED = "card_export_failed";
export const POWER_STATUS_UNAVAILABLE = "power_status_unavailable";

/** V0.3.5 角色卡音色错误码。 */
export const VOICE_NOT_CONFIGURED = "voice_not_configured";
export const VOICE_REFERENCE_MISSING = "voice_reference_missing";
export const VOICE_REFERENCE_INVALID = "voice_reference_invalid";
export const VOICE_CARD_PROVISION_IN_PROGRESS = "voice_card_provision_in_progress";
export const VOICE_CARD_NOT_READY = "voice_card_not_ready";

/** V0.3.5 手机语音与审批仲裁错误码。 */
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
  /** V0.3.2 M5：审批归属的任务 id（approval.requested/resolved 载荷新增）。 */
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
  /** V0.2 M4：待播队列条数（不含正在播放的当前条），VoiceMiniPlayer 的 queuedCount。 */
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
  active_task: ActiveTask | null;
  /** V0.3.2 M5：全账号活动任务全量集合（同聊天一次只有一个活动任务）；
      旧协议快照缺省时前端回退用 active_task 建立单条目集合。 */
  active_tasks?: ActiveTask[];
  busy: boolean;
  approvals: PendingApproval[];
  voice: VoiceState;
  pair: PairRecord;
  pairs: PairSummary[];
  sequence: number;
  /** M2.1：快照所属连接代次；旧代次快照不能覆盖新代次状态。 */
  stream_id?: string | number;
}

/** V0.3.2 M5：conversation.open 的只读装载结果——只装载指定聊天，
    不改变后端全局当前聊天，也不影响其他窗口的导航状态。 */
export interface ConversationOpenResult {
  conversation: ConversationRecord;
  project: (Omit<ProjectRecord, "conversations"> & { conversations?: ConversationRecord[] }) | null;
  pair: PairRecord;
  messages: Message[];
  tool_runs: ToolRun[];
  turns: Turn[];
  queue_items: QueueItem[];
  active_task: ActiveTask | null;
  /** 响应生成时最近已发出的同连接事件序号，用于重放等待期间的实时事件。 */
  sequence: number;
  stream_id?: string | number;
}

export type DesktopCommandMethod =
  | "app.bootstrap"
  | "app.shutdown"
  | "app.reconnect"
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
  | "codex.oauth_start"
  | "codex.oauth_status"
  | "codex.logout"
  | "codex.api_login"
  | "card.list"
  | "card.get"
  | "card.create_draft"
  | "card.update"
  | "card.duplicate"
  | "card.archive"
  | "card.delete"
  | "card.select_active"
  /* V0.3.7：card.peek_import 为规范名；card.peek_import_json 保留为同一 handler 的别名（deprecated）。 */
  | "card.peek_import"
  | "card.peek_import_json"
  | "card.import_json"
  | "card.import_png"
  | "card.export_json"
  | "card.export_png"
  | "card.publish"
  | "card.set_avatar"
  | "card.remove_avatar"
  | "voice.card_bind_reference"
  | "voice.card_create"
  | "voice.card_unbind"
  | "voice.card_preview"
  | "voice.mobile_ptt_start"
  | "voice.mobile_audio_chunk"
  | "voice.mobile_ptt_stop"
  | "voice.mobile_tts_stop"
  | "remote.issue_code"
  | "remote.pair"
  | "remote.list_devices"
  | "remote.revoke"
  | "power.get_status";

export interface DesktopCommand {
  kind: "request";
  id: string;
  method: DesktopCommandMethod;
  params: Record<string, unknown>;
  /** V0.3.2 M5：发起请求的前端窗口视图命名空间。旧调用可省略。 */
  view_id?: string;
}

export interface DesktopResponse<T = unknown> {
  kind: "response";
  id: string;
  ok: boolean;
  result?: T;
  error?: { code: string; message: string };
}

export type DesktopEventName =
  | "backend.ready"
  | "state.snapshot"
  | "message.created"
  | "message.status_changed"
  | "message.delta"
  | "message.finalized"
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
  | "account.changed"
  | "voice.asr_partial"
  | "voice.state_changed"
  | "voice.provision_changed"
  | "voice.card_provision_changed"
  | "voice.mobile_transcript"
  | "voice.mobile_tts_chunk"
  | "voice.mobile_tts_end"
  | "connection.status"
  | "error.reported"
  | "serve.started"
  | "power.status_changed";

export interface DesktopEvent<T = Record<string, unknown>> {
  kind: "event";
  event: DesktopEventName;
  sequence: number;
  /** M2.1：连接代次标识；业务事件按 (stream_id, sequence) 去重和查缺。 */
  stream_id?: string | number;
  payload: T;
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
  /** V0.3.2 M1：助手 segment 的段号与工作台序号。 */
  segment_index?: number | null;
  timeline_order?: number | null;
}

/** V0.3.2 M6：voice.provision_changed 事件载荷（不含 Key/Authorization）。 */
export interface VoiceProvisionEventPayload {
  account_id: string;
  speaker_id: string;
  state: "pending" | "creating" | "completed" | "failed" | string;
  completed: number;
  total: number;
  error: string | null;
  voice_id?: string | null;
}

/* ------------------------------------------------------------------ *
 * V0.3.5 角色卡导入/导出/头像/音色与手机语音：线缆类型严格按契约冻结文档。
 * 字段保持 snake_case（与线缆一致）；camelCase 视图模型在 view-models.ts。
 * ------------------------------------------------------------------ */

/** 角色卡导入兼容报告（对应 character_cards/codec.py 的 CompatReport）。 */
export interface CompatReportPayload {
  applied: string[];
  preserved: string[];
  not_executed: string[];
  normalized_from_root: string[];
  warnings: string[];
  errors: string[];
}

/** card.peek_import 的预览载荷（V0.3.7 起 JSON/PNG 双格式共用，format 区分）。 */
export interface CardImportPreviewPayload {
  name: string;
  spec_version: string;
  /** V0.3.7：预览格式；真实后端按文件签名分派（PNG 签名优先，不信任扩展名）。 */
  format?: "json" | "png";
  avatar_available: boolean;
  /** V0.3.7：PNG 分支携带 IHDR 宽高（像素）；JSON 分支与解析失败时为 null。 */
  avatar_width?: number | null;
  avatar_height?: number | null;
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

/** V0.3.5 审批仲裁：approval.resolved 携带决策与来源，双端据此收敛。 */
export interface ApprovalResolvedPayload {
  approval_id: string;
  conversation_id?: string;
  decision: "approve" | "deny" | string;
  resolved_by: "desktop" | "remote" | string;
  task_id?: string;
}

/* ------------------------------------------------------------------ *
 * V0.3.7 PNG 双向兼容与电源状态（契约见 docs/plans/V0.3.7-契约冻结.md §1/§2）。
 * ------------------------------------------------------------------ */

/** card.import_png 的结果（与 card.import_json 同形）。 */
export type CardImportPngResult = CardImportJsonResult;

/** card.export_png 的结果（§1.3：只写 ccv3 块，图像块为头像原始字节）。 */
export interface CardExportPngResult {
  exported: boolean;
  path: string;
  name: string;
  spec_version: string;
  greeting_count: number;
  world_book_entries: number;
  extensions: string[];
}

/** power.get_status 的结果；power.status_changed 事件载荷与其完全同形（§1.5/§2.1）。
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
}

/* ------------------------------------------------------------------ *
 * V0.3.3 角色卡与手机远程：与 Sidecar card.* / remote.* 命令对齐的线缆类型。
 * 字段保持 snake_case（与线缆一致）；camelCase 视图模型在 view-models.ts。
 * ------------------------------------------------------------------ */

/** 角色卡生命周期（character_cards/states.py CharacterCardState）。 */
export type CharacterCardState = "draft" | "saved" | "imported" | "invalid";
/** 角色卡来源。 */
export type CharacterCardSource =
  | "builtin"
  | "user_created"
  | "imported_json"
  | "imported_png";
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
}

export interface CardListResult {
  cards: CardSummaryPayload[];
}

/** card.get：card 为酒馆 v3 JSON 对象（未知扩展原样保留在 data.extensions）；
    V0.3.5 新增 avatar 字段，有头像时返回 base64 数据，否则 null。 */
export interface CardGetResult {
  card_id: string;
  state: CharacterCardState;
  source: CharacterCardSource;
  created_at: string;
  updated_at: string;
  card: Record<string, unknown>;
  read_only: boolean;
  avatar: CardAvatarPayload | null;
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

export interface CardArchiveResult {
  card_id: string;
  archived: boolean;
}

export interface CardDeleteResult {
  card_id: string;
  deleted: boolean;
}

/** remote.issue_code：配对码一次性、短期有效（当前 ttl 300 秒）。 */
export interface RemoteIssueCodeResult {
  code: string;
  ttl_seconds: number;
}

export interface RemotePairResult {
  token: string;
}

export interface RemoteDevice {
  device_name: string;
  issued_at: string;
  last_used_at: string;
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
