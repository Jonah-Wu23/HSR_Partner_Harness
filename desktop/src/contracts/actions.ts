import type { ApprovalMode, PairMemory, ReasoningEffort } from "./protocol";

/** config.test_connection 的连通结论与说明原文。 */
export interface ConnectionTestResult {
  ok: boolean;
  message: string;
}

/** chat.submit 的真实返回：快速接受时 status=received，忙碌入队时 queued=true。 */
export interface SubmitMessageResult {
  message_id?: string;
  conversation_id?: string;
  status?: string;
  queued?: boolean;
  turn_id?: string;
}

export interface HarnessActions {
  /** 选择文件夹并创建项目；用户取消文件夹对话框时返回 false。 */
  createProject(rootPath?: string, name?: string): Promise<boolean>;
  renameProject(projectId: string, name: string): Promise<void>;
  repairProjectPath(projectId: string): Promise<void>;
  selectProject(projectId: string): Promise<void>;
  archiveProject(projectId: string): Promise<void>;
  /** 创建聊天。bindingId 是配对目录里的绑定项（内置项为 `builtin:<pair_id>`，卡项为绑定 id），
      省略表示使用内置搭档。opts.reuseActive=true 时下发 reuse_active，「使用该角色」类入口
      复用同项目同绑定的活跃会话；「新建聊天」按钮不传，总是新建。 */
  createConversation(
    projectId?: string,
    title?: string,
    bindingId?: string,
    opts?: { reuseActive?: boolean },
  ): Promise<void>;
  /** 「使用该角色」入口：从最新配对目录按 character_card_id 找到绑定项并按它创建会话；
      目录中没有该卡的绑定项（草稿、已归档或尚未生效）时如实报错，不静默回退。
      会话创建成功后再把该卡标记为角色库「使用中」（card.select_active），该标记不参与身份解析。 */
  startConversationWithCard(cardId: string, opts?: { reuseActive?: boolean }): Promise<void>;
  /** 重取权威搭档目录（pair.list）写入 store；版本不新于本地已存版本时丢弃响应。 */
  refreshPairCatalog(): Promise<void>;
  /** 读取角色卡头像，返回 `data:<mime>;base64,<...>` 数据地址；卡没有头像时返回 null。
      按 cardId + avatarVersion 做内存缓存，头像变更后旧条目不再命中。 */
  fetchCardAvatar(cardId: string, avatarVersion: string | null): Promise<string | null>;
  selectConversation(conversationId: string): Promise<void>;
  /** 打开或聚焦本窗口聊天标签，经只读 conversation.open 装载，不改 Sidecar 全局导航。 */
  openConversationTab(conversationId: string): Promise<void>;
  /** 关闭本窗口聊天标签：只移除视图，不取消任务、不关闭会话；相邻标签接替为当前聊天。 */
  closeConversationTab(conversationId: string): void;
  /** 在新的 Tauri 窗口打开一份聊天视图。 */
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
  /** 定向取消：携带本窗口当前聊天的 conversation_id 与其活动任务 task_id。 */
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
  /** 测试对话服务连接；ok 是服务端给出的连通结论，message 是说明原文。 */
  testConnection(): Promise<ConnectionTestResult>;
  /** 本地 Toast 关闭（不经过后端）。 */
  dismissToast(id: string): void;
  /** 试听音色：text 为试听文本，voiceId 缺省时用角色音色。 */
  voicePreview(text: string, voiceId?: string): Promise<void>;
  /** 在当前账号的百炼下生成专属音色。speakerIds 缺省表示全部缺失项；
      replaceExisting=true 用于显式重新生成。 */
  provisionVoices(speakerIds?: string[], replaceExisting?: boolean): Promise<VoiceProvisionResult>;
  /** 拉取角色卡列表（含已归档）写入 store.characterLibrary；失败写入其 error。 */
  listCards(): Promise<void>;
  /** 打开角色库视图并触发 listCards。 */
  openCharacterLibrary(): Promise<void>;
  /** 打开角色创作视图；cardId 非空时经 card.get 载入该卡（只读卡 readOnly=true）。 */
  openCharacterCreate(cardId?: string): Promise<void>;
  /** 返回聊天工作区视图。 */
  openChat(): void;
  /** 创建最小草稿，返回 card_id（由创作页持有）。 */
  createCardDraft(name: string): Promise<string>;
  /** 以完整 v3 JSON 覆盖保存角色卡。 */
  updateCard(cardId: string, card: Record<string, unknown>): Promise<void>;
  duplicateCard(cardId: string): Promise<void>;
  archiveCard(cardId: string): Promise<void>;
  /** 把已归档的角色卡恢复到角色库（card.unarchive）。 */
  unarchiveCard(cardId: string): Promise<void>;
  /** 删除角色卡；页面确认后才允许调用（confirm=true 固定由本方法携带）。 */
  deleteCard(cardId: string): Promise<void>;
  selectActiveCard(cardId: string): Promise<void>;
  /** 只读拉取一张卡的完整 v3 JSON（含 avatar 与 hsr 扩展），不切视图、不写 store。 */
  cardGet(cardId: string): Promise<import("./protocol").CardGetResult>;
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
  /** 预览本地角色卡（JSON 与 PNG 按文件签名分派），不落库；失败抛错。 */
  cardPeekImport(path: string): Promise<import("./protocol").CardPeekImportResult>;
  /** 导入本地 PNG 角色卡（PNG 字节即头像）；asDuplicate=true 时名称追加「（副本）」。 */
  cardImportPng(path: string, asDuplicate?: boolean): Promise<import("./protocol").CardImportPngResult>;
  /** 导出角色卡为 PNG（含头像图像块）；卡无头像时后端以 card_export_failed 拒绝。 */
  cardExportPng(cardId: string, path: string): Promise<import("./protocol").CardExportPngResult>;
  /** 读取电源状态；非 Windows 平台如实返回 supported=false，不抛错。 */
  powerGetStatus(): Promise<import("./protocol").PowerStatusPayload>;
  /** 为角色卡绑定参考音频；不改变音色状态。 */
  voiceCardBindReference(cardId: string, path: string): Promise<import("./protocol").VoiceCardBindReferenceResult>;
  /** 为角色卡创建音色（clone 或 design），进度经 voice.card_provision_changed 事件下发。
      design 模式必填 voicePrompt；previewText 缺省时服务端使用固定试听文本。 */
  voiceCardCreate(
    cardId: string,
    mode: "clone" | "design",
    opts?: { prefix?: string; voicePrompt?: string; previewText?: string },
  ): Promise<import("./protocol").VoiceCardCreateResult>;
  /** 解绑角色卡音色。 */
  voiceCardUnbind(cardId: string): Promise<import("./protocol").VoiceCardUnbindResult>;
  /** 用角色卡绑定音色试听；未就绪时报错。 */
  voiceCardPreview(cardId: string, text?: string): Promise<void>;
  /** 手机端开始 Push-to-Talk 转写会话。 */
  voiceMobilePttStart(conversationId: string): Promise<import("./protocol").VoiceMobilePttStartResult>;
  /** 手机端上传音频分片；seq 从 0 严格递增。 */
  voiceMobileAudioChunk(sessionId: string, seq: number, dataBase64: string): Promise<void>;
  /** 手机端结束 Push-to-Talk 并获取最终转写。 */
  voiceMobilePttStop(sessionId: string): Promise<import("./protocol").VoiceMobilePttStopResult>;
  /** 手机端中断当前 TTS 播放。 */
  voiceMobileTtsStop(messageId: string): Promise<void>;
  /** 生成一次性短期配对码，写入 store.remotePairing。 */
  issuePairingCode(): Promise<void>;
  listRemoteDevices(): Promise<void>;
  /** 按设备名撤销其全部 token 并刷新设备列表。 */
  revokeRemoteDevice(deviceName: string): Promise<void>;
  /** 开启 Cloudflare Quick Tunnel 公网隧道。 */
  tunnelStart(): Promise<void>;
  tunnelStop(): Promise<void>;
  queryTunnelStatus(): Promise<void>;
  /** 重新生成摘要（summary.regenerate），调用配置的模型。 */
  regenerateSummary(summaryId: string, conversationId: string): Promise<void>;
  /** 只读查询回合指标（metrics.query）。 */
  queryMetrics(params?: {
    conversation_id?: string;
    cursor?: string | null;
    limit?: number;
    account_id?: string;
    project_id?: string;
    pair_id?: string;
    status?: string;
  }): Promise<{ metrics: import("./protocol").TurnMetric[]; next_cursor: string | null }>;
  /** 只读查询提示词装配诊断（diagnostics.prompt_assembly）；includeHidden=true 时返回隐藏原文。 */
  queryPromptAssembly(params?: {
    conversation_id?: string;
    includeHidden?: boolean;
  }): Promise<import("./view-models").PromptAssemblyView>;
  /** 读取指定会话（缺省为本窗口当前聊天）作用域内的记忆；作用域由服务端按会话解析，
      客户端只传 conversation_id。 */
  listMemories(opts?: {
    conversationId?: string | null;
    status?: "active" | "deleted";
  }): Promise<PairMemory[]>;
  /** 在指定会话的作用域内新增一条记忆（memory.create）；content 是 JSON 对象，代码不改写。 */
  createMemory(
    content: Record<string, unknown>,
    opts?: { conversationId?: string | null },
  ): Promise<PairMemory>;
  /** 改写一条记忆的内容（memory.update）；越作用域时服务端报错。 */
  updateMemory(
    memoryId: string,
    content: Record<string, unknown>,
    opts?: { conversationId?: string | null },
  ): Promise<PairMemory>;
  /** 软删除一条记忆（memory.delete），返回服务端落库后的记录。 */
  deleteMemory(
    memoryId: string,
    opts?: { conversationId?: string | null },
  ): Promise<PairMemory>;
}

/** voice.provision 的返回：completed 或 partial_failed 加每项结果。 */
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
