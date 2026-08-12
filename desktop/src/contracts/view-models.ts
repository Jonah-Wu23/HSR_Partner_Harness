import type {
  ActiveTask,
  ApprovalMode,
  ConversationRecord,
  Message,
  PairRecord,
  PendingApproval,
  ProjectRecord,
  ToolRun,
  VoiceState,
} from "./protocol";

export interface ProjectViewModel extends ProjectRecord {
  isCurrent: boolean;
  isBusy: boolean;
}

export interface ConversationViewModel extends ConversationRecord {
  isCurrent: boolean;
  isTaskOrigin: boolean;
}

export interface NavigationViewModel {
  projects: ProjectViewModel[];
  currentProjectId: string;
  currentConversationId: string;
  currentPair: PairRecord;
}

export interface ConversationTimelineViewModel {
  conversationId: string;
  messages: Message[];
  isStreaming: boolean;
}

export interface AssistantWorkbenchViewModel {
  conversationId: string;
  messages: Message[];
  toolRuns: ToolRun[];
  busy: boolean;
  activeTask: ActiveTask | null;
}

export interface WorkspaceViewModel {
  mode: "chat" | "collaboration";
  character: ConversationTimelineViewModel;
  assistant: AssistantWorkbenchViewModel;
}

export interface ComposerViewModel {
  target: "character" | "assistant";
  draft: string;
  enabled: boolean;
  approvalMode: ApprovalMode;
  reasoningEffort: string;
  asrPartial: string;
}

export interface ApprovalViewModel {
  mode: ApprovalMode;
  pending: Array<PendingApproval & { resolving: boolean }>;
  reviewActive: boolean;
  reviewText: string | null;
}

export interface VoiceViewModel extends VoiceState {
  canPushToTalk: boolean;
}

export interface AppShellViewModel {
  status: "booting" | "ready" | "disconnected" | "error";
  theme: "dark" | "light";
  navigation: NavigationViewModel | null;
  workspace: WorkspaceViewModel | null;
  composer: ComposerViewModel;
  approval: ApprovalViewModel;
  voice: VoiceViewModel;
  error: string | null;
}
