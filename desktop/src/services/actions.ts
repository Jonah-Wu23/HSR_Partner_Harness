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

function isSnapshot(value: unknown): value is DesktopSnapshot {
  return isDesktopSnapshot(value);
}

export interface ActionController {
  actions: HarnessActions;
  loadBootstrap(): Promise<void>;
}

export function createActionController(backend: DesktopBackend): ActionController {
  const ids = new RequestIdFactory();

  async function request<T>(method: DesktopCommandMethod, params: Record<string, unknown> = {}): Promise<T> {
    const command: DesktopCommand = { kind: "request", id: ids.next(), method, params };
    const result = await backend.request<T>(command);
    if (isSnapshot(result)) desktopStore.getState().hydrate(result);
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
  };
  return { actions, loadBootstrap };
}
