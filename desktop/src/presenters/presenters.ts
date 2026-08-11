import type { AppShellViewModel, ConversationViewModel, ProjectViewModel } from "../contracts/view-models";
import type { Message, ToolRun } from "../contracts/protocol";
import type { DesktopState } from "../stores/desktopStore";

function messagesFor(state: DesktopState, conversationId: string): Message[] {
  return (state.messageIdsByConversation[conversationId] ?? [])
    .map((id) => state.messagesById[id])
    .filter((message): message is Message => message !== undefined);
}

function toolsFor(state: DesktopState, conversationId: string): ToolRun[] {
  return (state.toolIdsByConversation[conversationId] ?? [])
    .map((id) => state.toolRunsById[id])
    .filter((tool): tool is ToolRun => tool !== undefined);
}

export function presentAppShell(state: DesktopState): AppShellViewModel {
  const currentProject = state.projectsById[state.currentProjectId];
  const currentConversation = state.conversationsById[state.currentConversationId];
  const activeConversationId = state.activeTask?.conversation_id;
  const projects: ProjectViewModel[] = Object.values(state.projectsById).map((project) => ({
    ...project,
    isCurrent: project.project_id === state.currentProjectId,
    isBusy: project.project_id === state.activeTask?.project_id,
    conversations: project.conversations.map((conversation): ConversationViewModel => ({
      ...conversation,
      isCurrent: conversation.conversation_id === state.currentConversationId,
      isTaskOrigin: conversation.conversation_id === activeConversationId,
    })),
  }));

  const characterMessages = currentConversation
    ? messagesFor(state, currentConversation.conversation_id).filter(
        (message) => message.source !== "assistant" && message.source !== "tool",
      )
    : [];
  const assistantMessages = currentConversation
    ? messagesFor(state, currentConversation.conversation_id).filter(
        (message) => message.source === "assistant" || message.source === "tool",
      )
    : [];
  const assistantTools = currentConversation ? toolsFor(state, currentConversation.conversation_id) : [];
  const approvalMode = currentProject?.approval_mode ?? "request_approval";

  return {
    status: state.status,
    theme: state.theme,
    navigation: state.pair
      ? {
          projects,
          currentProjectId: state.currentProjectId,
          currentConversationId: state.currentConversationId,
          currentPair: state.pair,
        }
      : null,
    workspace: currentConversation
      ? {
          mode: state.mode,
          character: {
            conversationId: currentConversation.conversation_id,
            messages: characterMessages,
            isStreaming: characterMessages.some((message) => message.streaming === true),
          },
          assistant: {
            conversationId: currentConversation.conversation_id,
            messages: assistantMessages,
            toolRuns: assistantTools,
            busy: state.busy,
            activeTask: state.activeTask,
          },
        }
      : null,
    composer: {
      target: state.composerTarget,
      draft: state.composerDraft,
      enabled: state.status === "ready",
      approvalMode,
      reasoningEffort: currentProject?.reasoning_effort ?? "low",
      asrPartial: state.voice.asr_partial,
    },
    approval: {
      mode: approvalMode,
      pending: state.approvals.map((approval) => ({
        ...approval,
        resolving: Boolean(state.approvalResolvingById[approval.approval_id]),
      })),
      reviewText: null,
    },
    voice: {
      ...state.voice,
      canPushToTalk: state.status === "ready",
    },
    error: state.error,
  };
}
