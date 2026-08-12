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
}

export type ApprovalMode = "request_approval" | "review" | "full_auto";
export type ReasoningEffort = "auto" | "low" | "medium" | "high" | "max";
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
}

export interface PairSpeaker {
  id: string;
  name: string;
  voice_id: string;
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
}

export interface VoiceState {
  supported: boolean;
  vad: string;
  vad_enabled: boolean;
  ptt: boolean;
  tts: string;
  asr_partial: string;
  error: string | null;
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
  busy: boolean;
  approvals: PendingApproval[];
  voice: VoiceState;
  pair: PairRecord;
  sequence: number;
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
  | "account.list"
  | "account.register"
  | "account.login"
  | "account.logout"
  | "account.switch"
  | "account.update_profile"
  | "account.change_password"
  | "config.get"
  | "config.set"
  | "config.test_connection"
  | "codex.oauth_start"
  | "codex.oauth_status"
  | "codex.logout"
  | "codex.api_login";

export interface DesktopCommand {
  kind: "request";
  id: string;
  method: DesktopCommandMethod;
  params: Record<string, unknown>;
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
  | "turn.completed"
  | "queue.changed"
  | "task.busy_changed"
  | "conversation.changed"
  | "project.changed"
  | "account.changed"
  | "config.changed"
  | "voice.asr_partial"
  | "voice.state_changed"
  | "connection.status"
  | "connection.restored"
  | "error.reported";

export interface DesktopEvent<T = Record<string, unknown>> {
  kind: "event";
  event: DesktopEventName;
  sequence: number;
  payload: T;
}

export interface MessageDeltaPayload {
  message_id: string;
  conversation_id: string;
  source: "assistant" | "character";
  kind: string;
  delta: string;
  task_id?: string;
  channel?: string;
}
