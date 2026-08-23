import type {
  AppShellViewModel,
  ChatTabsViewModel,
  ConversationViewModel,
  ProjectViewModel,
  WorkbenchItem,
} from "../contracts/view-models";
import type { Message, ToolRun } from "../contracts/protocol";
import type { DesktopRenderState } from "../stores/desktopStore";
import type { QueueItemView, ToastItem } from "../ui/status/types";
import type { DelegationCardView } from "../ui/workspace/DelegationCard";
import type { VoiceMiniPlayerView } from "../ui/composer/VoiceMiniPlayer";
import type { AccountListItem } from "../ui/gate/types";
import type {
  TestResult,
  VoicePageView,
  VoiceSpeakerStatus,
} from "../ui/settings/types";

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

/** V0.2 M4：排队条视图——指定会话未撤回的队列项按 position 升序。 */
function presentQueueItems(state: DesktopRenderState, conversationId: string): QueueItemView[] {
  const items = state.queueItemsByConversation[conversationId] ?? [];
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

/** V0.2 M4：委派卡——指定会话中角色发起的委派（origin=character_delegation
    且 delegation_id 非空），取最新一条 user 消息；状态来自真实消息状态。 */
function presentDelegation(
  state: DesktopRenderState,
  conversationId: string,
): DelegationCardView | null {
  if (!state.pair) return null;
  const ids = state.messageIdsByConversation[conversationId] ?? [];
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
  voice?: Record<string, unknown>;
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

  // config.get 是 V0.3.2 语音归属的权威来源。只有尚未拉取过配置时才
  // 回退旧快照里的 pair voice_id，避免把作者音色重新显示为当前账号音色。
  const hasVoiceConfig = config?.voice !== undefined;
  const configuredCharacterVoiceId =
    typeof voiceConfig.character_voice === "string" ? voiceConfig.character_voice : "";
  const configuredAssistantVoiceId =
    typeof voiceConfig.assistant_voice === "string" ? voiceConfig.assistant_voice : "";
  const characterVoiceId =
    configuredCharacterVoiceId || (!hasVoiceConfig ? activePair?.character.voice_id ?? "" : "");
  const characterVoiceName =
    (typeof voiceConfig.character_voice_name === "string"
      ? voiceConfig.character_voice_name
      : "") || activePair?.character.name || "";
  const assistantVoiceId =
    configuredAssistantVoiceId || (!hasVoiceConfig ? activePair?.assistant.voice_id ?? "" : "");
  const assistantVoiceName =
    (typeof voiceConfig.assistant_voice_name === "string"
      ? voiceConfig.assistant_voice_name
      : "") || activePair?.assistant.name || "";

  const speakers: VoiceSpeakerStatus[] = Array.isArray(voiceConfig.speakers)
    ? voiceConfig.speakers.flatMap((value): VoiceSpeakerStatus[] => {
        if (!value || typeof value !== "object") return [];
        const item = value as Record<string, unknown>;
        const speakerId = String(item.speaker_id ?? "");
        if (!speakerId) return [];
        const state = String(item.state ?? "not_generated");
        return [
          {
            speakerId,
            name: String(item.name ?? speakerId),
            method: item.method === "design" ? "design" : "clone",
            state:
              state === "creating" || state === "completed" || state === "failed"
                ? state
                : "not_generated",
            voiceId: String(item.voice_id ?? "") || undefined,
            error: item.error == null ? null : String(item.error),
          },
        ];
      })
    : [];

  const voice: VoicePageView = {
    accountId: state.currentAccountId,
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
    baseUrl: typeof voiceConfig.base_url === "string" ? voiceConfig.base_url : "",
    apiKeyMasked:
      typeof voiceConfig.api_key_masked === "string" ? voiceConfig.api_key_masked : "",
    wsUrl: typeof voiceConfig.ws_url === "string" ? voiceConfig.ws_url : "",
    customizationEndpoint:
      typeof voiceConfig.customization_endpoint === "string"
        ? voiceConfig.customization_endpoint
        : "",
    asrModel: typeof voiceConfig.asr_model === "string" ? voiceConfig.asr_model : undefined,
    ttsModel: typeof voiceConfig.tts_model === "string" ? voiceConfig.tts_model : undefined,
    asrAvailable: Boolean(voiceConfig.asr_available === true),
    credentialSource:
      voiceConfig.credential_source === "account" ||
      voiceConfig.credential_source === "development_env"
        ? voiceConfig.credential_source
        : "not_configured",
    voicesSource:
      voiceConfig.voices_source === "account" ||
      voiceConfig.voices_source === "env_author"
        ? voiceConfig.voices_source
        : "not_provisioned",
    speakers,
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

/** V0.3.2 M1：工作台统一时间线——助手 segment 与工具卡按 timeline_order
    混排；没有序号的消息（用户任务卡、system 卡）保持在序号块之前，
    legacy 记录（全部无序号）自然回退为“先消息后工具”的旧版分组。 */
function presentWorkbenchItems(
  messages: Message[],
  tools: ToolRun[],
): WorkbenchItem[] {
  const messageItems: WorkbenchItem[] = messages
    .filter((message) => message.source !== "tool")
    .map((message) => ({
      kind: "message" as const,
      order:
        message.timeline_order ??
        (typeof message.payload?.timeline_order === "number"
          ? (message.payload.timeline_order as number)
          : null),
      message,
    }));
  const toolItems: WorkbenchItem[] = tools.map((run) => ({
    kind: "tool" as const,
    order: run.timeline_order ?? null,
    run,
  }));
  const unordered: WorkbenchItem[] = [];
  const ordered: WorkbenchItem[] = [];
  for (const item of [...messageItems, ...toolItems]) {
    if (item.order === null || item.order === undefined) unordered.push(item);
    else ordered.push(item);
  }
  ordered.sort((a, b) => (a.order as number) - (b.order as number));
  return [...unordered, ...ordered];
}

/** V0.3.2 M5：聊天标签视图——标题取自会话记录（conversation.changed 实时更新），
    状态点只反映该聊天自己的运行/排队/待审批状态。 */
function presentChatTabs(state: DesktopRenderState): ChatTabsViewModel[] {
  return state.openConversationIds.map((conversationId) => {
    const conversation = state.conversationsById[conversationId];
    return {
      conversationId,
      title: conversation?.title ?? "未知聊天",
      isRunning: Boolean(state.activeTasksByConversation[conversationId]),
      isQueued: (state.queueItemsByConversation[conversationId] ?? []).some(
        (item) => item.status !== "withdrawn",
      ),
      isWaitingApproval: state.approvals.some(
        (approval) => approval.conversation_id === conversationId,
      ),
      isActive: conversationId === state.activeConversationId,
    };
  });
}

export function presentAppShell(state: DesktopRenderState): AppShellViewModel {
  const currentProject = state.projectsById[state.currentProjectId];
  // V0.3.2 M5：工作区渲染本窗口活动标签；没有打开的标签（全部关闭）时为空状态。
  const workspaceConversationId = state.activeConversationId;
  const workspaceConversation = workspaceConversationId
    ? state.conversationsById[workspaceConversationId]
    : undefined;
  // V0.3.2 M5：项目级活动标记——该项目下任一聊天有活动任务即点亮。
  const activeTaskCountByProject: Record<string, number> = {};
  for (const task of Object.values(state.activeTasksByConversation)) {
    activeTaskCountByProject[task.project_id] =
      (activeTaskCountByProject[task.project_id] ?? 0) + 1;
  }
  const navigationConversationId = workspaceConversationId ?? state.currentConversationId;
  const projects: ProjectViewModel[] = Object.values(state.projectsById).map((project) => {
    const activeTaskCount = activeTaskCountByProject[project.project_id] ?? 0;
    return {
      ...project,
      isCurrent: project.project_id === state.currentProjectId,
      isBusy: activeTaskCount > 0,
      activeTaskCount,
      conversations: (project.conversations ?? []).map(
        (conversation): ConversationViewModel => {
          const isRunning = Boolean(
            state.activeTasksByConversation[conversation.conversation_id],
          );
          return {
            ...conversation,
            isCurrent: conversation.conversation_id === navigationConversationId,
            isRunning,
            isTaskOrigin: isRunning,
          };
        },
      ),
    };
  });

  // V0.2 消息空间归属（问题 7）：不再只按 source 切栏。
  // user+target=assistant 与 assistant/tool 归工作台；
  // user+target=character、character、system 归角色区。
  const characterMessages = workspaceConversation
    ? messagesFor(state, workspaceConversation.conversation_id).filter(
        (message) =>
          (message.source === "user" && message.target !== "assistant") ||
          message.source === "character" ||
          message.source === "system",
      )
    : [];
  const assistantMessages = workspaceConversation
    ? messagesFor(state, workspaceConversation.conversation_id).filter(
        (message) =>
          (message.source === "user" && message.target === "assistant") ||
          message.source === "assistant" ||
          message.source === "tool",
      )
    : [];
  const assistantTools = workspaceConversation
    ? toolsFor(state, workspaceConversation.conversation_id)
    : [];
  const approvalMode = currentProject?.approval_mode ?? "request_approval";
  const currentPairId =
    workspaceConversation?.pair_id || state.pair?.pair_id || "phainon_ancient_machine";

  return {
    status: state.status,
    theme: state.theme,
    currentPairId,
    navigation: state.pair
      ? {
          projects,
          currentProjectId: state.currentProjectId,
          currentConversationId: navigationConversationId,
          currentPair: state.pair,
          pairs: state.pairs?.length ? state.pairs : [state.pair],
        }
      : null,
    chatTabs: presentChatTabs(state),
    workspace: workspaceConversation
      ? {
          mode: state.mode,
          character: {
            conversationId: workspaceConversation.conversation_id,
            messages: characterMessages,
            isStreaming: characterMessages.some((message) => message.streaming === true),
          },
          assistant: {
            conversationId: workspaceConversation.conversation_id,
            messages: assistantMessages,
            toolRuns: assistantTools,
            items: presentWorkbenchItems(assistantMessages, assistantTools),
            busy: state.busy,
            activeTask: state.activeTask,
          },
          // V0.2 M4：委派卡（角色区与工作台之间的视觉桥梁）
          delegation: presentDelegation(state, workspaceConversation.conversation_id),
        }
      : null,
    composer: {
      target: state.composerTarget,
      draft: state.composerDraft,
      enabled: state.status === "ready" && workspaceConversation !== undefined,
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
    queueItems: presentQueueItems(state, workspaceConversationId ?? ""),
    toasts: state.toasts as ToastItem[],
    voiceMiniPlayer: presentVoiceMiniPlayer(state),
    accountGate: presentAccountGate(state),
    onboarding:
      state.currentAccount !== null &&
      state.currentAccount.username !== "default" &&
      state.currentAccount.onboarding_complete === false,
    settings: presentSettings(state),
    // V0.3.3：角色卡与远程配对 slice 在 store 层按视图模型形状维护，直接透传。
    mainView: state.mainView,
    characterLibrary: state.characterLibrary,
    characterCreate: state.characterCreate,
    remotePairing: state.remotePairing,
  };
}
