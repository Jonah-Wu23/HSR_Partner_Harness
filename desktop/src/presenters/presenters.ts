import type {
  AppShellViewModel,
  CharacterCardVoicePageViewModel,
  ChatTabsViewModel,
  ConversationViewModel,
  ProjectViewModel,
  WorkbenchItem,
} from "../contracts/view-models";
import type { Message, QueueItem, ToolRun, VoiceState } from "../contracts/protocol";
import {
  selectComposerTarget,
  selectWindowMode,
  selectWindowProjectId,
  type DesktopRenderState,
} from "../stores/desktopStore";
import type { QueueItemView, ToastItem } from "../ui/status/types";
import type { DelegationCardView } from "../ui/workspace/DelegationCard";
import type { VoiceMiniPlayerView } from "../ui/composer/VoiceMiniPlayer";
import type { AccountListItem } from "../ui/gate/types";
import type {
  TestResult,
  VoicePageView,
  VoiceSpeakerStatus,
} from "../ui/settings/types";

/** 指定会话的消息，按 timeline_order 排序。 */
function messagesFor(state: DesktopRenderState, conversationId: string): Message[] {
  return (state.messageIdsByConversation[conversationId] ?? [])
    .map((id) => state.messagesById[id])
    .sort((left, right) => left.timeline_order - right.timeline_order);
}

function toolsFor(state: DesktopRenderState, conversationId: string): ToolRun[] {
  return (state.toolIdsByConversation[conversationId] ?? []).map((id) => state.toolRunsById[id]);
}

/** 队列项摘要：压缩空白后的单行文本，超 24 字截断加省略号。 */
function truncateSingleLine(text: string, max = 24): string {
  const compact = text.replace(/\s+/g, " ").trim();
  return compact.length <= max ? compact : `${compact.slice(0, max)}…`;
}

/** 指定会话未撤回的排队项（完整文本，按 position 升序），显示在消息流尾部；
    队列条用 presentQueueItems 的截断摘要。 */
function queuedItemsFor(state: DesktopRenderState, conversationId: string): QueueItem[] {
  return (state.queueItemsByConversation[conversationId] ?? [])
    .filter((item) => item.status !== "withdrawn")
    .sort((a, b) => a.position - b.position);
}

/** 排队条视图：指定会话未撤回的队列项按 position 升序。waitingFor 按真实状态派生；
    派发失败的项不再等待，只显示失败原因，也不计入后面各项的等待数。 */
function presentQueueItems(state: DesktopRenderState, conversationId: string): QueueItemView[] {
  const ordered = queuedItemsFor(state, conversationId);
  const hasActiveTurn = Boolean(state.activeTasksByConversation[conversationId]);
  let pendingAhead = 0;
  return ordered.map((item) => {
    const failed = item.status === "failed";
    const view: QueueItemView = {
      queueItemId: item.queue_item_id,
      target: item.target,
      summary: truncateSingleLine(item.text),
      position: item.position + 1,
      waitingFor: failed
        ? ""
        : item.status === "processing"
          ? "执行中"
          : hasActiveTurn
            ? pendingAhead === 0
              ? "等待当前回复结束"
              : `等待当前回复及前面 ${pendingAhead} 项`
            : "等待派发",
      intent: item.intent,
      failed,
      error: item.error,
    };
    if (!failed) pendingAhead += 1;
    return view;
  });
}

/** 委派卡：指定会话中角色发起的委派（origin=character_delegation 且 delegation_id 非空），
    取最新一条 user 消息，状态来自消息状态。 */
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

/** 语音迷你播放条：tts 播放、合成或失败时显示。后端 tts 状态不带说话方，显示为角色；
    摘要没有数据时为空串。 */
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

/** 账号门：默认账号（未设密码）进账号门；非默认账号且引导未完成时进首次引导。 */
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

interface DialogueConfigShape {
  provider?: string;
  model?: string;
  base_url?: string;
  api_key_masked?: string;
  reasoning_effort?: string;
  /** 后端判定当前服务商是否可用及其不可用原因，前端只做展示。 */
  provider_supported?: boolean;
  provider_unavailable?: { code?: string; message?: string } | null;
}

interface ConfigShape {
  dialogue?: DialogueConfigShape;
  voice?: Record<string, unknown>;
}

/** 后端 dialogue.provider_unavailable 投影：只有带非空 message 的对象才是可用文案，
    其余（null / 缺字段 / 空 message）一律为 null，前端不编造替代文案。 */
function presentProviderUnavailable(
  value: { code?: string; message?: string } | null | undefined,
): { code: string; message: string } | null {
  if (!value || typeof value.message !== "string" || !value.message) return null;
  return {
    code: typeof value.code === "string" ? value.code : "",
    message: value.message,
  };
}

/** VAD 运行时状态：语音运行时不可用或 VAD 模型不可用为 unavailable，正在聆听或识别为 running。 */
function presentVadStatus(voice: VoiceState): VoicePageView["vadStatus"] {
  if (!voice.supported || voice.vad === "unavailable") return "unavailable";
  return voice.vad === "idle" ? "ready" : "running";
}

/** 角色音色依赖当前账号保存的 DashScope Key 与服务地址（config.get 的 credential_source=account）。 */
function presentVoiceConfigured(config: Record<string, unknown> | null): boolean {
  const voice = (config as ConfigShape | null)?.voice;
  return (
    voice?.credential_source === "account" &&
    typeof voice.base_url === "string" &&
    voice.base_url.length > 0
  );
}

/** 设置中心各页视图：由 configSnapshot 映射，尚未拉取配置时给空值。 */
function presentSettings(state: DesktopRenderState): AppShellViewModel["settings"] {
  const config = state.configSnapshot as ConfigShape | null;
  const dialogue = config?.dialogue ?? {};
  const voiceConfig = config?.voice ?? {};
  const reasoningEffort =
    typeof dialogue.reasoning_effort === "string" ? dialogue.reasoning_effort : "auto";

  // 多标签窗口以本窗口活动会话为准；currentConversationId 是 Sidecar 全局指针，
  // 可能指向其他窗口的会话。
  const currentConv =
    state.conversationsById[state.activeConversationId ?? state.currentConversationId];
  const activePairId = currentConv?.pair_id || state.pair?.pair_id;
  const activePair =
    state.pairs.find((p) => p.pair_id === activePairId) ?? state.pair;

  // 音色以 config.get 为准；尚未拉取配置时显示快照里搭档的 voice_id。
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
    vadStatus: presentVadStatus(state.voice),
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
    model: {
      provider: String(dialogue.provider ?? ""),
      model: String(dialogue.model ?? ""),
      baseUrl: String(dialogue.base_url ?? ""),
      apiKeyMasked: String(dialogue.api_key_masked ?? ""),
      reasoningEffort,
      // 只有后端明确给出 false 才判定不可用；未上报该字段不当作不可用。
      providerSupported: dialogue.provider_supported !== false,
      providerUnavailable: presentProviderUnavailable(dialogue.provider_unavailable),
    },
    voice,
    characterVoice: presentCharacterCardVoicePage(state),
    modelTest: idle,
    voicePreview: idle,
  };
}

/** 工作台时间线：助手 segment 与工具卡按 timeline_order 混排。 */
function presentWorkbenchItems(
  messages: Message[],
  tools: ToolRun[],
): WorkbenchItem[] {
  const messageItems: WorkbenchItem[] = messages
    .filter((message) => message.source !== "tool")
    .map((message) => ({ kind: "message" as const, order: message.timeline_order, message }));
  const toolItems: WorkbenchItem[] = tools.map((run) => ({
    kind: "tool" as const,
    order: run.timeline_order,
    run,
  }));
  return [...messageItems, ...toolItems].sort((a, b) => a.order - b.order);
}

/** 聊天标签视图：标题取自会话记录，状态点只反映该聊天自己的运行、排队与待审批。 */
function presentChatTabs(state: DesktopRenderState): ChatTabsViewModel[] {
  return state.openConversationIds.map((conversationId) => {
    const conversation = state.conversationsById[conversationId];
    return {
      conversationId,
      title: conversation.title,
      isRunning: Boolean(state.activeTasksByConversation[conversationId]),
      isQueued: (state.queueItemsByConversation[conversationId] ?? []).some(
        (item) => item.status === "queued" || item.status === "processing",
      ),
      isWaitingApproval: state.approvals.some(
        (approval) => approval.conversation_id === conversationId,
      ),
      isActive: conversationId === state.activeConversationId,
    };
  });
}

/** 语音设置页「角色音色」区视图模型，卡列表来自 characterLibrary。 */
export function presentCharacterCardVoicePage(
  state: DesktopRenderState,
): CharacterCardVoicePageViewModel {
  const cards = state.characterLibrary.cards.map((card): CharacterCardVoicePageViewModel["cards"][number] => ({
    cardId: card.cardId,
    name: card.name,
    state: card.state,
    source: card.source,
    hasAvatar: card.hasAvatar,
    voiceState: card.voiceState,
    active: card.active,
    readOnly: card.readOnly,
  }));
  return { voiceConfigured: presentVoiceConfigured(state.configSnapshot), cards };
}

export function presentAppShell(state: DesktopRenderState): AppShellViewModel {
  // 工作区渲染本窗口活动标签；没有打开的标签时为空状态。
  const workspaceConversationId = state.activeConversationId;
  const workspaceConversation = workspaceConversationId
    ? state.conversationsById[workspaceConversationId]
    : undefined;
  // 项目级活动标记：该项目下任一聊天有活动任务即点亮。
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
      conversations: project.conversations.map(
        (conversation): ConversationViewModel => ({
          ...conversation,
          isCurrent: conversation.conversation_id === navigationConversationId,
          isRunning: Boolean(state.activeTasksByConversation[conversation.conversation_id]),
        }),
      ),
    };
  });

  // 消息空间归属：user+target=assistant 与 assistant、tool 归工作台；
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
  // 审批模式与推理档位是项目设置，取本窗口活动标签所属项目。
  const windowProjectId = selectWindowProjectId(state);
  const windowProject = windowProjectId ? state.projectsById[windowProjectId] : undefined;
  const approvalMode = windowProject?.approval_mode ?? "request_approval";
  const review = workspaceConversationId
    ? state.reviewByConversation[workspaceConversationId]
    : undefined;
  const currentPairId = workspaceConversation?.pair_id ?? state.pair?.pair_id ?? null;

  return {
    status: state.status,
    resyncing: state.resyncing,
    theme: state.theme,
    currentPairId,
    navigation: state.pair
      ? {
          projects,
          currentProjectId: state.currentProjectId,
          currentConversationId: navigationConversationId,
          currentPair: state.pair,
          pairs: state.pairs,
        }
      : null,
    chatTabs: presentChatTabs(state),
    workspace: workspaceConversation
      ? {
          mode: selectWindowMode(state),
          character: {
            conversationId: workspaceConversation.conversation_id,
            messages: characterMessages,
            isStreaming: characterMessages.some((message) => message.streaming === true),
            queueItems: queuedItemsFor(state, workspaceConversation.conversation_id),
          },
          assistant: {
            conversationId: workspaceConversation.conversation_id,
            messages: assistantMessages,
            toolRuns: assistantTools,
            items: presentWorkbenchItems(assistantMessages, assistantTools),
            busy: state.busy,
            activeTask: state.activeTask,
          },
          delegation: presentDelegation(state, workspaceConversation.conversation_id),
        }
      : null,
    composer: {
      target: selectComposerTarget(state),
      enabled: state.status === "ready" && workspaceConversation !== undefined,
      approvalMode,
      reasoningEffort: windowProject?.reasoning_effort ?? "low",
      asrPartial: state.voice.asr_partial,
    },
    approval: {
      mode: approvalMode,
      pending: state.approvals.map((approval) => ({
        ...approval,
        resolving: Boolean(state.approvalResolvingById[approval.approval_id]),
      })),
      reviewActive: review?.active ?? false,
      reviewText: review?.text ?? null,
    },
    voice: {
      ...state.voice,
      canPushToTalk: state.status === "ready",
    },
    error: state.error,
    queueItems: workspaceConversationId ? presentQueueItems(state, workspaceConversationId) : [],
    toasts: state.toasts as ToastItem[],
    voiceMiniPlayer: presentVoiceMiniPlayer(state),
    accountGate: presentAccountGate(state),
    onboarding:
      state.currentAccount !== null &&
      state.currentAccount.username !== "default" &&
      state.currentAccount.onboarding_complete === false,
    settings: presentSettings(state),
    // 角色卡与远程配对在 store 层已按视图模型形状维护，直接透传。
    mainView: state.mainView,
    characterLibrary: state.characterLibrary,
    characterCreate: state.characterCreate,
    remotePairing: state.remotePairing,
  };
}
