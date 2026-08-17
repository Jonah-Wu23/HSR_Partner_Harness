import type { ApprovalMode, ReasoningEffort } from "./protocol";

/** chat.submit 的真实返回：快速接受时 status=received，忙碌入队时 queued=true。 */
export interface SubmitMessageResult {
  message_id?: string;
  conversation_id?: string;
  status?: string;
  queued?: boolean;
  turn_id?: string;
}

export interface CodexOAuthStatus {
  status: string;
  account_label?: string | null;
}

export interface HarnessActions {
  /** 选择文件夹并创建项目；用户取消文件夹对话框时返回 false。 */
  createProject(rootPath?: string, name?: string): Promise<boolean>;
  renameProject(projectId: string, name: string): Promise<void>;
  repairProjectPath(projectId: string): Promise<void>;
  selectProject(projectId: string): Promise<void>;
  archiveProject(projectId: string): Promise<void>;
  createConversation(projectId?: string, title?: string, pairId?: string): Promise<void>;
  selectConversation(conversationId: string): Promise<void>;
  /** V0.3.2 M5：打开（或聚焦）本窗口聊天标签；同时把本窗口当前聊天切到该会话
      （使用只读 conversation.open，不改 Sidecar 全局导航）。 */
  openConversationTab(conversationId: string): Promise<void>;
  /** V0.3.2 M5：关闭本窗口聊天标签——只移除视图，不取消任务、不关闭会话；
      关闭活动标签后相邻标签接替为本窗口当前聊天。 */
  closeConversationTab(conversationId: string): void;
  /** V0.3.2 M5：在新的 Tauri 窗口打开一份聊天视图。 */
  openConversationWindow(conversationId: string): Promise<void>;
  renameConversation(conversationId: string, title: string): Promise<void>;
  archiveConversation(conversationId: string): Promise<void>;
  switchMode(mode: "chat" | "collaboration"): Promise<void>;
  switchTheme(theme: "dark" | "light"): void;
  submitMessage(
    text: string,
    target?: "character" | "assistant",
    intent?: "followup" | "steer",
  ): Promise<SubmitMessageResult>;
  editQueueItem(queueItemId: string, text: string): Promise<void>;
  withdrawQueueItem(queueItemId: string): Promise<void>;
  prioritizeQueueItem(queueItemId: string): Promise<void>;
  /** 队列条「编辑」：撤回该项并返回原文（拉回输入区用）；不存在返回 null。 */
  editQueueFromStrip(queueItemId: string): Promise<string | null>;
  /** V0.3.2 M5：定向取消——携带本窗口当前聊天 conversation_id 与其活动任务 task_id。 */
  cancelTask(): Promise<void>;
  resolveApproval(approvalId: string, decision: string): Promise<void>;
  setApprovalMode(mode: ApprovalMode): Promise<void>;
  setReasoningEffort(effort: ReasoningEffort): Promise<void>;
  setVadEnabled(enabled: boolean): Promise<void>;
  startPushToTalk(target?: "character" | "assistant"): Promise<void>;
  stopPushToTalk(): Promise<void>;
  stopSpeech(): Promise<void>;
  /** 跳过当前朗读，播放下一条（voice.tts_skip）。 */
  skipSpeech(): Promise<void>;
  /** 立即重连本地服务（Sidecar 断开时由 Rust 侧强制重启并重置退避）。 */
  reconnect(): Promise<void>;
  listAccounts(): Promise<void>;
  registerAccount(username: string, displayName: string, password: string): Promise<void>;
  loginAccount(accountId: string, password: string): Promise<void>;
  logoutAccount(): Promise<void>;
  updateAccountProfile(displayName?: string, avatar?: string): Promise<void>;
  changePassword(oldPassword: string, newPassword: string): Promise<void>;
  /** 首次引导完成：置 onboarding_complete 并广播 account.changed。 */
  completeOnboarding(): Promise<void>;
  getConfig(): Promise<void>;
  setConfig(updates: Record<string, string>): Promise<void>;
  /** 测试对话服务连接；返回人话结果（如「连接正常（延迟 12 ms）」「Key 无效…」）。 */
  testConnection(): Promise<string>;
  /** 本地 Toast 关闭（不经过后端）。 */
  dismissToast(id: string): void;
  codexOauthStart(): Promise<void>;
  /** 查询 Codex OAuth 登录状态（供首次引导/设置页轮询）。 */
  codexOauthStatus(): Promise<CodexOAuthStatus>;
  codexApiLogin(apiKey: string): Promise<void>;
  codexLogout(): Promise<void>;
  /** 试听音色：text 试听文本，voiceId 缺省/非当前有效音色时用角色音色；
      V0.3.2 M6 音色来自当前账号生成结果（或开发机作者 Key）。 */
  voicePreview(text: string, voiceId?: string): Promise<void>;
  /** V0.3.2 M6：在当前账号的百炼下生成专属音色（5 复刻 + 1 设计）。
      speakerIds 缺省表示全部缺失项；replaceExisting=true 用于显式重新生成。 */
  provisionVoices(speakerIds?: string[], replaceExisting?: boolean): Promise<VoiceProvisionResult>;
}

/** voice.provision 的真实返回：completed 或 partial_failed + 每项结果。 */
export interface VoiceProvisionResult {
  status?: "completed" | "partial_failed" | string;
  completed?: number;
  total?: number;
  results?: Array<{
    speaker_id: string;
    state: string;
    voice_id?: string | null;
    error?: string | null;
  }>;
}
