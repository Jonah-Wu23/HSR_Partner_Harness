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
}
