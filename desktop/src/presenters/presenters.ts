import type {
  AppShellViewModel,
  ConversationViewModel,
  ProjectViewModel,
} from "../contracts/view-models";
import type { Message, ToolRun } from "../contracts/protocol";
import type { DesktopRenderState } from "../stores/desktopStore";
import type { QueueItemView, ToastItem } from "../ui/status/types";
import type { DelegationCardView } from "../ui/workspace/DelegationCard";
import type { VoiceMiniPlayerView } from "../ui/composer/VoiceMiniPlayer";
import type { AccountListItem } from "../ui/gate/types";
import type { TestResult, VoicePageView } from "../ui/settings/types";

type CodingAssistantCodexStatus = "logged_out" | "waiting" | "logged_in" | "expired";

function messagesFor(state: DesktopRenderState, conversationId: string): Message[] {
  return (state.messageIdsByConversation[conversationId] ?? [])
    .map((id) => state.messagesById[id])
    .filter((message): message is Message => message !== undefined);
}

function toolsFor(state: DesktopRenderState, conversationId: string): ToolRun[] {
  return (state.toolIdsByConversation[conversationId] ?? [])
    .map((id) => state.toolRunsById[id])
    .filter((tool): tool is ToolRun => tool !== undefined);
}

/** V0.2 M4：队列项摘要——压缩空白后的单行文本，超 24 字截断加省略号。 */
function truncateSingleLine(text: string, max = 24): string {
  const compact = text.replace(/\s+/g, " ").trim();
  return compact.length <= max ? compact : `${compact.slice(0, max)}…`;
}

/** V0.2 M4：排队条视图——当前会话未撤回的队列项按 position 升序。 */
function presentQueueItems(state: DesktopRenderState): QueueItemView[] {
  const items = state.queueItemsByConversation[state.currentConversationId] ?? [];
  return items
    .filter((item) => item.status !== "withdrawn")
    .sort((a, b) => a.position - b.position)
    .map((item) => ({
      queueItemId: item.queue_item_id,
      target: item.target,
      summary: truncateSingleLine(item.text),
      position: item.position + 1,
      waitingFor: "等待当前回复结束",
      intent: item.intent,
    }));
}

/** V0.2 M4：委派卡——当前会话中角色发起的委派（origin=character_delegation
    且 delegation_id 非空），取最新一条 user 消息；状态来自真实消息状态。 */
function presentDelegation(state: DesktopRenderState): DelegationCardView | null {
  if (!state.pair) return null;
  const ids = state.messageIdsByConversation[state.currentConversationId] ?? [];
  let delegationMessage: Message | undefined;
  for (const id of ids) {
    const message = state.messagesById[id];
    if (
      message &&
      message.source === "user" &&
      message.origin === "character_delegation" &&
      message.delegation_id
    ) {
      delegationMessage = message;
    }
  }
  if (!delegationMessage) return null;
  const executionStatus = delegationMessage.status;
  const status =
    state.activeTask?.task_id === delegationMessage.delegation_id ||
    executionStatus === "processing"
      ? "running"
      : executionStatus === "failed"
        ? "failed"
        : executionStatus === "cancelled"
          ? "cancelled"
          : "completed";
  return {
    delegationId: delegationMessage.delegation_id ?? "",
    fromName: state.pair.character.name,
    summary: delegationMessage.text,
    status,
  };
}

/** V0.2 M4：语音迷你播放条——tts 播放/合成/失败时映射；
    后端 tts 状态没有 speaker 来源，用角色兜底；摘要无数据给空串。 */
function presentVoiceMiniPlayer(state: DesktopRenderState): VoiceMiniPlayerView | null {
  const pair = state.pair;
  if (!pair || state.voice.tts === "idle") return null;
  if (state.voice.tts === "failed") {
    return {
      status: "failed",
      speaker: "character",
      speakerName: pair.character.name,
      summary: "",
      queuedCount: state.voice.speech_queue_len,
      errorText: state.voice.error ?? undefined,
    };
  }
  return {
    status: state.voice.tts === "synthesizing" ? "synthesizing" : "playing",
    speaker: "character",
    speakerName: pair.character.name,
    summary: "",
    queuedCount: state.voice.speech_queue_len,
  };
}

/** V0.2 M4：账号门与引导——默认账号（未设密码）进账号门；
    非默认账号且引导未完成进 Onboarding。 */
function presentAccountGate(state: DesktopRenderState): AppShellViewModel["accountGate"] {
  if (state.currentAccount?.username !== "default") return null;
  const accounts: AccountListItem[] = state.accounts.map((account) => ({
    accountId: account.account_id,
    displayName: account.display_name,
    avatarUrl: account.avatar || null,
    isLastLogin: account.is_last_login,
  }));
  return { accounts, error: null, busy: state.status !== "ready" };
}

interface ConfigShape {
  engine?: string;
  dialogue?: Record<string, string>;
  voice?: Record<string, string | boolean>;
  codex?: Record<string, string | null>;
}

/** V0.2 M4：设置中心四页视图——configSnapshot 映射，无数据给默认空值。 */
function presentSettings(state: DesktopRenderState): AppShellViewModel["settings"] {
  const config = state.configSnapshot as ConfigShape | null;
  const dialogue = config?.dialogue ?? {};
  const voiceConfig = config?.voice ?? {};
  const codex = config?.codex ?? {};
  const reasoningEffort =
    typeof dialogue.reasoning_effort === "string" ? dialogue.reasoning_effort : "auto";

  const currentConv = state.conversationsById[state.currentConversationId];
  const activePairId = currentConv?.pair_id || state.pair?.pair_id;
  const activePair =
    state.pairs.find((p) => p.pair_id === activePairId) ?? state.pair;

  const characterVoiceId =
    activePair?.character.voice_id || String(voiceConfig.character_voice ?? "");
  const characterVoiceName =
    activePair?.character.name || String(voiceConfig.character_voice_name ?? "");
  const assistantVoiceId =
    activePair?.assistant.voice_id || String(voiceConfig.assistant_voice ?? "");
  const assistantVoiceName =
    activePair?.assistant.name || String(voiceConfig.assistant_voice_name ?? "");

  const voice: VoicePageView = {
    enabled: Boolean(voiceConfig.enabled === true || voiceConfig.enabled === "true"),
    assistantVoiceEnabled: Boolean(
      voiceConfig.assistant_voice_enabled === true || voiceConfig.assistant_voice_enabled === "true",
    ),
    characterVoiceId,
    characterVoiceName,
    assistantVoiceId,
    assistantVoiceName,
    vadEnabled: Boolean(voiceConfig.vad_enabled === "true"),
    vadStatus: "ready",
  };
  const idle: TestResult = { state: "idle" };
  return {
    account: {
      displayName: state.currentAccount?.display_name ?? "",
      avatarUrl: state.currentAccount?.avatar || null,
    },
    coding: {
      engine: config?.engine === "deepseek" ? "deepseek" : "codex",
      codex: {
        status:
          codex.status === "logged_in" || codex.status === "expired" || codex.status === "waiting"
            ? (codex.status as CodingAssistantCodexStatus)
            : "logged_out",
        accountLabel: typeof codex.account_label === "string" ? codex.account_label : null,
      },
    },
    model: {
      provider: String(dialogue.provider ?? ""),
      model: String(dialogue.model ?? ""),
      baseUrl: String(dialogue.base_url ?? ""),
      apiKeyMasked: String(dialogue.api_key_masked ?? ""),
      reasoningEffort,
    },
    voice,
    modelTest: idle,
    voicePreview: idle,
  };
}

export function presentAppShell(state: DesktopRenderState): AppShellViewModel {
  const currentProject = state.projectsById[state.currentProjectId];
  const currentConversation = state.conversationsById[state.currentConversationId];
  const activeConversationId = state.activeTask?.conversation_id;
  const projects: ProjectViewModel[] = Object.values(state.projectsById).map((project) => ({
    ...project,
    isCurrent: project.project_id === state.currentProjectId,
    isBusy: project.project_id === state.activeTask?.project_id,
    conversations: (project.conversations ?? []).map((conversation): ConversationViewModel => ({
      ...conversation,
      isCurrent: conversation.conversation_id === state.currentConversationId,
      isTaskOrigin: conversation.conversation_id === activeConversationId,
    })),
  }));

  // V0.2 消息空间归属（问题 7）：不再只按 source 切栏。
  // user+target=assistant 与 assistant/tool 归工作台；
  // user+target=character、character、system 归角色区。
  const characterMessages = currentConversation
    ? messagesFor(state, currentConversation.conversation_id).filter(
        (message) =>
          (message.source === "user" && message.target !== "assistant") ||
          message.source === "character" ||
          message.source === "system",
      )
    : [];
  const assistantMessages = currentConversation
    ? messagesFor(state, currentConversation.conversation_id).filter(
        (message) =>
          (message.source === "user" && message.target === "assistant") ||
          message.source === "assistant" ||
          message.source === "tool",
      )
    : [];
  const assistantTools = currentConversation ? toolsFor(state, currentConversation.conversation_id) : [];
  const approvalMode = currentProject?.approval_mode ?? "request_approval";
  const currentPairId =
    currentConversation?.pair_id || state.pair?.pair_id || "phainon_ancient_machine";

  return {
    status: state.status,
    theme: state.theme,
    currentPairId,
    navigation: state.pair
      ? {
          projects,
          currentProjectId: state.currentProjectId,
          currentConversationId: state.currentConversationId,
          currentPair: state.pair,
          pairs: state.pairs?.length ? state.pairs : [state.pair],
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
          // V0.2 M4：委派卡（角色区与工作台之间的视觉桥梁）
          delegation: presentDelegation(state),
        }
      : null,
    composer: {
      target: state.composerTarget,
      draft: state.composerDraft,
      enabled: state.status === "ready" && currentConversation !== undefined,
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
      reviewActive: state.reviewActive,
      reviewText: state.reviewText,
    },
    voice: {
      ...state.voice,
      canPushToTalk: state.status === "ready",
    },
    error: state.error,
    // V0.2 M4：视觉方案接口（队列 / Toast / 语音播放条 / 账号门 / 设置）
    queueItems: presentQueueItems(state),
    toasts: state.toasts as ToastItem[],
    voiceMiniPlayer: presentVoiceMiniPlayer(state),
    accountGate: presentAccountGate(state),
    onboarding:
      state.currentAccount !== null &&
      state.currentAccount.username !== "default" &&
      state.currentAccount.onboarding_complete === false,
    settings: presentSettings(state),
  };
}
