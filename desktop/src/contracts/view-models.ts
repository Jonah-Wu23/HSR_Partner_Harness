import type {
  QueueItem,
  ActiveTask,
  ApprovalMode,
  CharacterCardSource,
  ConversationRecord,
  Message,
  PairRecord,
  PairSummary,
  PendingApproval,
  ProjectRecord,
  ReasoningEffort,
  ToolRun,
  VoiceState,
} from "./protocol";
// 视图类型以 ui/*/types.ts 为准，这里只做类型级引用。
import type { ToastItem, QueueItemView } from "../ui/status/types";
import type { DelegationCardView } from "../ui/workspace/DelegationCard";
import type { VoiceMiniPlayerView } from "../ui/composer/VoiceMiniPlayer";
import type { AccountListItem } from "../ui/gate/types";
import type {
  AccountPageView,
  CharacterModelPageView,
  TestResult,
  VoicePageView,
} from "../ui/settings/types";

export type { PromptAssemblyModule, PromptAssemblyView } from "../ui/diagnostics/types";

export interface ProjectViewModel extends Omit<ProjectRecord, "conversations"> {
  conversations: ConversationViewModel[];
  isCurrent: boolean;
  /** 该项目下任一聊天有活动任务。 */
  isBusy: boolean;
  /** 该项目下运行中的聊天数。 */
  activeTaskCount: number;
}

export interface ConversationViewModel extends ConversationRecord {
  isCurrent: boolean;
  /** 该聊天有活动任务。 */
  isRunning: boolean;
}

/** 聊天标签视图：标题随 conversation.changed 更新，状态点只反映该聊天自己的运行、排队与待审批。 */
export interface ChatTabsViewModel {
  conversationId: string;
  title: string;
  isRunning: boolean;
  /** 该聊天有排队中或执行中的队列项。 */
  isQueued: boolean;
  /** 该聊天有待审批项。 */
  isWaitingApproval: boolean;
  isActive: boolean;
  /** 已用缓存切到该聊天，正在等待 conversation.open 的权威结果。 */
  isSyncing: boolean;
}

export interface NavigationViewModel {
  projects: ProjectViewModel[];
  currentProjectId: string;
  currentConversationId: string;
  currentPair: PairRecord;
  pairs: PairSummary[];
}

export interface ConversationTimelineViewModel {
  conversationId: string;
  messages: Message[];
  isStreaming: boolean;
  /** 忙时排队的用户消息全文，显示在消息流尾部。 */
  queueItems: QueueItem[];
}

/** 工作台时间线条目：助手 segment 与工具卡按 timeline_order 混排。 */
export type WorkbenchItem =
  | { kind: "message"; order: number; message: Message }
  | { kind: "tool"; order: number; run: ToolRun };

export interface AssistantWorkbenchViewModel {
  conversationId: string;
  messages: Message[];
  toolRuns: ToolRun[];
  /** Workspace 的渲染来源。 */
  items: WorkbenchItem[];
  busy: boolean;
  activeTask: ActiveTask | null;
}

/** summary.failed 留下的重新生成目标。 */
export interface SummaryRegenerateTarget {
  summary_id: string;
  conversation_id: string;
}

export interface WorkspaceViewModel {
  mode: "chat" | "collaboration";
  character: ConversationTimelineViewModel;
  assistant: AssistantWorkbenchViewModel;
  /** 角色发起的委派卡；无委派时为 null。 */
  delegation: DelegationCardView | null;
}

export interface ComposerViewModel {
  target: "character" | "assistant";
  enabled: boolean;
  approvalMode: ApprovalMode;
  reasoningEffort: ReasoningEffort;
  asrPartial: string;
}

export interface ApprovalViewModel {
  mode: ApprovalMode;
  pending: Array<PendingApproval & { resolving: boolean }>;
  reviewActive: boolean;
  reviewText: string | null;
}

export interface VoiceViewModel extends VoiceState {
  canPushToTalk: boolean;
}

/** 账号门：当前账号是默认账号（username=default）时非空。 */
export interface AccountGateViewModel {
  accounts: AccountListItem[];
  error: string | null;
  busy: boolean;
}

/** 设置中心各页数据与测试结果。 */
export interface SettingsViewModel {
  account: AccountPageView;
  model: CharacterModelPageView;
  voice: VoicePageView;
  /** 语音页「角色音色」区数据。 */
  characterVoice: CharacterCardVoicePageViewModel;
  modelTest: TestResult;
  voicePreview: TestResult;
}

/* 角色卡与手机远程的 camelCase 视图模型；线缆类型见 contracts/protocol.ts。 */

/** 主工作区视图：聊天 / 角色库 / 角色创作。 */
export type MainView = "chat" | "characters" | "characterCreate";

/** 角色卡列表项（card.list 摘要的 camelCase 投影）。 */
export interface CharacterCardSummaryView {
  cardId: string;
  name: string;
  state: "draft" | "saved" | "imported" | "invalid";
  source: CharacterCardSource;
  updatedAt: string;
  hasAvatar: boolean;
  voiceState: "voice_unconfigured" | "voice_creating" | "voice_ready" | "voice_failed";
  active: boolean;
  readOnly: boolean;
  archived: boolean;
}

export interface CharacterLibraryViewModel {
  cards: CharacterCardSummaryView[];
  loading: boolean;
  error: string | null;
  /** 至少完成过一次真实 card.list。 */
  loaded: boolean;
}

export interface CharacterCreateViewModel {
  /** 正在编辑的草稿/卡 id；全新未保存为 null。 */
  cardId: string | null;
  /** card.get 载入的 v3 JSON（编辑已有卡时非空）。 */
  card: Record<string, unknown> | null;
  readOnly: boolean;
  loading: boolean;
  error: string | null;
}

/** 语音设置页「角色音色」区的单张卡；参考音频与音色详情由该区经 card.get 读取。 */
export interface CharacterCardVoiceView {
  cardId: string;
  name: string;
  state: "draft" | "saved" | "imported" | "invalid";
  source: CharacterCardSource;
  hasAvatar: boolean;
  voiceState: "voice_unconfigured" | "voice_creating" | "voice_ready" | "voice_failed";
  active: boolean;
  readOnly: boolean;
}

/** 语音设置页「角色音色」区视图模型。 */
export interface CharacterCardVoicePageViewModel {
  /** 当前账号已保存 DashScope Key 与服务地址。 */
  voiceConfigured: boolean;
  /** 可选角色卡（内置、自建与导入）。 */
  cards: CharacterCardVoiceView[];
}

export interface RemoteDeviceView {
  deviceName: string;
  issuedAt: string;
  lastUsedAt: string;
  expiresAt?: string;
  revoked: boolean;
}

export type TunnelState = "off" | "downloading" | "starting" | "ready" | "failed";

export interface TunnelViewModel {
  state: TunnelState;
  publicUrl: string | null;
  hostname: string | null;
  error: string | null;
  /** 停止隧道或查询状态的请求失败原文；隧道状态本身不因此改变。 */
  requestError: string | null;
  loading: boolean;
}

export interface RemotePairingViewModel {
  code: string | null;
  ttlSeconds: number;
  /** 配对码生成时刻（本地 epoch ms），用于倒计时展示。 */
  issuedAtEpochMs: number | null;
  devices: RemoteDeviceView[];
  loading: boolean;
  error: string | null;
  /** Sidecar --serve 上报的监听地址，二维码按它生成；null 表示没有可用的局域网接入地址。 */
  serveAddress: {
    host: string;
    port: number;
    mode?: "loopback" | "lan" | null;
    tls?: boolean | null;
  } | null;
  /** serve.started 上报的监听端口（host 为 null 时端口依然真实）。 */
  servePort?: number | null;
  /** serve.started 上报的运行模式。 */
  serveMode?: "loopback" | "lan" | null;
  /** 服务已监听但无可用局域网地址时服务端给出的原因码，如 no_lan_address。 */
  serveUnavailableReason?: string | null;
  /** error.reported(serve_start_failed) 的报文。 */
  serveFailure?: string | null;
  /** Cloudflare Quick Tunnel 公网隧道状态。 */
  tunnel: TunnelViewModel;
  /** 每次配对成功（remote.paired）加 1，面板据此重拉设备列表。 */
  devicesRevision?: number;
}

export interface AppShellViewModel {
  status: "booting" | "ready" | "disconnected" | "error";
  /** 序号缺口后正在重新同步快照；界面保持可用。 */
  resyncing: boolean;
  theme: "dark" | "light";
  /** 当前搭档 id；快照装载前为 null。 */
  currentPairId: string | null;
  navigation: NavigationViewModel | null;
  workspace: WorkspaceViewModel | null;
  /** 本窗口聊天标签，顺序即标签顺序。 */
  chatTabs: ChatTabsViewModel[];
  composer: ComposerViewModel;
  approval: ApprovalViewModel;
  voice: VoiceViewModel;
  error: string | null;
  /** 当前聊天未撤回的队列项。 */
  queueItems: QueueItemView[];
  toasts: ToastItem[];
  /** 语音迷你播放条；朗读空闲时为 null。 */
  voiceMiniPlayer: VoiceMiniPlayerView | null;
  /** 账号门；非默认账号时为 null。 */
  accountGate: AccountGateViewModel | null;
  /** 非默认账号且引导未完成时显示首次引导。 */
  onboarding: boolean;
  settings: SettingsViewModel;
  mainView: MainView;
  characterLibrary: CharacterLibraryViewModel;
  characterCreate: CharacterCreateViewModel;
  /** 设置中心「远程设备」页数据。 */
  remotePairing: RemotePairingViewModel;
}
