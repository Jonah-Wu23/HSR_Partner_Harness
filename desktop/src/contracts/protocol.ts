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

export interface DesktopSnapshot {
  projects: ProjectRecord[];
  current_project_id: string;
  current_conversation_id: string;
  current_project: Omit<ProjectRecord, "conversations">;
  current_conversation: ConversationRecord;
  messages: Message[];
  tool_runs: ToolRun[];
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
  | "project.create"
  | "project.select"
  | "project.update_settings"
  | "project.archive"
  | "conversation.create"
  | "conversation.select"
  | "conversation.rename"
  | "conversation.archive"
  | "chat.submit"
  | "task.cancel"
  | "approval.resolve"
  | "voice.vad_set"
  | "voice.ptt_start"
  | "voice.ptt_stop"
  | "voice.tts_stop";

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
  | "message.delta"
  | "message.finalized"
  | "tool_run.upserted"
  | "approval.requested"
  | "approval.resolved"
  | "task.busy_changed"
  | "conversation.changed"
  | "project.changed"
  | "voice.asr_partial"
  | "voice.state_changed"
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
