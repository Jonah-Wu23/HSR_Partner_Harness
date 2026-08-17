import type {
  CodexOAuthStatus,
  HarnessActions,
  SubmitMessageResult,
  VoiceProvisionResult,
} from "../contracts/actions";
import type {
  ApprovalMode,
  ConversationOpenResult,
  DesktopCommand,
  DesktopCommandMethod,
  DesktopSnapshot,
  ReasoningEffort,
} from "../contracts/protocol";
import type { DesktopBackend } from "./backend";
import { RequestIdFactory } from "./backend";
import { isDesktopSnapshot } from "./mockDesktopBackend";
import {
  desktopStore,
  selectWindowConversationId,
  selectWindowProjectId,
} from "../stores/desktopStore";

export interface ActionController {
  actions: HarnessActions;
  loadBootstrap(): Promise<void>;
  /** V0.3.2 M5：conversation.open 只读装载指定聊天并打开其标签（不改全局当前聊天）。 */
  conversationOpen(conversationId: string): Promise<void>;
}

export function createActionController(backend: DesktopBackend): ActionController {
  // V0.3.2 M5：请求 id 携带本窗口 viewId（多窗口全应用唯一），失败如常上抛。
  const ids = new RequestIdFactory(() => desktopStore.getState().viewId);

  async function request<T>(method: DesktopCommandMethod, params: Record<string, unknown> = {}): Promise<T> {
    const viewId = desktopStore.getState().viewId;
    const command: DesktopCommand = {
      kind: "request",
      id: ids.next(),
      method,
      params,
      view_id: viewId,
    };
    const result = await backend.request<T>(command);
    if (isDesktopSnapshot(result)) desktopStore.getState().hydrate(result);
    return result;
  }

  const loadBootstrap = async () => {
    desktopStore.getState().setStatus("booting");
    try {
      await request<DesktopSnapshot>("app.bootstrap");
    } catch (error) {
      desktopStore.getState().setStatus("error", error instanceof Error ? error.message : String(error));
    }
  };

  // V0.3.2 M5：只读装载指定聊天——参数携带本窗口 view_id；结果合并进
  // 各会话索引并打开该聊天的标签，不改变后端全局当前聊天。
  const conversationOpen = async (conversationId: string) => {
    const result = await request<ConversationOpenResult>("conversation.open", {
      conversation_id: conversationId,
      view_id: desktopStore.getState().viewId,
    });
    desktopStore.getState().hydrateConversationView(result);
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
      await request("project.create", { root_path: selectedRoot, name });
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
      await request("project.select", { project_id: projectId });
    },
    async archiveProject(projectId) {
      await request("project.archive", { project_id: projectId });
    },
    async createConversation(projectId, title, pairId) {
      await request("conversation.create", {
        project_id: projectId,
        title,
        ...(pairId ? { pair_id: pairId } : {}),
      });
      focusBackendConversation();
    },
    async selectConversation(conversationId) {
      await request("conversation.select", { conversation_id: conversationId });
      focusBackendConversation();
    },
    async openConversationTab(conversationId) {
      // 每次聚焦都重新读取该会话的权威快照，同时让共享的
      // 物理语音运行时切到该聊天；conversation.open 不改 Sidecar 全局导航。
      await conversationOpen(conversationId);
    },
    closeConversationTab(conversationId) {
      // V0.3.2 M5：只移除本窗口标签；标签已有完整缓存，切到相邻标签
      // 不需要 conversation.select，也绝不取消任务或关闭会话。
      desktopStore.getState().closeConversationTab(conversationId);
    },
    async openConversationWindow(conversationId) {
      const state = desktopStore.getState();
      const conversation = state.conversationsById[conversationId];
      const projectId = conversation?.project_id;
      if (!conversation || !projectId) {
        throw new Error(`找不到聊天 ${conversationId} 的项目上下文`);
      }
      try {
        await backend.openChatWindow(conversationId, projectId, conversation.title);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
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
      await request("conversation.rename", { conversation_id: conversationId, title });
    },
    async archiveConversation(conversationId) {
      await request("conversation.archive", { conversation_id: conversationId });
    },
    async switchMode(mode) {
      // V0.2 模式独立：模式由后端按会话持久化，走独立命令。
      // M5.3：先持久化成功再切换本地模式；失败恢复原模式并保留真实错误。
      const previous = desktopStore.getState().mode;
      // V0.3.2 M5：模式保存到本窗口当前聊天（活动标签优先）。
      const conversationId = selectWindowConversationId(desktopStore.getState());
      try {
        if (conversationId) {
          await request("conversation.set_mode", { conversation_id: conversationId, mode });
        }
        desktopStore.getState().setMode(mode);
      } catch (error) {
        desktopStore.getState().setMode(previous);
        const message = error instanceof Error ? error.message : String(error);
        desktopStore.getState().pushToast({
          id: `mode:${message}`,
          kind: "error",
          text: `模式切换保存失败：${message}`,
          hasDetails: true,
        });
        throw error;
      }
    },
    switchTheme(theme) {
      if (typeof window !== "undefined") window.localStorage.setItem("pair-harness-theme", theme);
      desktopStore.getState().setTheme(theme);
    },
    async submitMessage(text, target, intent) {
      const state = desktopStore.getState();
      const actualTarget = target ?? state.composerTarget;
      // M5.3：草稿由 Composer 在收到 accepted/queued 回执后清除；这里不清空，
      // 请求失败时输入文字与 target 都保留。
      // V0.3.2 M5：提交到本窗口当前聊天（活动标签优先），其他窗口不受影响。
      return request<SubmitMessageResult>("chat.submit", {
        conversation_id: selectWindowConversationId(state),
        target: actualTarget,
        mode: state.mode,
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
      // V0.2 M4：QueueStrip「编辑」= 撤回该项并返回原文（拉回输入区）
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
      // V0.3.2 M5：定向取消必须携带本窗口当前聊天的 conversation_id 与
      // 该聊天活动任务的 task_id；缺少任一项时不发送模糊的旧式全局取消。
      const state = desktopStore.getState();
      const conversationId = selectWindowConversationId(state);
      const activeTask = conversationId
        ? state.activeTasksByConversation[conversationId]
        : undefined;
      if (!conversationId || !activeTask) {
        throw new Error("当前聊天没有可取消的活动任务");
      }
      await request("task.cancel", {
        conversation_id: conversationId,
        task_id: activeTask.task_id,
      });
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
      if (!projectId) throw new Error("当前窗口没有项目上下文");
      await request("project.update_settings", { project_id: projectId, approval_mode: mode });
    },
    async setReasoningEffort(effort: ReasoningEffort) {
      const projectId = selectWindowProjectId(desktopStore.getState());
      if (!projectId) throw new Error("当前窗口没有项目上下文");
      await request("project.update_settings", { project_id: projectId, reasoning_effort: effort });
    },
    async setVadEnabled(enabled) {
      await request("voice.vad_set", { enabled });
    },
    async startPushToTalk(target) {
      const state = desktopStore.getState();
      const conversationId = selectWindowConversationId(state);
      await request("voice.ptt_start", {
        target: target ?? state.composerTarget,
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
      // Sidecar 断开时走 Rust 侧强制重启（sidecar_reconnect），成功后由
      // connection.status connected 事件驱动重新 bootstrap；失败则上报错误状态。
      try {
        await backend.reconnectSidecar();
      } catch (error) {
        desktopStore
          .getState()
          .setStatus("error", error instanceof Error ? error.message : String(error));
      }
    },
    async listAccounts() {
      await request("account.list");
    },
    async registerAccount(username, displayName, password) {
      await request("account.register", { username, display_name: displayName, password });
    },
    async loginAccount(accountId, password) {
      await request("account.login", { account_id: accountId, password });
    },
    async logoutAccount() {
      await request("account.logout");
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
      // V0.2 M4：config.get 结果存入 store（SettingsCenter 数据源）
      const result = await request<Record<string, unknown>>("config.get");
      desktopStore.getState().setConfigSnapshot(result);
    },
    async setConfig(updates) {
      const result = await request<{ config?: Record<string, unknown> }>("config.set", { updates });
      if (result?.config) desktopStore.getState().setConfigSnapshot(result.config);
    },
    async testConnection() {
      // V0.2 M4：返回人话结果（Onboarding 保存并测试 / 设置中心模型页）
      const result = await request<{ ok?: boolean; message?: string }>("config.test_connection");
      if (result?.ok === false) return result.message ?? "连接失败，请检查配置";
      return result?.message ?? "连接正常";
    },
    async codexOauthStart() {
      const result = await request<{ config?: Record<string, unknown> }>("codex.oauth_start");
      if (result?.config) desktopStore.getState().setConfigSnapshot(result.config);
    },
    async codexOauthStatus() {
      return request<CodexOAuthStatus>("codex.oauth_status");
    },
    async codexApiLogin(apiKey) {
      await request("codex.api_login", { api_key: apiKey });
    },
    async codexLogout() {
      await request("codex.logout");
    },
    async voicePreview(text, voiceId) {
      await request("voice.preview", { text, ...(voiceId ? { voice_id: voiceId } : {}) });
    },
    async provisionVoices(speakerIds, replaceExisting) {
      const params: Record<string, unknown> = {};
      if (speakerIds !== undefined) params.speaker_ids = speakerIds;
      if (replaceExisting !== undefined) params.replace_existing = replaceExisting;
      const result = await request<VoiceProvisionResult>("voice.provision", params);
      // voice.provision 的逐项事件用于实时状态；命令完成后再取一次权威配置，
      // 确保成功项已从 SQLite 水合到设置页，且失败项仍保留真实状态。
      const config = await request<Record<string, unknown>>("config.get");
      desktopStore.getState().setConfigSnapshot(config);
      return result;
    },
    dismissToast(id) {
      // V0.2 M4：Toast 是本地 UI 状态，不经过后端
      desktopStore.getState().dismissToast(id);
    },
  };
  return { actions, loadBootstrap, conversationOpen };
}
