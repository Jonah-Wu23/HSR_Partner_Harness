import type {
  ActiveTask,
  ApprovalMode,
  ConversationRecord,
  Message,
  PairRecord,
  PairSummary,
  PendingApproval,
  ProjectRecord,
  ToolRun,
  VoiceState,
} from "./protocol";
// V0.2 M4：视图类型按视觉线冻结的形状走（ui/*/types.ts 是唯一权威），
// 这里只做类型级引用（import type 编译期擦除，无运行时依赖）。
import type { ToastItem, QueueItemView } from "../ui/status/types";
import type { DelegationCardView } from "../ui/workspace/DelegationCard";
import type { VoiceMiniPlayerView } from "../ui/composer/VoiceMiniPlayer";
import type { AccountListItem } from "../ui/gate/types";
import type {
  AccountPageView,
  CharacterModelPageView,
  CodingAssistantPageView,
  TestResult,
  VoicePageView,
} from "../ui/settings/types";

export interface ProjectViewModel extends ProjectRecord {
  isCurrent: boolean;
  /** V0.3.2 M5：该项目下任一聊天有活动任务即为真（多活动任务集合推导）。 */
  isBusy: boolean;
  /** V0.3.2 M5：该项目下运行中的聊天数（项目级活动标记可附数量）。 */
  activeTaskCount: number;
}

export interface ConversationViewModel extends ConversationRecord {
  isCurrent: boolean;
  /** V0.3.2 M5：该聊天在 activeTasksByConversation 中（运行中）。 */
  isRunning: boolean;
  /** 兼容旧字段：与 isRunning 同值（任务源聊天标记）。 */
  isTaskOrigin: boolean;
}

/** V0.3.2 M5：聊天标签视图——标题随 conversation.changed 实时更新，
    状态点反映该聊天自己的运行/排队/待审批状态。 */
export interface ChatTabsViewModel {
  conversationId: string;
  title: string;
  isRunning: boolean;
  /** queueItemsByConversation 有未撤回项。 */
  isQueued: boolean;
  /** approvals 中存在该聊天的待审批项。 */
  isWaitingApproval: boolean;
  isActive: boolean;
  /** 由容器（AppShell）注入的关闭回调；presenters 保持纯数据投影。 */
  onClose?: () => void;
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
}

/** V0.3.2 M1：工作台统一时间线条目——助手 segment 与工具卡按真实事件顺序混排。 */
export type WorkbenchItem =
  | { kind: "message"; order: number | null; message: Message }
  | { kind: "tool"; order: number | null; run: ToolRun };

export interface AssistantWorkbenchViewModel {
  conversationId: string;
  messages: Message[];
  toolRuns: ToolRun[];
  /** V0.3.2 M1：统一混排时间线（Workspace 唯一渲染来源）。 */
  items: WorkbenchItem[];
  busy: boolean;
  activeTask: ActiveTask | null;
}

export interface WorkspaceViewModel {
  mode: "chat" | "collaboration";
  character: ConversationTimelineViewModel;
  assistant: AssistantWorkbenchViewModel;
  /** V0.2 M4：委派卡（角色区与工作台之间的视觉桥梁）；无委派时为 null。 */
  delegation: DelegationCardView | null;
}

export interface ComposerViewModel {
  target: "character" | "assistant";
  draft: string;
  enabled: boolean;
  approvalMode: ApprovalMode;
  reasoningEffort: string;
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

/** V0.2 M4：账号门（当前账号为默认账号 username=default 时非空）。 */
export interface AccountGateViewModel {
  accounts: AccountListItem[];
  error: string | null;
  busy: boolean;
}

/** V0.2 M4：设置中心四个页 + 测试结果（modelTest/voicePreview 初值 idle）。 */
export interface SettingsViewModel {
  account: AccountPageView;
  coding: CodingAssistantPageView;
  model: CharacterModelPageView;
  voice: VoicePageView;
  modelTest: TestResult;
  voicePreview: TestResult;
}

/* ------------------------------------------------------------------ *
 * V0.3.3 角色卡与手机远程视图（线缆类型见 contracts/protocol.ts，
 * 本文件为 camelCase 视图模型，由 store/presenters 投影维护）。
 * ------------------------------------------------------------------ */

/** 主工作区视图：聊天 / 角色库 / 角色创作。 */
export type MainView = "chat" | "characters" | "characterCreate";

/** 角色卡列表项。archived 不由 card.list 直接携带——
    由 actions 层对 include_archived 两次结果做差集推导。 */
export interface CharacterCardSummaryView {
  cardId: string;
  name: string;
  state: "draft" | "saved" | "imported" | "invalid";
  source: "builtin" | "user_created" | "imported_json" | "imported_png";
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

export interface RemoteDeviceView {
  deviceName: string;
  issuedAt: string;
  lastUsedAt: string;
  revoked: boolean;
}

export interface RemotePairingViewModel {
  code: string | null;
  ttlSeconds: number;
  /** 配对码生成时刻（本地 epoch ms），用于倒计时展示。 */
  issuedAtEpochMs: number | null;
  devices: RemoteDeviceView[];
  loading: boolean;
  error: string | null;
  /** V0.3.4：Sidecar --serve 实际监听地址（serve.started 事件上报），
      二维码按它生成；null 表示远程服务未就绪（serve 未启动/启动失败）。 */
  serveAddress: { host: string; port: number } | null;
}

export interface AppShellViewModel {
  status: "booting" | "ready" | "disconnected" | "error";
  theme: "dark" | "light";
  currentPairId: string;
  navigation: NavigationViewModel | null;
  workspace: WorkspaceViewModel | null;
  /** V0.3.2 M5：本窗口聊天标签（顺序即标签顺序；无标签为空数组）。 */
  chatTabs: ChatTabsViewModel[];
  composer: ComposerViewModel;
  approval: ApprovalViewModel;
  voice: VoiceViewModel;
  error: string | null;
  /** V0.2 M4：排队条（当前会话未撤回的队列项映射）。 */
  queueItems: QueueItemView[];
  /** V0.2 M4：Toast 队列（store 透传）。 */
  toasts: ToastItem[];
  /** V0.2 M4：语音迷你播放条（tts playing/synthesizing/failed 时非空）。 */
  voiceMiniPlayer: VoiceMiniPlayerView | null;
  /** V0.2 M4：账号门；非默认账号时为 null。 */
  accountGate: AccountGateViewModel | null;
  /** V0.2 M4：首次引导（非默认账号且 onboarding_complete=false）。 */
  onboarding: boolean;
  /** V0.2 M4：设置中心数据源（configSnapshot 映射）。 */
  settings: SettingsViewModel;
  /** V0.3.3：主工作区视图切换。 */
  mainView: MainView;
  /** V0.3.3：角色库页数据。 */
  characterLibrary: CharacterLibraryViewModel;
  /** V0.3.3：角色创作页数据。 */
  characterCreate: CharacterCreateViewModel;
  /** V0.3.3：设置中心「远程设备」页数据源。 */
  remotePairing: RemotePairingViewModel;
}
