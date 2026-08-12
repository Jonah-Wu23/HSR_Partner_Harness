import type { ApprovalMode, ReasoningEffort } from "./protocol";

export interface HarnessActions {
  createProject(rootPath?: string, name?: string): Promise<void>;
  renameProject(projectId: string, name: string): Promise<void>;
  repairProjectPath(projectId: string): Promise<void>;
  selectProject(projectId: string): Promise<void>;
  createConversation(projectId?: string, title?: string): Promise<void>;
  selectConversation(conversationId: string): Promise<void>;
  renameConversation(conversationId: string, title: string): Promise<void>;
  archiveConversation(conversationId: string): Promise<void>;
  switchMode(mode: "chat" | "collaboration"): void;
  switchTheme(theme: "dark" | "light"): void;
  submitMessage(text: string, target?: "character" | "assistant"): Promise<void>;
  cancelTask(): Promise<void>;
  resolveApproval(approvalId: string, decision: string): Promise<void>;
  setApprovalMode(mode: ApprovalMode): Promise<void>;
  setReasoningEffort(effort: ReasoningEffort): Promise<void>;
  setVadEnabled(enabled: boolean): Promise<void>;
  startPushToTalk(target?: "character" | "assistant"): Promise<void>;
  stopPushToTalk(): Promise<void>;
  stopSpeech(): Promise<void>;
}
