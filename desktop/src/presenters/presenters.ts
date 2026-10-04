import type {
  AppShellViewModel,
  ApprovalViewModel,
  AssistantWorkbenchViewModel,
  CharacterCardVoicePageViewModel,
  ChatTabsViewModel,
  ComposerViewModel,
  ConversationTimelineViewModel,
  ConversationViewModel,
  NavigationViewModel,
  ProjectViewModel,
  VoiceViewModel,
  WorkbenchItem,
  WorkspaceViewModel,
} from "../contracts/view-models";
import type {
  ActiveTask,
  Message,
  PairRecord,
  QueueItem,
  ToolRun,
  VoiceState,
} from "../contracts/protocol";
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

/* 视图模型按输入引用缓存：输入没变的部分沿用上次的对象，React.memo 的区域据此跳过渲染。 */

function sameItems<T>(left: readonly T[], right: readonly T[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 新结果与上次结果逐字段（数组逐项）同一引用时沿用上次结果。 */
function keepIfShallowEqual<T>(previous: T, next: T): T {
  if (Array.isArray(previous) && Array.isArray(next)) {
    return sameItems(previous, next) ? previous : next;
  }
  if (!isRecord(previous) || !isRecord(next)) return next;
  const keys = Object.keys(next);
  return keys.length === Object.keys(previous).length &&
    keys.every((key) => Object.is(previous[key], next[key]))
    ? previous
    : next;
}

/** 参数逐个与上次同一引用时沿用上次结果。 */
function memoLast<A extends unknown[], R>(compute: (...args: A) => R): (...args: A) => R {
  let lastArgs: A | null = null;
  let lastResult = undefined as R;
  return (...args) => {
    if (lastArgs !== null && args.every((arg, index) => Object.is(arg, lastArgs![index]))) {
      return lastResult;
    }
    lastArgs = args;
    lastResult = keepIfShallowEqual(lastResult, compute(...args));
    return lastResult;
  };
}

/** 只读取 state 中 keys 字段的投影：这些字段都与上次同一引用时沿用上次结果。 */
function memoByFields<K extends keyof DesktopRenderState, R>(
  keys: readonly K[],
  compute: (input: Pick<DesktopRenderState, K>) => R,
): (state: DesktopRenderState) => R {
  let lastInput: Pick<DesktopRenderState, K> | null = null;
  let lastResult = undefined as R;
  return (state) => {
    if (lastInput !== null && keys.every((key) => Object.is(state[key], lastInput![key]))) {
      return lastResult;
    }
    lastInput = state;
    lastResult = keepIfShallowEqual(lastResult, compute(state));
    return lastResult;
  };
}

/**
 * 按 orderOf 升序排列。输入与上次逐项相同时沿用上次结果；
 * 长度不变且变化的条目序号不变时（流式更新正文）沿用上次的排列，免去重新排序。
 */
function createSortedList<T>(orderOf: (entry: T) => number): (entries: readonly T[]) => T[] {
  let lastEntries: readonly T[] = [];
  let lastPermutation: number[] = [];
  let lastSorted: T[] = [];
  return (entries) => {
    if (entries.length === lastEntries.length) {
      let changed = false;
      let reordered = false;
      for (let index = 0; index < entries.length && !reordered; index += 1) {
        if (entries[index] === lastEntries[index]) continue;
        changed = true;
        reordered = orderOf(entries[index]) !== orderOf(lastEntries[index]);
      }
      if (!changed) return lastSorted;
      if (!reordered) {
        lastEntries = entries;
        lastSorted = lastPermutation.map((index) => entries[index]);
        return lastSorted;
      }
    }
    const permutation = entries
      .map((_, index) => index)
      .sort((left, right) => orderOf(entries[left]) - orderOf(entries[right]));
    lastEntries = entries;
    lastPermutation = permutation;
    lastSorted = permutation.map((index) => entries[index]);
    return lastSorted;
  };
}

/** 队列项摘要：压缩空白后的单行文本，超 24 字截断加省略号。 */
function truncateSingleLine(text: string, max = 24): string {
  const compact = text.replace(/\s+/g, " ").trim();
  return compact.length <= max ? compact : `${compact.slice(0, max)}…`;
}

/** 未撤回的排队项（完整文本，按 position 升序），显示在消息流尾部；
    队列条用 presentQueueItems 的截断摘要。 */
function queuedItems(items: readonly QueueItem[]): QueueItem[] {
  return items
    .filter((item) => item.status !== "withdrawn")
    .sort((a, b) => a.position - b.position);
}

/** 排队条视图：本窗口聊天未撤回的队列项按 position 升序。waitingFor 按真实状态派生；
    派发失败的项不再等待，只显示失败原因，也不计入后面各项的等待数。 */
function presentQueueItems(
  state: Pick<
    DesktopRenderState,
    "queueItemsByConversation" | "activeTasksByConversation" | "activeConversationId"
  >,
): QueueItemView[] {
  const conversationId = state.activeConversationId;
  if (!conversationId) return [];
  const ordered = queuedItems(state.queueItemsByConversation[conversationId] ?? []);
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
  pair: PairRecord | null,
  messages: readonly Message[],
  activeTask: ActiveTask | null,
): DelegationCardView | null {
  if (!pair) return null;
  let delegationMessage: Message | undefined;
  for (const message of messages) {
    if (
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
    activeTask?.task_id === delegationMessage.delegation_id ||
    executionStatus === "processing"
      ? "running"
      : executionStatus === "failed"
        ? "failed"
        : executionStatus === "cancelled"
          ? "cancelled"
          : "completed";
  return {
    delegationId: delegationMessage.delegation_id ?? "",
    fromName: pair.character.name,
    summary: delegationMessage.text,
    status,
  };
}

/** 语音迷你播放条：tts 播放、合成或失败时显示。后端 tts 状态不带说话方，显示为角色；
    摘要没有数据时为空串。 */
function presentVoiceMiniPlayer(
  state: Pick<DesktopRenderState, "pair" | "voice">,
): VoiceMiniPlayerView | null {
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
function presentAccountGate(
  state: Pick<DesktopRenderState, "currentAccount" | "accounts" | "status">,
): AppShellViewModel["accountGate"] {
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
const SETTINGS_FIELDS = [
  "configSnapshot",
  "conversationsById",
  "activeConversationId",
  "currentConversationId",
  "pair",
  "pairs",
  "currentAccountId",
  "currentAccount",
  "voice",
  "characterLibrary",
] as const;

function presentSettings(
  state: Pick<DesktopRenderState, (typeof SETTINGS_FIELDS)[number]>,
): AppShellViewModel["settings"] {
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

/** 工作台条目按消息或工具记录对象缓存，同一条记录始终对应同一个条目对象。 */
const workbenchItems = new WeakMap<Message | ToolRun, WorkbenchItem>();

function workbenchItem(source: Message | ToolRun, create: () => WorkbenchItem): WorkbenchItem {
  let item = workbenchItems.get(source);
  if (item === undefined) {
    item = create();
    workbenchItems.set(source, item);
  }
  return item;
}

/** 消息空间归属：user+target=assistant 与 assistant、tool 归工作台；
    user+target=character、character、system 归角色区。 */
function inCharacterSpace(message: Message): boolean {
  return (
    (message.source === "user" && message.target !== "assistant") ||
    message.source === "character" ||
    message.source === "system"
  );
}

function inAssistantSpace(message: Message): boolean {
  return (
    (message.source === "user" && message.target === "assistant") ||
    message.source === "assistant" ||
    message.source === "tool"
  );
}

const NO_IDS: string[] = [];

/** 工作区两栏：流式分片只换掉变化的消息对象，另一栏与未变化的消息沿用上次的对象。 */
function createWorkspacePresenter(): (state: DesktopRenderState) => WorkspaceViewModel | null {
  const sortMessages = createSortedList<Message>((message) => message.timeline_order);
  const conversationMessages = memoLast(
    (ids: readonly string[], messagesById: Record<string, Message>) =>
      sortMessages(ids.map((id) => messagesById[id])),
  );
  const characterMessages = memoLast((messages: Message[]) => messages.filter(inCharacterSpace));
  const assistantMessages = memoLast((messages: Message[]) => messages.filter(inAssistantSpace));
  const conversationTools = memoLast(
    (ids: readonly string[], toolRunsById: Record<string, ToolRun>) =>
      ids.map((id) => toolRunsById[id]),
  );
  const timelineQueue = memoLast((items: readonly QueueItem[] | undefined) =>
    items ? queuedItems(items) : [],
  );
  const sortWorkbench = createSortedList<WorkbenchItem>((item) => item.order);
  // 工作台时间线：助手 segment 与工具卡按 timeline_order 混排。
  const workbenchTimeline = memoLast((messages: Message[], tools: ToolRun[]) =>
    sortWorkbench([
      ...messages
        .filter((message) => message.source !== "tool")
        .map((message) =>
          workbenchItem(message, () => ({ kind: "message", order: message.timeline_order, message })),
        ),
      ...tools.map((run) => workbenchItem(run, () => ({ kind: "tool", order: run.timeline_order, run }))),
    ]),
  );
  const character = memoLast(
    (conversationId: string, messages: Message[], queueItems: QueueItem[]): ConversationTimelineViewModel => ({
      conversationId,
      messages,
      isStreaming: messages.some((message) => message.streaming === true),
      queueItems,
    }),
  );
  const assistant = memoLast(
    (
      conversationId: string,
      messages: Message[],
      toolRuns: ToolRun[],
      busy: boolean,
      activeTask: ActiveTask | null,
    ): AssistantWorkbenchViewModel => ({
      conversationId,
      messages,
      toolRuns,
      items: workbenchTimeline(messages, toolRuns),
      busy,
      activeTask,
    }),
  );
  const delegation = memoLast(presentDelegation);
  const workspace = memoLast(
    (
      mode: WorkspaceViewModel["mode"],
      characterView: ConversationTimelineViewModel,
      assistantView: AssistantWorkbenchViewModel,
      delegationView: DelegationCardView | null,
    ): WorkspaceViewModel => ({
      mode,
      character: characterView,
      assistant: assistantView,
      delegation: delegationView,
    }),
  );

  return (state) => {
    // 工作区渲染本窗口活动标签；没有打开的标签时为空状态。
    const conversationId = state.activeConversationId;
    if (!conversationId || !state.conversationsById[conversationId]) return null;
    const messages = conversationMessages(
      state.messageIdsByConversation[conversationId] ?? NO_IDS,
      state.messagesById,
    );
    const characterSpace = characterMessages(messages);
    const assistantSpace = assistantMessages(messages);
    const tools = conversationTools(
      state.toolIdsByConversation[conversationId] ?? NO_IDS,
      state.toolRunsById,
    );
    return workspace(
      selectWindowMode(state),
      character(
        conversationId,
        characterSpace,
        timelineQueue(state.queueItemsByConversation[conversationId]),
      ),
      assistant(conversationId, assistantSpace, tools, state.busy, state.activeTask),
      delegation(state.pair, messages, state.activeTask),
    );
  };
}

const NAVIGATION_FIELDS = [
  "projectsById",
  "activeTasksByConversation",
  "currentProjectId",
  "activeConversationId",
  "currentConversationId",
  "pair",
  "pairs",
  "catalogVersion",
] as const;

function presentNavigation(
  state: Pick<DesktopRenderState, (typeof NAVIGATION_FIELDS)[number]>,
): NavigationViewModel | null {
  if (!state.pair) return null;
  // 项目级活动标记：该项目下任一聊天有活动任务即点亮。
  const activeTaskCountByProject: Record<string, number> = {};
  for (const task of Object.values(state.activeTasksByConversation)) {
    activeTaskCountByProject[task.project_id] =
      (activeTaskCountByProject[task.project_id] ?? 0) + 1;
  }
  const navigationConversationId = state.activeConversationId ?? state.currentConversationId;
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
  return {
    projects,
    currentProjectId: state.currentProjectId,
    currentConversationId: navigationConversationId,
    currentPair: state.pair,
    pairs: state.pairs,
    catalogVersion: state.catalogVersion,
  };
}

const CHAT_TAB_FIELDS = [
  "openConversationIds",
  "conversationsById",
  "activeTasksByConversation",
  "queueItemsByConversation",
  "approvals",
  "activeConversationId",
  "syncingConversationIds",
] as const;

/** 聊天标签视图：标题取自会话记录，状态点只反映该聊天自己的运行、排队与待审批。 */
function presentChatTabs(
  state: Pick<DesktopRenderState, (typeof CHAT_TAB_FIELDS)[number]>,
): ChatTabsViewModel[] {
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
      isSyncing: Boolean(state.syncingConversationIds[conversationId]),
    };
  });
}

/** 审批模式与推理档位是项目设置，取本窗口活动标签所属项目。 */
function windowProjectOf(
  state: Pick<DesktopRenderState, "activeProjectId" | "currentProjectId" | "projectsById">,
) {
  const projectId = selectWindowProjectId(state);
  return projectId ? state.projectsById[projectId] : undefined;
}

const COMPOSER_FIELDS = [
  "composerTarget",
  "activeConversationId",
  "conversationsById",
  "status",
  "activeProjectId",
  "currentProjectId",
  "projectsById",
  "voice",
] as const;

function presentComposer(
  state: Pick<DesktopRenderState, (typeof COMPOSER_FIELDS)[number]>,
): ComposerViewModel {
  const windowProject = windowProjectOf(state);
  return {
    target: selectComposerTarget(state),
    enabled:
      state.status === "ready" &&
      state.activeConversationId !== null &&
      state.conversationsById[state.activeConversationId] !== undefined,
    approvalMode: windowProject?.approval_mode ?? "request_approval",
    reasoningEffort: windowProject?.reasoning_effort ?? "low",
    asrPartial: state.voice.asr_partial,
  };
}

const APPROVAL_FIELDS = [
  "approvals",
  "approvalResolvingById",
  "reviewByConversation",
  "activeConversationId",
  "activeProjectId",
  "currentProjectId",
  "projectsById",
] as const;

function presentApproval(
  state: Pick<DesktopRenderState, (typeof APPROVAL_FIELDS)[number]>,
): ApprovalViewModel {
  const review = state.activeConversationId
    ? state.reviewByConversation[state.activeConversationId]
    : undefined;
  return {
    mode: windowProjectOf(state)?.approval_mode ?? "request_approval",
    pending: state.approvals.map((approval) => ({
      ...approval,
      resolving: Boolean(state.approvalResolvingById[approval.approval_id]),
    })),
    reviewActive: review?.active ?? false,
    reviewText: review?.text ?? null,
  };
}

function presentVoice(state: Pick<DesktopRenderState, "voice" | "status">): VoiceViewModel {
  return { ...state.voice, canPushToTalk: state.status === "ready" };
}

/** 语音设置页「角色音色」区视图模型，卡列表来自 characterLibrary。 */
export function presentCharacterCardVoicePage(
  state: Pick<DesktopRenderState, "characterLibrary" | "configSnapshot">,
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

/**
 * 创建带缓存的 AppShell 视图模型投影。各区域只在自己读取的 store 字段变化时重算，
 * 结果与上次逐字段相同时沿用上次的对象；流式分片只换掉工作区里变化的那条消息。
 */
export function createAppShellPresenter(): (state: DesktopRenderState) => AppShellViewModel {
  const navigation = memoByFields(NAVIGATION_FIELDS, presentNavigation);
  const chatTabs = memoByFields(CHAT_TAB_FIELDS, presentChatTabs);
  const workspace = createWorkspacePresenter();
  const composer = memoByFields(COMPOSER_FIELDS, presentComposer);
  const approval = memoByFields(APPROVAL_FIELDS, presentApproval);
  const voice = memoByFields(["voice", "status"], presentVoice);
  const queueItems = memoByFields(
    ["queueItemsByConversation", "activeTasksByConversation", "activeConversationId"],
    presentQueueItems,
  );
  const voiceMiniPlayer = memoByFields(["pair", "voice"], presentVoiceMiniPlayer);
  const accountGate = memoByFields(["currentAccount", "accounts", "status"], presentAccountGate);
  const settings = memoByFields(SETTINGS_FIELDS, presentSettings);
  let previous: AppShellViewModel | null = null;

  return (state) => {
    const workspaceConversation = state.activeConversationId
      ? state.conversationsById[state.activeConversationId]
      : undefined;
    const next: AppShellViewModel = {
      status: state.status,
      resyncing: state.resyncing,
      theme: state.theme,
      currentPairId: workspaceConversation?.pair_id ?? state.pair?.pair_id ?? null,
      navigation: navigation(state),
      chatTabs: chatTabs(state),
      workspace: workspace(state),
      composer: composer(state),
      approval: approval(state),
      voice: voice(state),
      error: state.error,
      queueItems: queueItems(state),
      toasts: state.toasts as ToastItem[],
      voiceMiniPlayer: voiceMiniPlayer(state),
      accountGate: accountGate(state),
      onboarding:
        state.currentAccount !== null &&
        state.currentAccount.username !== "default" &&
        state.currentAccount.onboarding_complete === false,
      settings: settings(state),
      // 角色卡与远程配对在 store 层已按视图模型形状维护，直接透传。
      mainView: state.mainView,
      characterLibrary: state.characterLibrary,
      characterCreate: state.characterCreate,
      remotePairing: state.remotePairing,
    };
    previous = previous === null ? next : keepIfShallowEqual(previous, next);
    return previous;
  };
}

/** 一次性投影，不跨调用缓存。 */
export function presentAppShell(state: DesktopRenderState): AppShellViewModel {
  return createAppShellPresenter()(state);
}
