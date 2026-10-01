import type {
  HarnessActions,
  SubmitMessageResult,
  VoiceProvisionResult,
} from "../contracts/actions";
import type {
  ApprovalMode,
  CardArchiveResult,
  CardCreateDraftResult,
  CardDeleteResult,
  CardDuplicateResult,
  CardExportJsonResult,
  CardExportPngResult,
  CardGetResult,
  CardImportJsonResult,
  CardImportPngResult,
  CardListResult,
  CardPeekImportResult,
  CardPublishResult,
  CardRemoveAvatarResult,
  CardSetAvatarResult,
  CardUpdateResult,
  ConfigTestConnectionResult,
  ConversationCreateResult,
  ConversationOpenResult,
  DesktopCommand,
  DesktopCommandMethod,
  DesktopSnapshot,
  DesktopStreamEvent,
  ReasoningEffort,
  PowerStatusPayload,
  RemoteIssueCodeResult,
  RemoteListDevicesResult,
  RemoteRevokeResult,
  RemoteTunnelStartResult,
  RemoteTunnelStopResult,
  RemoteTunnelStatusResult,
  TaskCancelResult,
  VoiceCardBindReferenceResult,
  VoiceCardCreateResult,
  VoiceCardUnbindResult,
  VoiceMobilePttStartResult,
  VoiceMobilePttStopResult,
  MemoryListResult,
  MemoryWriteResult,
  PairMemory,
} from "../contracts/protocol";
import { pairMemoryFromPayload } from "../contracts/protocol";
import type { CharacterCardSummaryView, RemoteDeviceView } from "../contracts/view-models";
import type { DesktopBackend } from "./backend";
import { RequestIdFactory } from "./backend";
import { adaptMetricsQueryResult, adaptPromptAssembly } from "../ui/diagnostics/types";
import {
  desktopStore,
  selectComposerTarget,
  selectWindowConversationId,
  selectWindowProjectId,
} from "../stores/desktopStore";

export interface ActionController {
  actions: HarnessActions;
  loadBootstrap(): Promise<void>;
  /** conversation.open 只读装载指定聊天并打开其标签，不改全局当前聊天。 */
  conversationOpen(conversationId: string): Promise<void>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function createActionController(backend: DesktopBackend): ActionController {
  // 请求 id 携带本窗口 viewId，多窗口之间全应用唯一。
  const ids = new RequestIdFactory(() => desktopStore.getState().viewId);
  let conversationOpenGeneration = 0;

  /** 请求失败统一推送带原始错误的 Toast，错误继续抛给调用方。
      timeoutSecs 缺省用后端默认上限，null 表示一直等到 Sidecar 回复或断开。 */
  async function request<T>(
    method: DesktopCommandMethod,
    params: Record<string, unknown> = {},
    timeoutSecs?: number | null,
  ): Promise<T> {
    const command: DesktopCommand = {
      kind: "request",
      id: ids.next(),
      method,
      params,
      view_id: desktopStore.getState().viewId,
    };
    try {
      return await backend.request<T>(command, timeoutSecs);
    } catch (error) {
      const message = errorMessage(error);
      desktopStore.getState().pushToast({
        id: `request-failed:${method}:${message}`,
        kind: "error",
        text: `${method} 失败：${message}`,
        hasDetails: true,
      });
      throw error;
    }
  }

  /** 返回 bootstrap 快照的命令：结果直接水合。 */
  async function requestSnapshot<T extends DesktopSnapshot = DesktopSnapshot>(
    method: DesktopCommandMethod,
    params: Record<string, unknown> = {},
  ): Promise<T> {
    const snapshot = await request<T>(method, params);
    desktopStore.getState().hydrate(snapshot);
    return snapshot;
  }

  /** 发请求前的前置条件不满足：与请求失败一样推送 Toast 并抛出。 */
  function rejectAction(id: string, text: string): never {
    desktopStore.getState().pushToast({ id, kind: "error", text });
    throw new Error(text);
  }

  /** 记忆命令一律按会话下发，作用域由服务端解析；没有会话上下文时如实失败。 */
  function resolveMemoryConversationId(explicit?: string | null): string {
    const conversationId = explicit ?? selectWindowConversationId(desktopStore.getState());
    if (!conversationId) {
      throw new Error("没有当前聊天，无法解析长期记忆作用域（需要会话上下文）");
    }
    return conversationId;
  }

  /** 写命令返回体写入 store（与 memory.updated/deleted 事件同形，按 memory_id 幂等）。 */
  function recordMemoryWrite(result: MemoryWriteResult, conversationId: string): PairMemory {
    const memory = pairMemoryFromPayload(result.memory);
    desktopStore.getState().upsertMemory(memory, memory.conversation_id ?? conversationId);
    return memory;
  }

  // 序号缺口触发的重新同步不切到启动状态页：界面与输入区保持可用，直到快照水合。
  const loadBootstrap = async () => {
    if (!desktopStore.getState().resyncing) desktopStore.getState().setStatus("booting");
    try {
      await requestSnapshot("app.bootstrap");
    } catch (error) {
      desktopStore.getState().setStatus("error", errorMessage(error));
    }
  };

  // 只读装载指定聊天：参数携带本窗口 view_id；结果合并进各会话索引并打开该聊天的标签，
  // 不改变后端全局当前聊天。
  const conversationOpen = async (conversationId: string) => {
    const generation = ++conversationOpenGeneration;
    const requestAccountGeneration = desktopStore.getState().accountGeneration;
    const bufferedEvents: DesktopStreamEvent[] = [];
    const unsubscribe = backend.subscribe((event) => bufferedEvents.push(event));
    let result: ConversationOpenResult;
    try {
      result = await request<ConversationOpenResult>("conversation.open", {
        conversation_id: conversationId,
        view_id: desktopStore.getState().viewId,
      });
    } finally {
      unsubscribe();
    }
    if (
      generation !== conversationOpenGeneration ||
      requestAccountGeneration !== desktopStore.getState().accountGeneration
    ) return;
    desktopStore.getState().hydrateConversationView(result, bufferedEvents);
  };

  /** 后端选择/创建成功后，把本窗口焦点同步到新的当前聊天。 */
  const focusBackendConversation = () => {
    const conversationId = desktopStore.getState().currentConversationId;
    if (conversationId) desktopStore.getState().openConversationTab(conversationId);
  };

  const actions: HarnessActions = {
    async createProject(rootPath, name) {
      const selectedRoot = rootPath?.trim() || (await backend.pickFolder("选择项目文件夹"));
      if (!selectedRoot) return false;
      await requestSnapshot("project.create", { root_path: selectedRoot, name });
      focusBackendConversation();
      return true;
    },
    async renameProject(projectId, name) {
      await request("project.update_settings", { project_id: projectId, name });
    },
    async repairProjectPath(projectId) {
      const selectedRoot = await backend.pickFolder("重新选择项目文件夹");
      if (!selectedRoot) return;
      await request("project.update_settings", {
        project_id: projectId,
        root_path: selectedRoot,
      });
    },
    async selectProject(projectId) {
      await requestSnapshot("project.select", { project_id: projectId });
    },
    async archiveProject(projectId) {
      await requestSnapshot("project.archive", { project_id: projectId });
    },
    async createConversation(projectId, title, pairId, opts) {
      // 「使用该角色」类入口带 reuse_active 复用活跃会话；「新建聊天」按钮总是新建。
      await requestSnapshot<ConversationCreateResult>("conversation.create", {
        project_id: projectId,
        title,
        ...(pairId ? { pair_id: pairId } : {}),
        ...(opts?.reuseActive ? { reuse_active: true } : {}),
      });
      focusBackendConversation();
    },
    async selectConversation(conversationId) {
      await requestSnapshot("conversation.select", { conversation_id: conversationId });
      focusBackendConversation();
    },
    async openConversationTab(conversationId) {
      // 每次聚焦都重新读取该会话的权威快照，同时让共享的
      // 物理语音运行时切到该聊天；conversation.open 不改 Sidecar 全局导航。
      await conversationOpen(conversationId);
    },
    closeConversationTab(conversationId) {
      // 只移除本窗口标签；标签已有完整缓存，切到相邻标签不需要 conversation.select，
      // 也不取消任务或关闭会话。
      desktopStore.getState().closeConversationTab(conversationId);
    },
    async openConversationWindow(conversationId) {
      const conversation = desktopStore.getState().conversationsById[conversationId];
      try {
        await backend.openChatWindow(conversationId, conversation.title);
      } catch (error) {
        const message = errorMessage(error);
        desktopStore.getState().pushToast({
          id: `open-chat-window:${conversationId}:${message}`,
          kind: "error",
          text: `打开独立聊天窗口失败：${message}`,
          hasDetails: true,
        });
        throw error;
      }
    },
    async renameConversation(conversationId, title) {
      await requestSnapshot("conversation.rename", { conversation_id: conversationId, title });
    },
    async archiveConversation(conversationId) {
      await requestSnapshot("conversation.archive", { conversation_id: conversationId });
    },
    async switchMode(mode) {
      // 模式按会话持久化在 last_mode；界面模式随后由 conversation.changed 更新。
      const conversationId = selectWindowConversationId(desktopStore.getState());
      if (!conversationId) {
        rejectAction("mode:no-conversation", "当前窗口没有打开的聊天，无法切换模式");
      }
      await request("conversation.set_mode", { conversation_id: conversationId, mode });
    },
    switchTheme(theme) {
      if (typeof window !== "undefined") window.localStorage.setItem("pair-harness-theme", theme);
      desktopStore.getState().setTheme(theme);
    },
    async submitMessage(text, target, intent) {
      const state = desktopStore.getState();
      const actualTarget = target ?? selectComposerTarget(state);
      // 草稿由 Composer 在收到 accepted/queued 回执后清除，请求失败时输入保留。
      // 消息提交到本窗口活动标签的聊天；模式只经 switchMode 修改。
      return request<SubmitMessageResult>("chat.submit", {
        conversation_id: selectWindowConversationId(state),
        target: actualTarget,
        text,
        ...(intent ? { intent } : {}),
      });
    },
    async editQueueItem(queueItemId, text) {
      await request("queue.edit", { queue_item_id: queueItemId, text });
    },
    async withdrawQueueItem(queueItemId) {
      await request("queue.withdraw", { queue_item_id: queueItemId });
    },
    async editQueueFromStrip(queueItemId) {
      // 队列条「编辑」：撤回该项并返回原文，拉回输入区。
      const state = desktopStore.getState();
      const conversationId = selectWindowConversationId(state);
      if (!conversationId) return null;
      const item = (state.queueItemsByConversation[conversationId] ?? []).find(
        (candidate) => candidate.queue_item_id === queueItemId,
      );
      if (!item || item.status !== "queued") return null;
      await this.withdrawQueueItem(queueItemId);
      return item.text;
    },
    async prioritizeQueueItem(queueItemId) {
      await request("queue.prioritize", { queue_item_id: queueItemId });
    },
    async cancelTask() {
      // 定向取消携带本窗口聊天的 conversation_id 与其活动任务的 task_id。
      // cancelled=false 表示服务端没有取消任何任务，如实提示。
      const state = desktopStore.getState();
      const conversationId = selectWindowConversationId(state);
      const activeTask = conversationId
        ? state.activeTasksByConversation[conversationId]
        : undefined;
      if (!conversationId || !activeTask) {
        rejectAction("task-cancel:no-task", "当前聊天没有可取消的活动任务");
      }
      const result = await request<TaskCancelResult>("task.cancel", {
        conversation_id: conversationId,
        task_id: activeTask.task_id,
      });
      if (!result.cancelled) {
        desktopStore.getState().pushToast({
          id: `task-cancel:not-cancelled:${activeTask.task_id}`,
          kind: "warning",
          text: `取消未生效：服务端没有取消任务 ${activeTask.task_id}`,
        });
      }
    },
    async resolveApproval(approvalId, decision) {
      const state = desktopStore.getState();
      if (state.approvalResolvingById[approvalId]) return;
      state.setApprovalResolving(approvalId, true);
      try {
        await request("approval.resolve", { approval_id: approvalId, decision });
      } catch (error) {
        desktopStore.getState().setApprovalResolving(approvalId, false);
        throw error;
      }
    },
    async setApprovalMode(mode: ApprovalMode) {
      const projectId = selectWindowProjectId(desktopStore.getState());
      if (!projectId) rejectAction("approval-mode:no-project", "当前窗口没有项目上下文");
      await request("project.update_settings", { project_id: projectId, approval_mode: mode });
    },
    async setReasoningEffort(effort: ReasoningEffort) {
      const projectId = selectWindowProjectId(desktopStore.getState());
      if (!projectId) rejectAction("reasoning-effort:no-project", "当前窗口没有项目上下文");
      await request("project.update_settings", { project_id: projectId, reasoning_effort: effort });
    },
    async setVadEnabled(enabled) {
      await request("voice.vad_set", { enabled });
    },
    async startPushToTalk(target) {
      const state = desktopStore.getState();
      const conversationId = selectWindowConversationId(state);
      await request("voice.ptt_start", {
        target: target ?? selectComposerTarget(state),
        ...(conversationId ? { conversation_id: conversationId } : {}),
      });
    },
    async stopPushToTalk() {
      await request("voice.ptt_stop");
    },
    async stopSpeech() {
      await request("voice.tts_stop");
    },
    async skipSpeech() {
      await request("voice.tts_skip");
    },
    async reconnect() {
      // Rust 侧强制重启 Sidecar；成功后由 connection.status connected 驱动重新 bootstrap，
      // 失败时连接状态记为出错并显示原文。
      try {
        await backend.reconnectSidecar();
      } catch (error) {
        desktopStore.getState().setStatus("error", errorMessage(error));
      }
    },
    async listAccounts() {
      await request("account.list");
    },
    async registerAccount(username, displayName, password) {
      conversationOpenGeneration += 1;
      await request("account.register", { username, display_name: displayName, password });
      await loadBootstrap();
    },
    async loginAccount(accountId, password) {
      conversationOpenGeneration += 1;
      await request("account.login", { account_id: accountId, password });
      await loadBootstrap();
    },
    async logoutAccount() {
      conversationOpenGeneration += 1;
      await request("account.logout");
      await loadBootstrap();
    },
    async updateAccountProfile(displayName, avatar) {
      await request("account.update_profile", { display_name: displayName, avatar });
    },
    async changePassword(oldPassword, newPassword) {
      await request("account.change_password", {
        old_password: oldPassword,
        new_password: newPassword,
      });
    },
    async completeOnboarding() {
      await request("account.onboarding_complete");
    },
    async getConfig() {
      // 账号切换后迟到的结果不覆盖新账号的设置页数据。
      const accountGeneration = desktopStore.getState().accountGeneration;
      const result = await request<Record<string, unknown>>("config.get");
      if (accountGeneration === desktopStore.getState().accountGeneration) {
        desktopStore.getState().setConfigSnapshot(result);
      }
    },
    async setConfig(updates) {
      const accountGeneration = desktopStore.getState().accountGeneration;
      const result = await request<{ config: Record<string, unknown> }>("config.set", { updates });
      if (accountGeneration === desktopStore.getState().accountGeneration) {
        desktopStore.getState().setConfigSnapshot(result.config);
      }
    },
    async testConnection() {
      const result = await request<ConfigTestConnectionResult>("config.test_connection");
      return { ok: result.ok, message: result.message };
    },
    async voicePreview(text, voiceId) {
      await request("voice.preview", { text, ...(voiceId ? { voice_id: voiceId } : {}) });
    },
    async provisionVoices(speakerIds, replaceExisting) {
      const accountGeneration = desktopStore.getState().accountGeneration;
      const params: Record<string, unknown> = {};
      if (speakerIds !== undefined) params.speaker_ids = speakerIds;
      if (replaceExisting !== undefined) params.replace_existing = replaceExisting;
      // 逐个生成音色耗时不定，一直等到 Sidecar 回复或断开。
      const result = await request<VoiceProvisionResult>("voice.provision", params, null);
      // 逐项事件用于实时状态；命令完成后再取一次配置，成功项从库里水合到设置页，
      // 失败项保留原状态。
      const config = await request<Record<string, unknown>>("config.get");
      if (accountGeneration === desktopStore.getState().accountGeneration) {
        desktopStore.getState().setConfigSnapshot(config);
      }
      return result;
    },
    async listCards() {
      desktopStore.getState().setCharacterLibrary({ loading: true, error: null });
      try {
        const result = await request<CardListResult>("card.list", { include_archived: true });
        const cards: CharacterCardSummaryView[] = result.cards.map((card) => ({
          cardId: card.card_id,
          name: card.name,
          state: card.state,
          source: card.source,
          updatedAt: card.updated_at,
          hasAvatar: card.has_avatar,
          voiceState: card.voice_state,
          active: card.active,
          readOnly: card.read_only,
          archived: card.archived,
        }));
        desktopStore.getState().setCharacterLibrary({ cards, loading: false, loaded: true });
      } catch (error) {
        desktopStore
          .getState()
          .setCharacterLibrary({ loading: false, error: errorMessage(error), loaded: true });
      }
    },
    async openCharacterLibrary() {
      desktopStore.getState().setMainView("characters");
      await this.listCards();
    },
    async openCharacterCreate(cardId) {
      desktopStore.getState().setMainView("characterCreate");
      if (!cardId) {
        desktopStore.getState().setCharacterCreate({
          cardId: null,
          card: null,
          readOnly: false,
          loading: false,
          error: null,
        });
        return;
      }
      // 先清空再载入：重新打开同一张卡时 cardId 也会变化一次，创作页据此用最新内容水合。
      desktopStore.getState().setCharacterCreate({
        cardId: null,
        card: null,
        readOnly: false,
        loading: true,
        error: null,
      });
      try {
        const result = await request<CardGetResult>("card.get", { card_id: cardId });
        desktopStore.getState().setCharacterCreate({
          cardId: result.card_id,
          card: result.card,
          readOnly: result.read_only,
          loading: false,
        });
      } catch (error) {
        desktopStore.getState().setCharacterCreate({ loading: false, error: errorMessage(error) });
      }
    },
    openChat() {
      desktopStore.getState().setMainView("chat");
    },
    async createCardDraft(name) {
      // 草稿 id 由创作页自己持有；store 的 cardId 只表示经 openCharacterCreate 打开的卡，
      // 创作页只在它变化时重新水合表单。
      const result = await request<CardCreateDraftResult>("card.create_draft", { name });
      return result.card_id;
    },
    async updateCard(cardId, card) {
      await request<CardUpdateResult>("card.update", { card_id: cardId, card });
    },
    async duplicateCard(cardId) {
      await request<CardDuplicateResult>("card.duplicate", { card_id: cardId });
      await this.listCards();
    },
    async archiveCard(cardId) {
      await request<CardArchiveResult>("card.archive", { card_id: cardId });
      await this.listCards();
    },
    async unarchiveCard(cardId) {
      await request<CardArchiveResult>("card.unarchive", { card_id: cardId });
      await this.listCards();
    },
    async deleteCard(cardId) {
      await request<CardDeleteResult>("card.delete", { card_id: cardId, confirm: true });
      await this.listCards();
    },
    async selectActiveCard(cardId) {
      await request("card.select_active", { card_id: cardId });
      await this.listCards();
    },
    async cardGet(cardId) {
      return request<CardGetResult>("card.get", { card_id: cardId });
    },
    async cardImportJson(path, asDuplicate) {
      const result = await request<CardImportJsonResult>("card.import_json", {
        path,
        as_duplicate: asDuplicate ?? false,
      });
      await this.listCards();
      return result;
    },
    async cardExportJson(cardId, path, saveAvatar) {
      return request<CardExportJsonResult>("card.export_json", {
        card_id: cardId,
        path,
        save_avatar: saveAvatar ?? true,
      });
    },
    async cardPublish(cardId) {
      const result = await request<CardPublishResult>("card.publish", { card_id: cardId });
      await this.listCards();
      return result;
    },
    // 头像由服务端写入卡的 avatar_asset；创作页经 card.get 刷新头像，
    // 这里只刷新角色库的 has_avatar。
    async cardSetAvatar(cardId, path) {
      const result = await request<CardSetAvatarResult>("card.set_avatar", { card_id: cardId, path });
      await this.listCards();
      return result;
    },
    async cardRemoveAvatar(cardId) {
      const result = await request<CardRemoveAvatarResult>("card.remove_avatar", { card_id: cardId });
      await this.listCards();
      return result;
    },
    async cardPeekImport(path) {
      return request<CardPeekImportResult>("card.peek_import", { path });
    },
    async cardImportPng(path, asDuplicate) {
      const result = await request<CardImportPngResult>("card.import_png", {
        path,
        as_duplicate: asDuplicate ?? false,
      });
      await this.listCards();
      return result;
    },
    async cardExportPng(cardId, path) {
      return request<CardExportPngResult>("card.export_png", { card_id: cardId, path });
    },
    async powerGetStatus() {
      return request<PowerStatusPayload>("power.get_status");
    },
    async voiceCardBindReference(cardId, path) {
      return request<VoiceCardBindReferenceResult>("voice.card_bind_reference", {
        card_id: cardId,
        path,
      });
    },
    async voiceCardCreate(cardId, mode, opts) {
      const result = await request<VoiceCardCreateResult>("voice.card_create", {
        card_id: cardId,
        mode,
        ...(opts?.prefix ? { prefix: opts.prefix } : {}),
        ...(opts?.voicePrompt ? { voice_prompt: opts.voicePrompt } : {}),
        ...(opts?.previewText ? { preview_text: opts.previewText } : {}),
      });
      await this.listCards();
      return result;
    },
    async voiceCardUnbind(cardId) {
      const result = await request<VoiceCardUnbindResult>("voice.card_unbind", { card_id: cardId });
      await this.listCards();
      return result;
    },
    async voiceCardPreview(cardId, text) {
      await request("voice.card_preview", { card_id: cardId, ...(text ? { text } : {}) });
    },
    async voiceMobilePttStart(conversationId) {
      return request<VoiceMobilePttStartResult>("voice.mobile_ptt_start", { conversation_id: conversationId });
    },
    async voiceMobileAudioChunk(sessionId, seq, dataBase64) {
      await request("voice.mobile_audio_chunk", { session_id: sessionId, seq, data: dataBase64 });
    },
    async voiceMobilePttStop(sessionId) {
      return request<VoiceMobilePttStopResult>("voice.mobile_ptt_stop", { session_id: sessionId });
    },
    async voiceMobileTtsStop(messageId) {
      await request("voice.mobile_tts_stop", { message_id: messageId });
    },
    async issuePairingCode() {
      desktopStore.getState().setRemotePairing({ loading: true, error: null });
      try {
        const result = await request<RemoteIssueCodeResult>("remote.issue_code");
        desktopStore.getState().setRemotePairing({
          code: result.code,
          ttlSeconds: result.ttl_seconds,
          issuedAtEpochMs: Date.now(),
          loading: false,
        });
        // 返回体带当前 serve 地址（与 serve.started 同形），错过启动时的一次性事件也能出二维码。
        desktopStore.getState().setServeAddress(result.serve_address);
      } catch (error) {
        desktopStore.getState().setRemotePairing({ loading: false, error: errorMessage(error) });
      }
    },
    async listRemoteDevices() {
      desktopStore.getState().setRemotePairing({ loading: true, error: null });
      try {
        const result = await request<RemoteListDevicesResult>("remote.list_devices");
        const devices: RemoteDeviceView[] = result.devices.map((device) => ({
          deviceName: device.device_name,
          issuedAt: device.issued_at,
          lastUsedAt: device.last_used_at,
          expiresAt: device.expires_at,
          revoked: device.revoked,
        }));
        desktopStore.getState().setRemotePairing({ devices, loading: false });
      } catch (error) {
        desktopStore.getState().setRemotePairing({ loading: false, error: errorMessage(error) });
      }
    },
    async revokeRemoteDevice(deviceName) {
      await request<RemoteRevokeResult>("remote.revoke", { device_name: deviceName });
      await this.listRemoteDevices();
    },
    async tunnelStart() {
      desktopStore.getState().setTunnelStarting();
      try {
        await request<RemoteTunnelStartResult>("remote.tunnel_start");
      } catch (error) {
        desktopStore.getState().setTunnelFailed(errorMessage(error));
        throw error;
      }
    },
    // 停止或查询失败只说明这次请求失败，隧道状态以 tunnel.* 事件与状态查询结果为准。
    async tunnelStop() {
      desktopStore.getState().setTunnelStopping();
      try {
        await request<RemoteTunnelStopResult>("remote.tunnel_stop");
      } catch (error) {
        desktopStore.getState().setTunnelRequestFailed(errorMessage(error));
        throw error;
      }
    },
    async queryTunnelStatus() {
      try {
        const result = await request<RemoteTunnelStatusResult>("remote.tunnel_status");
        desktopStore.getState().setTunnelStatus(result);
      } catch (error) {
        desktopStore.getState().setTunnelRequestFailed(errorMessage(error));
        throw error;
      }
    },
    async regenerateSummary(summaryId, conversationId) {
      // 服务端随后广播 summary.started 与终态事件，摘要状态由事件驱动。
      await request("summary.regenerate", { summary_id: summaryId, conversation_id: conversationId });
    },
    async queryMetrics(params) {
      desktopStore.getState().setMetricsLoading(true);
      try {
        const raw = await request<unknown>("metrics.query", {
          ...params,
          conversation_id: params?.conversation_id ?? selectWindowConversationId(desktopStore.getState()),
        });
        const result = adaptMetricsQueryResult(raw);
        // 不带 cursor 是首屏或刷新，整体替换；带 cursor 是加载更多，追加到已读结果之后。
        desktopStore.getState().setMetricsPage(
          { metrics: result.metrics, cursor: result.next_cursor },
          params?.cursor ? "append" : "replace",
        );
        return result;
      } catch (error) {
        desktopStore.getState().setMetricsError(errorMessage(error));
        throw error;
      }
    },
    async queryPromptAssembly(params) {
      // 概览结果进 store 供诊断抽屉渲染；带隐藏原文的结果只交给请求方，不留在 store。
      const includeHidden = params?.includeHidden === true;
      const store = desktopStore.getState();
      if (!includeHidden) store.setPromptAssemblyLoading(true);
      try {
        const raw = await request<unknown>("diagnostics.prompt_assembly", {
          conversation_id: params?.conversation_id ?? selectWindowConversationId(store),
          include_hidden: includeHidden,
        });
        const assembly = adaptPromptAssembly(raw);
        if (!includeHidden) desktopStore.getState().setPromptAssembly(assembly);
        return assembly;
      } catch (error) {
        if (!includeHidden) desktopStore.getState().setPromptAssemblyError(errorMessage(error));
        throw error;
      }
    },
    async listMemories(opts) {
      const conversationId = resolveMemoryConversationId(opts?.conversationId);
      desktopStore.getState().setMemoryPanel({ conversationId, loading: true, error: null });
      try {
        const result = await request<MemoryListResult>("memory.list", {
          conversation_id: conversationId,
          ...(opts?.status ? { status: opts.status } : {}),
        });
        const memories = result.memories.map(pairMemoryFromPayload);
        // 服务端已按该会话的作用域过滤；整批替换该聊天的条目。
        const store = desktopStore.getState();
        store.setMemoriesForConversation(conversationId, memories);
        if (store.activeConversationId === conversationId) store.setMemories(memories);
        desktopStore.getState().setMemoryPanel({ loading: false, error: null, loaded: true });
        return memories;
      } catch (error) {
        desktopStore
          .getState()
          .setMemoryPanel({ loading: false, error: errorMessage(error), loaded: true });
        throw error;
      }
    },
    async createMemory(content, opts) {
      const conversationId = resolveMemoryConversationId(opts?.conversationId);
      const result = await request<MemoryWriteResult>("memory.create", {
        conversation_id: conversationId,
        content,
      });
      return recordMemoryWrite(result, conversationId);
    },
    async updateMemory(memoryId, content, opts) {
      const conversationId = resolveMemoryConversationId(opts?.conversationId);
      const result = await request<MemoryWriteResult>("memory.update", {
        conversation_id: conversationId,
        memory_id: memoryId,
        content,
      });
      return recordMemoryWrite(result, conversationId);
    },
    async deleteMemory(memoryId, opts) {
      const conversationId = resolveMemoryConversationId(opts?.conversationId);
      const result = await request<MemoryWriteResult>("memory.delete", {
        conversation_id: conversationId,
        memory_id: memoryId,
      });
      return recordMemoryWrite(result, conversationId);
    },
    dismissToast(id) {
      desktopStore.getState().dismissToast(id);
    },
  };
  return { actions, loadBootstrap, conversationOpen };
}
