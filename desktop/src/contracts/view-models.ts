import type {
  ActiveTask,
  ApprovalMode,
  ConversationRecord,
  Message,
  PairRecord,
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
  isBusy: boolean;
}

export interface ConversationViewModel extends ConversationRecord {
  isCurrent: boolean;
  isTaskOrigin: boolean;
}

export interface NavigationViewModel {
  projects: ProjectViewModel[];
  currentProjectId: string;
  currentConversationId: string;
  currentPair: PairRecord;
}

export interface ConversationTimelineViewModel {
  conversationId: string;
  messages: Message[];
  isStreaming: boolean;
}

export interface AssistantWorkbenchViewModel {
  conversationId: string;
  messages: Message[];
  toolRuns: ToolRun[];
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
  navigation: NavigationViewModel | null;
  workspace: WorkspaceViewModel | null;
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
