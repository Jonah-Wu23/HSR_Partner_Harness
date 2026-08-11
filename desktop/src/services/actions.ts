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
      await request("project.create", { root_path: rootPath, name });
    },
    async selectProject(projectId) {
      await request("project.select", { project_id: projectId });
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
    switchMode(mode) {
      desktopStore.getState().setMode(mode);
    },
    switchTheme(theme) {
      if (typeof window !== "undefined") window.localStorage.setItem("pair-harness-theme", theme);
      desktopStore.getState().setTheme(theme);
    },
    async submitMessage(text, target) {
      const state = desktopStore.getState();
      const actualTarget = target ?? state.composerTarget;
      desktopStore.getState().setComposerDraft("");
      await request("chat.submit", {
        conversation_id: state.currentConversationId,
        target: actualTarget,
        mode: state.mode,
        text,
      });
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
