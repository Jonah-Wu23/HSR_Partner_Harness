import type { HarnessActions } from "../contracts/actions";
import type {
  ApprovalMode,
  DesktopCommand,
  DesktopCommandMethod,
  DesktopSnapshot,
  ReasoningEffort,
} from "../contracts/protocol";
import type { DesktopBackend } from "./backend";
import { RequestIdFactory } from "./backend";
import { isDesktopSnapshot } from "./mockDesktopBackend";
import { desktopStore } from "../stores/desktopStore";

export interface ActionController {
  actions: HarnessActions;
  loadBootstrap(): Promise<void>;
}

export function createActionController(backend: DesktopBackend): ActionController {
  const ids = new RequestIdFactory();

  async function request<T>(method: DesktopCommandMethod, params: Record<string, unknown> = {}): Promise<T> {
    const command: DesktopCommand = { kind: "request", id: ids.next(), method, params };
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

  const actions: HarnessActions = {
    async createProject(rootPath, name) {
      const selectedRoot = rootPath?.trim() || (await backend.pickFolder("选择项目文件夹"));
      if (!selectedRoot) return;
      await request("project.create", { root_path: selectedRoot, name });
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
    async createConversation(projectId, title) {
      await request("conversation.create", { project_id: projectId, title });
    },
    async selectConversation(conversationId) {
      await request("conversation.select", { conversation_id: conversationId });
    },
    async renameConversation(conversationId, title) {
      await request("conversation.rename", { conversation_id: conversationId, title });
    },
    async archiveConversation(conversationId) {
      await request("conversation.archive", { conversation_id: conversationId });
    },
    async switchMode(mode) {
      // V0.2 模式独立（问题 3）：模式由后端按会话持久化，走独立命令。
      // 先同步更新本地模式（工作台开合动画即时反馈），再异步持久化；
      // 不依赖某次 settings 快照顺便覆盖，也不被推理档位/审批方式重置。
      desktopStore.getState().setMode(mode);
      const conversationId = desktopStore.getState().currentConversationId;
      if (conversationId) {
        try {
          await request("conversation.set_mode", { conversation_id: conversationId, mode });
        } catch {
          // 持久化失败不回滚 UI；下次快照按后端 last_mode 为准
        }
      }
    },
    switchTheme(theme) {
      if (typeof window !== "undefined") window.localStorage.setItem("pair-harness-theme", theme);
      desktopStore.getState().setTheme(theme);
    },
    async submitMessage(text, target, intent) {
      const state = desktopStore.getState();
      const actualTarget = target ?? state.composerTarget;
      desktopStore.getState().setComposerDraft("");
      await request("chat.submit", {
        conversation_id: state.currentConversationId,
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
      const item = (state.queueItemsByConversation[state.currentConversationId] ?? []).find(
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
      await request("task.cancel");
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
      const projectId = desktopStore.getState().currentProjectId;
      await request("project.update_settings", { project_id: projectId, approval_mode: mode });
    },
    async setReasoningEffort(effort: ReasoningEffort) {
      const projectId = desktopStore.getState().currentProjectId;
      await request("project.update_settings", { project_id: projectId, reasoning_effort: effort });
    },
    async setVadEnabled(enabled) {
      await request("voice.vad_set", { enabled });
    },
    async startPushToTalk(target) {
      await request("voice.ptt_start", { target: target ?? desktopStore.getState().composerTarget });
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
    async codexApiLogin(apiKey) {
      await request("codex.api_login", { api_key: apiKey });
    },
    async codexLogout() {
      await request("codex.logout");
    },
    async voicePreview(text, voiceId) {
      await request("voice.preview", { text, ...(voiceId ? { voice_id: voiceId } : {}) });
    },
    dismissToast(id) {
      // V0.2 M4：Toast 是本地 UI 状态，不经过后端
      desktopStore.getState().dismissToast(id);
    },
  };
  return { actions, loadBootstrap };
}
