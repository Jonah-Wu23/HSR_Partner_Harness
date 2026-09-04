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
  /* —— V0.3.3 角色卡（card.* 命令）—— */
  /** 拉取角色卡列表写入 store.characterLibrary（含归档差集标记）；失败写入 slice.error。 */
  listCards(): Promise<void>;
  /** 打开角色库视图并触发 listCards。 */
  openCharacterLibrary(): Promise<void>;
  /** 打开角色创作视图；cardId 非空时经 card.get 载入该卡（只读卡 readOnly=true）。 */
  openCharacterCreate(cardId?: string): Promise<void>;
  /** 返回聊天工作区视图。 */
  openChat(): void;
  /** 创建最小草稿，返回 card_id；同时记为创作页当前草稿。 */
  createCardDraft(name: string): Promise<string>;
  /** 以完整 v3 JSON 覆盖保存角色卡。 */
  updateCard(cardId: string, card: Record<string, unknown>): Promise<void>;
  duplicateCard(cardId: string): Promise<void>;
  archiveCard(cardId: string): Promise<void>;
  /** 删除角色卡；页面确认后才允许调用（confirm=true 固定由本方法携带）。 */
  deleteCard(cardId: string): Promise<void>;
  selectActiveCard(cardId: string): Promise<void>;
  /** 只读拉取一张卡的完整 v3 JSON（含 avatar 与 hsr 扩展），不切视图、不写 store。 */
  cardGet(cardId: string): Promise<import("./protocol").CardGetResult>;
  /* —— V0.3.5 角色卡导入导出/发布/头像 —— */
  /** 预览本地 JSON 角色卡，不落库；失败抛错。 */
  cardPeekImportJson(path: string): Promise<import("./protocol").CardPeekImportResult>;
  /** 导入本地 JSON 角色卡；asDuplicate=true 时名称追加「（副本）」。 */
  cardImportJson(path: string, asDuplicate?: boolean): Promise<import("./protocol").CardImportJsonResult>;
  /** 导出角色卡 v3 JSON 到 path；saveAvatar=true 时配套另存头像。 */
  cardExportJson(cardId: string, path: string, saveAvatar?: boolean): Promise<import("./protocol").CardExportJsonResult>;
  /** 发布草稿卡（draft → saved）；非 draft 幂等成功。 */
  cardPublish(cardId: string): Promise<import("./protocol").CardPublishResult>;
  /** 为角色卡设置头像；成功后更新 store 中该卡头像。 */
  cardSetAvatar(cardId: string, path: string): Promise<import("./protocol").CardSetAvatarResult>;
  /** 移除角色卡头像。 */
  cardRemoveAvatar(cardId: string): Promise<import("./protocol").CardRemoveAvatarResult>;
  /* —— V0.3.7 PNG 导入导出/电源状态 —— */
  /** 预览本地角色卡（JSON/PNG 按文件签名自动分派），不落库；失败抛错。 */
  cardPeekImport(path: string): Promise<import("./protocol").CardPeekImportResult>;
  /** 导入本地 PNG 角色卡（PNG 字节即头像）；asDuplicate=true 时名称追加「（副本）」。 */
  cardImportPng(path: string, asDuplicate?: boolean): Promise<import("./protocol").CardImportPngResult>;
  /** 导出角色卡为 PNG（含头像图像块）；卡无头像时后端以 card_export_failed 拒绝。 */
  cardExportPng(cardId: string, path: string): Promise<import("./protocol").CardExportPngResult>;
  /** 读取电源状态；非 Windows 平台如实返回 supported=false，不抛错。 */
  powerGetStatus(): Promise<import("./protocol").PowerStatusPayload>;
  /* —— V0.3.5 角色卡音色 —— */
  /** 为角色卡绑定参考音频；不改变音色状态。 */
  voiceCardBindReference(cardId: string, path: string): Promise<import("./protocol").VoiceCardBindReferenceResult>;
  /** 为角色卡创建音色（clone/design）；成功后监听 voice.card_provision_changed 事件。
      design 模式必填 voicePrompt；previewText 为 design 可选试听文本，
      缺省时服务端使用固定默认文本（契约冻结 §3.2，与 _voice_provision design 路径同源）。 */
  voiceCardCreate(
    cardId: string,
    mode: "clone" | "design",
    opts?: { prefix?: string; voicePrompt?: string; previewText?: string },
  ): Promise<import("./protocol").VoiceCardCreateResult>;
  /** 解绑角色卡音色。 */
  voiceCardUnbind(cardId: string): Promise<import("./protocol").VoiceCardUnbindResult>;
  /** 用角色卡绑定音色试听；未就绪时报错。 */
  voiceCardPreview(cardId: string, text?: string): Promise<void>;
  /* —— V0.3.5 手机远程语音 —— */
  /** 手机端开始 Push-to-Talk 转写会话。 */
  voiceMobilePttStart(conversationId: string): Promise<import("./protocol").VoiceMobilePttStartResult>;
  /** 手机端上传音频分片；seq 从 0 严格递增。 */
  voiceMobileAudioChunk(sessionId: string, seq: number, dataBase64: string): Promise<void>;
  /** 手机端结束 Push-to-Talk 并获取最终转写。 */
  voiceMobilePttStop(sessionId: string): Promise<import("./protocol").VoiceMobilePttStopResult>;
  /** 手机端中断当前 TTS 播放。 */
  voiceMobileTtsStop(messageId: string): Promise<void>;
  /* —— V0.3.3 手机远程配对（remote.* 命令）—— */
  /** 生成一次性短期配对码，写入 store.remotePairing。 */
  issuePairingCode(): Promise<void>;
  listRemoteDevices(): Promise<void>;
  /** 按设备名撤销其全部 token 并刷新设备列表。 */
  revokeRemoteDevice(deviceName: string): Promise<void>;
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
