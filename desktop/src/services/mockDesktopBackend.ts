import type {
  ApprovalResolvedPayload,
  CardAvatarPayload,
  CardSummaryPayload,
  CharacterVoiceState,
  CompatReportPayload,
  ConversationOpenResult,
  ConversationRecord,
  DesktopCommand,
  DesktopEvent,
  DesktopSnapshot,
  DesktopStreamEvent,
  Message,
  MessageDeltaPayload,
  PendingApproval,
  ProjectRecord,
  PowerStatusPayload,
  QueueItem,
  RemoteIssueCodeResult,
  TaskCancelResult,
  ToolRun,
  Turn,
} from "../contracts/protocol";
import type { FileFilter } from "./backend";
import { DesktopRequestError } from "./backend";
import {
  APPROVAL_ALREADY_RESOLVED,
  CARD_AVATAR_UNSUPPORTED,
  CARD_EXPORT_FAILED,
  CARD_IMPORT_FAILED,
  CARD_PUBLISH_INVALID,
  CARD_READ_ONLY,
  VOICE_AUDIO_SEQ_GAP,
  VOICE_CARD_NOT_READY,
  VOICE_CARD_PROVISION_IN_PROGRESS,
  VOICE_NOT_CONFIGURED,
  VOICE_REFERENCE_INVALID,
  VOICE_REFERENCE_MISSING,
  VOICE_TRANSCRIPT_EMPTY,
} from "../contracts/protocol";
import type { DesktopBackend } from "./backend";
import { RequestIdFactory } from "./backend";
import { applyMessageDelta } from "../stores/messageDelta";
import {
  MOCK_STREAM_ID,
  createMockScenario,
  conversation,
  message,
  nextTimelineOrder,
  project,
  type MockScenario,
  type MockScenarioName,
} from "../mocks/scenarios";
import {
  MOCK_BUILTIN_CARDS,
  MOCK_ARCHIVED_CARD_IDS,
  MOCK_REMOTE_DEVICES,
  MOCK_USER_CARDS,
  mockBuiltinCardPayload,
  mockCardPayload,
  type MockCardSummary,
} from "../mocks/characterCards";

/** mock 场景里已有账号的登录密码；默认账号未设密码，空密码登录。注册的账号用注册时的密码。 */
export const MOCK_ACCOUNT_PASSWORD = "mock-password";

const EMPTY_COMPAT_REPORT: CompatReportPayload = {
  applied: [],
  preserved: [],
  not_executed: [],
  normalized_from_root: [],
  warnings: [],
  errors: [],
};

const BUILTIN_PREFIX = "builtin:";

/** voice.card_create 模拟供应商创建音色的耗时（毫秒）。 */
const MOCK_VOICE_PROVIDER_DELAY_MS = 50;

/** mock 不读真实文件：样例卡、card.set_avatar 与 PNG 导入共用这张 1x1 PNG 作头像数据。 */
const PLACEHOLDER_AVATAR_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

/** 与 Sidecar 的 _required_string 一致：缺少或为空白时以 invalid_params 拒绝。 */
function requiredString(params: Record<string, unknown>, key: string): string {
  const value = params[key];
  if (typeof value !== "string" || !value.trim()) {
    throw new DesktopRequestError("invalid_params", `缺少非空参数：${key}`);
  }
  return value;
}

/** card.update 整卡的角色名。mock 只接受带 data 对象的 v3 形状，缺 name 时与 Sidecar 一样拒绝。 */
function cardName(card: Record<string, unknown>): string {
  const data = card.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new DesktopRequestError("card_invalid_payload", "角色卡数据非法：data 必须是 JSON 对象");
  }
  const name = (data as Record<string, unknown>).name;
  if (typeof name !== "string" || name === "") {
    throw new DesktopRequestError(
      "card_invalid_payload",
      "角色卡数据非法：缺少必填字段 name（data 与根级均无有效值）",
    );
  }
  return name;
}

/** 换名后的整卡 JSON（复制卡时名称追加「（副本）」）。 */
function renamedCard(card: Record<string, unknown>, name: string): Record<string, unknown> {
  return { ...card, data: { ...(card.data as Record<string, unknown>), name } };
}

/** mock 后端可配置开关，便于 UI 开发与测试覆盖异常路径。 */
export interface MockDesktopBackendOptions {
  /** 账号是否已配置 voice.api_key/voice.base_url；默认 true。 */
  voiceConfigured?: boolean;
  /** 是否模拟音色创建失败路径；默认 false。 */
  voiceProvisionFail?: boolean;
  /** 手机 PTT 结束是否返回空转写；默认 false。 */
  mobileTranscriptEmpty?: boolean;
  /** pickFile 默认返回值；null 表示用户取消。 */
  pickFileResult?: string | null;
  /** saveFile 默认返回值；null 表示用户取消。 */
  saveFileResult?: string | null;
}

export class MockDesktopBackend implements DesktopBackend {
  private readonly listeners = new Set<(event: DesktopStreamEvent) => void>();
  private readonly requestIds = new RequestIdFactory();
  private scenario: MockScenario;
  private sequence: number;
  /** 记录全部 request 命令，供测试断言接线与参数。 */
  readonly recordedRequests: DesktopCommand[] = [];

  /* 角色卡可变状态，样例数据见 mocks/characterCards。 */
  private cards: MockCardSummary[] = MOCK_USER_CARDS.map((card) => ({ ...card }));
  private archivedCardIds = new Set<string>(MOCK_ARCHIVED_CARD_IDS);
  /** card.get 返回的整卡 JSON；card.update 整体替换。 */
  private cardPayloads = new Map<string, Record<string, unknown>>(
    MOCK_USER_CARDS.map((card) => [card.card_id, mockCardPayload(card.name)]),
  );

  voiceConfigured: boolean;
  voiceProvisionFail: boolean;
  mobileTranscriptEmpty: boolean;
  pickFileResult: string | null;
  saveFileResult: string | null;

  /* 角色卡头像、参考音频与音色状态；样例卡按摘要的 has_avatar 与 voice_state 预置。 */
  private cardAvatars = new Map<string, CardAvatarPayload>(
    MOCK_USER_CARDS.filter((card) => card.has_avatar).map((card) => [
      card.card_id,
      { mime_type: "image/png", data_base64: PLACEHOLDER_AVATAR_BASE64 },
    ]),
  );
  private cardReferenceAudios = new Map<string, { asset_id: string; duration_seconds: number; size_bytes: number; mime_type: string }>();
  private voiceProvisioningCardIds = new Set<string>();
  private voiceProfiles = new Map<string, { voice_id: string; state: CharacterVoiceState }>(
    MOCK_USER_CARDS.filter((card) => card.voice_state !== "voice_unconfigured").map((card) => [
      card.card_id,
      {
        voice_id: card.voice_state === "voice_ready" ? `mock-voice-${card.card_id}` : "",
        state: card.voice_state,
      },
    ]),
  );

  /** 已裁决的审批终态，用于首个终态获胜的仲裁。 */
  private resolvedApprovals = new Map<string, ApprovalResolvedPayload>();

  /** 账号密码（account_id → 密码）；默认账号未设密码。 */
  private passwords = new Map<string, string>();

  /** 当前有效的一次性配对码。 */
  private pairingCode: string | null = null;

  /** 手机转写会话；分片序号从 0 严格递增。 */
  private mobileAudioSessions = new Map<string, { conversation_id: string; expected_seq: number }>();

  /** 最近一次 power.status_changed 载荷，供开发与测试检查。 */
  lastPowerStatus: PowerStatusPayload | null = null;

  constructor(
    scenarioName: MockScenarioName = "single-project",
    options: MockDesktopBackendOptions = {},
  ) {
    this.scenario = createMockScenario(scenarioName);
    this.sequence = this.scenario.snapshot.sequence;
    this.resetPasswords();
    this.voiceConfigured = options.voiceConfigured ?? true;
    this.voiceProvisionFail = options.voiceProvisionFail ?? false;
    this.mobileTranscriptEmpty = options.mobileTranscriptEmpty ?? false;
    this.pickFileResult = options.pickFileResult ?? null;
    this.saveFileResult = options.saveFileResult ?? null;
  }

  setScenario(name: MockScenarioName): void {
    this.scenario = createMockScenario(name);
    this.sequence = this.scenario.snapshot.sequence;
    this.resetPasswords();
  }

  private resetPasswords(): void {
    this.passwords = new Map(
      this.scenario.snapshot.accounts.map((account) => [
        account.account_id,
        account.username === "default" ? "" : MOCK_ACCOUNT_PASSWORD,
      ]),
    );
  }

  get scenarioName(): MockScenarioName {
    return this.scenario.name;
  }

  setVoiceConfigured(configured: boolean): void {
    this.voiceConfigured = configured;
  }

  setVoiceProvisionFail(fail: boolean): void {
    this.voiceProvisionFail = fail;
  }

  setMobileTranscriptEmpty(empty: boolean): void {
    this.mobileTranscriptEmpty = empty;
  }

  setPickFileResult(result: string | null): void {
    this.pickFileResult = result;
  }

  setSaveFileResult(result: string | null): void {
    this.saveFileResult = result;
  }

  async request<T>(command: DesktopCommand, _timeoutSecs?: number | null): Promise<T> {
    this.recordedRequests.push(command);
    switch (command.method) {
      case "app.bootstrap":
        return this.snapshotResult<T>();
      case "app.shutdown":
        return { stopped: true } as T;
      case "project.create":
        return this.createProject(command.params) as T;
      case "project.select":
        return this.selectProject(command.params) as T;
      case "project.update_settings":
        return this.updateProjectSettings(command.params) as T;
      case "project.archive":
        return this.archiveProject(command.params) as T;
      case "conversation.create":
        return this.createConversation(command.params) as T;
      case "conversation.select":
        return this.selectConversation(command.params) as T;
      case "conversation.open":
        return this.openConversation(command.params) as T;
      case "conversation.rename":
        return this.renameConversation(command.params) as T;
      case "conversation.archive":
        return this.archiveConversation(command.params) as T;
      case "conversation.set_mode":
        return this.setConversationMode(command.params) as T;
      case "chat.submit":
        return this.submitMessage(command.params) as T;
      case "queue.edit":
        return this.editQueueItem(command.params) as T;
      case "queue.withdraw":
        return this.withdrawQueueItem(command.params) as T;
      case "queue.prioritize":
        return this.prioritizeQueueItem(command.params) as T;
      case "task.cancel":
        return this.cancelTask(command.params) as T;
      case "approval.resolve":
        return this.resolveApproval(command.params) as T;
      case "voice.vad_set":
        return this.setVoiceState({
          vad_enabled: Boolean(command.params.enabled),
          vad: command.params.enabled ? "listening" : "idle",
        }) as T;
      case "voice.ptt_start":
        return this.setVoiceState({ ptt: true, vad: "listening" }) as T;
      case "voice.ptt_stop":
        return this.setVoiceState({ ptt: false, vad: "idle" }) as T;
      case "voice.tts_stop":
        return this.setVoiceState({ tts: "idle" }) as T;
      case "voice.tts_skip":
        // mock 没有播放队列，跳过当前条等价于停止播放。
        return this.setVoiceState({ tts: "idle" }) as T;
      case "account.list":
        return this.accountList() as T;
      case "account.register":
        return this.accountRegister(command.params) as T;
      case "account.login":
        return this.accountLogin(command.params) as T;
      case "account.logout":
        return this.switchAccount(this.ensureDefaultAccount()) as T;
      case "account.onboarding_complete":
        return this.accountCompleteOnboarding() as T;
      case "account.update_profile":
        return this.updateAccountProfile(command.params) as T;
      case "account.change_password":
        return this.accountChangePassword(command.params) as T;
      case "config.get":
        return this.configGet() as T;
      case "config.set":
        return this.configSet(command.params) as T;
      case "config.test_connection":
        throw new DesktopRequestError(
          "mock_unsupported",
          "Mock 后端不连接真实对话服务，无法测试连接；请在 Tauri + Python Sidecar 中联调",
        );
      case "voice.preview":
        return { voice: this.scenario.snapshot.voice } as T;
      case "voice.provision":
        throw new DesktopRequestError(
          "mock_unsupported",
          "Mock 后端不提供真实音色生成；请在 Tauri + Python Sidecar 中联调",
        );
      case "card.list":
        return this.cardList(command.params) as T;
      case "card.get":
        return this.cardGet(command.params) as T;
      case "card.create_draft":
        return this.cardCreateDraft(command.params) as T;
      case "card.update":
        return this.cardUpdate(command.params) as T;
      case "card.duplicate":
        return this.cardDuplicate(command.params) as T;
      case "card.archive":
        return this.cardArchive(command.params) as T;
      case "card.unarchive":
        return this.cardUnarchive(command.params) as T;
      case "card.delete":
        return this.cardDelete(command.params) as T;
      case "card.select_active":
        return this.cardSelectActive(command.params) as T;
      case "card.peek_import":
        return this.cardPeekImport(command.params) as T;
      case "card.import_json":
        return this.cardImportJson(command.params) as T;
      case "card.import_png":
        return this.cardImportPng(command.params) as T;
      case "card.export_json":
        return this.cardExportJson(command.params) as T;
      case "card.export_png":
        return this.cardExportPng(command.params) as T;
      case "card.publish":
        return this.cardPublish(command.params) as T;
      case "card.set_avatar":
        return this.cardSetAvatar(command.params) as T;
      case "card.remove_avatar":
        return this.cardRemoveAvatar(command.params) as T;
      case "voice.card_bind_reference":
        return this.voiceCardBindReference(command.params) as T;
      case "voice.card_create":
        return (await this.voiceCardCreate(command.params)) as T;
      case "voice.card_unbind":
        return this.voiceCardUnbind(command.params) as T;
      case "voice.card_preview":
        return this.voiceCardPreview(command.params) as T;
      case "voice.mobile_ptt_start":
        return this.voiceMobilePttStart(command.params) as T;
      case "voice.mobile_audio_chunk":
        return this.voiceMobileAudioChunk(command.params) as T;
      case "voice.mobile_ptt_stop":
        return this.voiceMobilePttStop(command.params) as T;
      case "voice.mobile_tts_stop":
        return {} as T;
      case "remote.issue_code":
        return this.remoteIssueCode() as T;
      case "remote.pair":
        return this.remotePair(command.params) as T;
      case "remote.list_devices":
        return { devices: MOCK_REMOTE_DEVICES } as T;
      case "remote.revoke":
        return {
          device_name: String(command.params.device_name ?? ""),
          revoked_tokens: 1,
        } as T;
      // mock 不以 --serve 监听，与真实后端在远程服务未监听时一致：开启隧道被拒，隧道保持关闭。
      case "remote.tunnel_start":
        throw new DesktopRequestError(
          "serve_not_started",
          "远程服务未启动（--serve 未监听或端口被占用），无法开启公网接入",
        );
      case "remote.tunnel_stop":
        return { status: "stopping" } as T;
      case "remote.tunnel_status":
        return { state: "off", public_url: null, hostname: null, error: null } as T;
      case "power.get_status":
        return this.powerGetStatus() as T;
      default:
        throw new DesktopRequestError("unknown_method", `Mock 后端不支持命令：${command.method}`);
    }
  }

  async pickFolder(): Promise<string | null> {
    return null;
  }

  async pickFile(_options?: { title?: string; filters?: FileFilter[] }): Promise<string | null> {
    return this.pickFileResult;
  }

  async saveFile(_options?: { title?: string; defaultPath?: string; filters?: FileFilter[] }): Promise<string | null> {
    return this.saveFileResult;
  }

  async openChatWindow(_conversationId: string, _title: string): Promise<string> {
    throw new Error("独立聊天窗口需要在 Tauri 桌面运行时打开");
  }

  async reconnectSidecar(): Promise<void> {
    // 模拟 Rust 宿主的一次断线与恢复：先断开并上报可恢复错误，随后恢复；
    // connected 会让 store 进入 booting 并重新 bootstrap。宿主事件不带序号。
    this.emitHost("connection.status", { status: "disconnected" });
    this.emitHost("error.reported", {
      code: "backend_disconnected",
      message: "Python Sidecar 已断开，正在重连…",
      severity: "recoverable",
      source: "sidecar",
    });
    this.emitHost("connection.status", { status: "connected" });
  }

  /* card.* 命令；错误码、检查顺序与 Sidecar 一致。 */

  private activeCardId: string | null = "card-saved-002";

  /** 与 Sidecar 的 _require_writable_card 一致：内置角色只读。 */
  private requireWritableCard(cardId: string): void {
    if (cardId.startsWith(BUILTIN_PREFIX)) {
      throw new DesktopRequestError(CARD_READ_ONLY, "内置角色为只读，不能修改、归档或删除");
    }
  }

  private requireCard(cardId: string): MockCardSummary {
    const card = this.cards.find((item) => item.card_id === cardId);
    if (!card) throw new DesktopRequestError("card_not_found", "角色卡不存在");
    return card;
  }

  private requireBuiltinCard(cardId: string): MockCardSummary {
    const card = MOCK_BUILTIN_CARDS.find((item) => item.card_id === cardId);
    if (!card) throw new DesktopRequestError("card_not_found", "内置角色不存在");
    return card;
  }

  private patchCard(cardId: string, patch: Partial<MockCardSummary>): void {
    this.cards = this.cards.map((card) => (card.card_id === cardId ? { ...card, ...patch } : card));
  }

  /** 新卡入库：摘要排在最前，整卡 JSON 供 card.get 读取。 */
  private addCard(summary: MockCardSummary, payload: Record<string, unknown>): void {
    this.cards = [summary, ...this.cards];
    this.cardPayloads.set(summary.card_id, payload);
  }

  private cardList(params: Record<string, unknown>): { cards: CardSummaryPayload[] } {
    const includeArchived = params.include_archived === true;
    const cards = this.cards
      .filter((card) => includeArchived || !this.archivedCardIds.has(card.card_id))
      .map((card) => ({
        ...card,
        active: card.card_id === this.activeCardId,
        archived: this.archivedCardIds.has(card.card_id),
      }));
    const builtin = MOCK_BUILTIN_CARDS.map((card) => ({ ...card, archived: false }));
    return { cards: [...cards, ...builtin] };
  }

  /** 整卡带上 data.extensions.hsr.voice_profile，字段与 codec 序列化一致，全部为字符串。 */
  private cardWithVoiceProfile(cardId: string): Record<string, unknown> {
    const card = this.clone(this.cardPayloads.get(cardId)!);
    const profile = this.voiceProfiles.get(cardId);
    if (!profile) return card;
    const data = (card.data ?? {}) as Record<string, unknown>;
    const extensions = (data.extensions ?? {}) as Record<string, unknown>;
    const hsr = (extensions.hsr ?? {}) as Record<string, unknown>;
    hsr.voice_profile = {
      state: profile.state,
      voice_id: profile.voice_id,
      target_model: "qwen-audio-3.0-tts-flash",
      creation_mode: "clone",
      prefix: "",
      reference_audio_asset: this.cardReferenceAudios.get(cardId)?.asset_id ?? "",
      reference_audio_url: "",
      voice_prompt_asset: "",
      last_error: "",
      updated_at: "",
    };
    extensions.hsr = hsr;
    data.extensions = extensions;
    card.data = data;
    return card;
  }

  private cardGet(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    if (!cardId) throw new DesktopRequestError("invalid_params", "card.get 需要 card_id");
    if (cardId.startsWith(BUILTIN_PREFIX)) {
      const builtin = this.requireBuiltinCard(cardId);
      return {
        card_id: cardId,
        state: "saved",
        source: "builtin",
        created_at: "",
        updated_at: "",
        card: mockBuiltinCardPayload(cardId, builtin.name),
        read_only: true,
        avatar: null,
        compat_report: EMPTY_COMPAT_REPORT,
      };
    }
    const found = this.requireCard(cardId);
    return {
      card_id: found.card_id,
      state: found.state,
      source: found.source,
      created_at: found.updated_at,
      updated_at: found.updated_at,
      card: this.cardWithVoiceProfile(cardId),
      read_only: false,
      avatar: this.cardAvatars.get(cardId) ?? null,
      // 导入的卡沿用样例导入报告，其余卡没有兼容问题。
      compat_report:
        found.source === "tavern_import" ? this.sampleBaiImportPreview().report : EMPTY_COMPAT_REPORT,
    };
  }

  private cardCreateDraft(params: Record<string, unknown>) {
    const name = String(params.name ?? "").trim();
    if (!name) throw new DesktopRequestError("invalid_params", "card.create_draft 需要 name");
    const cardId = `card-mock-${this.cards.length + 1}`;
    this.addCard(
      {
        card_id: cardId,
        name,
        state: "draft",
        source: "user_created",
        updated_at: new Date().toISOString(),
        has_avatar: false,
        voice_state: "voice_unconfigured",
        active: false,
        read_only: false,
      },
      mockCardPayload(name),
    );
    return { card_id: cardId, state: "draft" };
  }

  private cardUpdate(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    this.requireWritableCard(cardId);
    const card = params.card;
    if (!card || typeof card !== "object" || Array.isArray(card)) {
      throw new DesktopRequestError("invalid_params", "card.update 需要 card（角色卡 JSON 对象）");
    }
    const payload = this.clone(card as Record<string, unknown>);
    const name = cardName(payload);
    this.requireCard(cardId);
    const now = new Date().toISOString();
    this.cardPayloads.set(cardId, payload);
    this.patchCard(cardId, { name, updated_at: now });
    return { card_id: cardId, updated_at: now };
  }

  private cardDuplicate(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const newId = `card-mock-copy-${this.cards.length + 1}`;
    const now = new Date().toISOString();
    if (cardId.startsWith(BUILTIN_PREFIX)) {
      // 内置卡按导入卡入库一份可编辑副本，没有头像与音色。
      const builtin = this.requireBuiltinCard(cardId);
      const name = `${builtin.name}（副本）`;
      this.addCard(
        {
          card_id: newId,
          name,
          state: "imported",
          source: "tavern_import",
          updated_at: now,
          has_avatar: false,
          voice_state: "voice_unconfigured",
          active: false,
          read_only: false,
        },
        renamedCard(mockBuiltinCardPayload(cardId, builtin.name), name),
      );
      return { card_id: newId, name };
    }
    const source = this.requireCard(cardId);
    const name = `${source.name}（副本）`;
    // 副本保留源卡的状态、来源、头像与音色。
    this.addCard(
      { ...source, card_id: newId, name, updated_at: now, active: false },
      renamedCard(this.clone(this.cardPayloads.get(cardId)!), name),
    );
    const avatar = this.cardAvatars.get(cardId);
    if (avatar) this.cardAvatars.set(newId, avatar);
    const reference = this.cardReferenceAudios.get(cardId);
    if (reference) this.cardReferenceAudios.set(newId, reference);
    const profile = this.voiceProfiles.get(cardId);
    if (profile) this.voiceProfiles.set(newId, profile);
    return { card_id: newId, name };
  }

  private cardArchive(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    this.requireWritableCard(cardId);
    if (this.requireCard(cardId).state === "draft") {
      throw new DesktopRequestError("card_invalid_state", "草稿不能归档，请先保存");
    }
    this.archivedCardIds.add(cardId);
    return { card_id: cardId, archived: true };
  }

  private cardUnarchive(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireWritableCard(cardId);
    this.requireCard(cardId);
    this.archivedCardIds.delete(cardId);
    return { card_id: cardId, archived: false };
  }

  private cardDelete(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    this.requireWritableCard(cardId);
    if (params.confirm !== true) throw new DesktopRequestError("card_confirm_required", "删除需要确认");
    this.cards = this.cards.filter((card) => card.card_id !== cardId);
    this.cardPayloads.delete(cardId);
    this.archivedCardIds.delete(cardId);
    this.cardAvatars.delete(cardId);
    this.cardReferenceAudios.delete(cardId);
    this.voiceProfiles.delete(cardId);
    return { card_id: cardId, deleted: true };
  }

  private cardSelectActive(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    this.requireWritableCard(cardId);
    if (this.archivedCardIds.has(cardId)) {
      throw new DesktopRequestError("card_invalid_state", `已归档角色卡不能设为当前使用: ${cardId}`);
    }
    this.activeCardId = cardId;
    return { card_id: cardId };
  }

  /* 角色卡导入导出、发布与头像。 */

  /** 白厄样例预览数据（来源：tests/fixtures/character_cards/白厄（3.4前）.json）。
      name=白厄（3.4前），spec_version=3.0，greeting_count=6（first_mes + 5 条 alternate_greetings），
      world_book_entries=20，avatar_available=false。 */
  private sampleBaiImportPreview() {
    return {
      name: "白厄（3.4前）",
      spec_version: "3.0",
      avatar_available: false,
      greeting_count: 6,
      world_book_entries: 20,
      tags: [] as string[],
      report: {
        applied: ["data.name", "data.description", "data.character_book"],
        preserved: ["data.extensions.talkativeness", "data.extensions.fav", "data.extensions.world"],
        not_executed: [
          { category: "command_panels" as const, text: "data.extensions.hsr.command_panels" },
        ],
        normalized_from_root: [],
        warnings: [],
        errors: [],
      },
    };
  }

  /** mock 不读真实文件：路径含 invalid 或 missing 时按无法解析的文件拒绝。 */
  private rejectUnparsableCardFile(path: string): void {
    if (path.includes("invalid") || path.includes("missing")) {
      throw new DesktopRequestError(CARD_IMPORT_FAILED, `模拟导入失败：无法解析 ${path}`);
    }
  }

  /** 导入的卡入库为酒馆导入卡；PNG 字节同时作为头像。 */
  private importCard(cardId: string, params: Record<string, unknown>, withAvatar: boolean) {
    const preview = this.sampleBaiImportPreview();
    const name = params.as_duplicate === true ? `${preview.name}（副本）` : preview.name;
    this.addCard(
      {
        card_id: cardId,
        name,
        state: "imported",
        source: "tavern_import",
        updated_at: new Date().toISOString(),
        has_avatar: withAvatar,
        voice_state: "voice_unconfigured",
        active: false,
        read_only: false,
      },
      mockCardPayload(name),
    );
    if (withAvatar) {
      this.cardAvatars.set(cardId, { mime_type: "image/png", data_base64: PLACEHOLDER_AVATAR_BASE64 });
    }
    return { card_id: cardId, name, state: "imported", report: preview.report };
  }

  private cardPeekImport(params: Record<string, unknown>) {
    const path = String(params.path ?? "");
    this.rejectUnparsableCardFile(path);
    if (path.toLowerCase().endsWith(".png")) {
      // 真实后端按 PNG 签名分派；mock 无文件可读，按扩展名模拟 PNG 分支。
      return {
        preview: {
          ...this.sampleBaiImportPreview(),
          format: "png" as const,
          avatar_available: true,
          avatar_width: 512,
          avatar_height: 512,
        },
      };
    }
    return {
      preview: {
        ...this.sampleBaiImportPreview(),
        format: "json" as const,
        avatar_available: false,
        avatar_width: null,
        avatar_height: null,
      },
    };
  }

  private cardImportJson(params: Record<string, unknown>) {
    this.rejectUnparsableCardFile(String(params.path ?? ""));
    return this.importCard(`card-imported-${this.cards.length + 1}`, params, false);
  }

  private cardImportPng(params: Record<string, unknown>) {
    this.rejectUnparsableCardFile(String(params.path ?? ""));
    return this.importCard(`card-imported-png-${this.cards.length + 1}`, params, true);
  }

  private cardExportJson(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    if (cardId.startsWith(BUILTIN_PREFIX)) {
      throw new DesktopRequestError(CARD_READ_ONLY, "内置角色为只读，请先复制为可编辑卡再导出");
    }
    const path = requiredString(params, "path");
    this.requireCard(cardId);
    return {
      exported: true,
      path,
      avatar_saved: params.save_avatar === true && this.cardAvatars.has(cardId),
    };
  }

  private cardExportPng(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireWritableCard(cardId);
    const path = requiredString(params, "path");
    const card = this.requireCard(cardId);
    if (!this.cardAvatars.has(cardId)) {
      throw new DesktopRequestError(CARD_EXPORT_FAILED, "卡未设置头像，请先设置头像后再导出 PNG");
    }
    return {
      exported: true,
      path,
      name: card.name,
      spec_version: "3.0",
      greeting_count: 6,
      world_book_entries: 20,
      extensions: ["hsr"],
    };
  }

  /** 草稿发布前检查整卡里的角色名与第一条消息；其他状态原样返回。 */
  private cardPublish(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireWritableCard(cardId);
    const card = this.requireCard(cardId);
    if (card.state !== "draft") {
      return { card_id: cardId, state: card.state };
    }
    const data = this.cardPayloads.get(cardId)!.data as Record<string, unknown>;
    const labels = { name: "角色名称", first_mes: "第一条消息" } as const;
    const missing = (Object.keys(labels) as Array<keyof typeof labels>)
      .filter((key) => !String(data[key] ?? "").trim())
      .map((key) => labels[key]);
    if (missing.length > 0) {
      throw new DesktopRequestError(CARD_PUBLISH_INVALID, `完成创建前必填：${missing.join("、")}`);
    }
    this.patchCard(cardId, { state: "saved", updated_at: new Date().toISOString() });
    return { card_id: cardId, state: "saved" };
  }

  private avatarMimeFromPath(path: string): string | null {
    const lower = path.toLowerCase();
    if (lower.endsWith(".png")) return "image/png";
    if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
    if (lower.endsWith(".webp")) return "image/webp";
    return null;
  }

  private cardSetAvatar(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireWritableCard(cardId);
    const mimeType = this.avatarMimeFromPath(requiredString(params, "path"));
    if (!mimeType) {
      throw new DesktopRequestError(CARD_AVATAR_UNSUPPORTED, "头像仅支持 PNG / JPEG / WebP 图片");
    }
    this.requireCard(cardId);
    this.cardAvatars.set(cardId, { mime_type: mimeType, data_base64: PLACEHOLDER_AVATAR_BASE64 });
    this.patchCard(cardId, { has_avatar: true });
    return { card_id: cardId, asset_id: `avatar-${cardId}`, mime_type: mimeType };
  }

  private cardRemoveAvatar(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireWritableCard(cardId);
    this.requireCard(cardId);
    this.cardAvatars.delete(cardId);
    this.patchCard(cardId, { has_avatar: false });
    return { card_id: cardId, removed: true };
  }

  /* 电源状态。 */

  private powerGetStatus(): PowerStatusPayload {
    // Windows 上读取成功、未以 --serve 开启远程服务时的结果；at_risk 场景由 emitPowerStatusChanged 模拟。
    return {
      supported: true,
      platform: "win32",
      plan_name: "平衡",
      ac_sleep_timeout_seconds: 1800,
      dc_sleep_timeout_seconds: 1200,
      remote_serve_enabled: false,
      threshold_seconds: 900,
      at_risk: false,
      reason: "远程服务未开启",
      checked_at: new Date().toISOString(),
      warnings: [],
    };
  }

  /** 模拟 --serve 电源监视线程的 power.status_changed，载荷与 power.get_status 同形。 */
  emitPowerStatusChanged(payload: PowerStatusPayload): void {
    this.emit("power.status_changed", payload as unknown as Record<string, unknown>);
  }

  /* 角色卡音色。 */

  private referenceMimeFromPath(path: string): string | null {
    const lower = path.toLowerCase();
    if (lower.endsWith(".wav")) return "audio/wav";
    if (lower.endsWith(".mp3")) return "audio/mpeg";
    if (lower.endsWith(".m4a")) return "audio/mp4";
    return null;
  }

  private voiceCardBindReference(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireWritableCard(cardId);
    const mimeType = this.referenceMimeFromPath(requiredString(params, "path"));
    if (!mimeType) {
      throw new DesktopRequestError(VOICE_REFERENCE_INVALID, "参考音频仅支持 WAV / MP3 / M4A");
    }
    this.requireCard(cardId);
    const assetId = `ref-audio-${cardId}`;
    const asset = { asset_id: assetId, duration_seconds: 5.2, size_bytes: 102400, mime_type: mimeType };
    this.cardReferenceAudios.set(cardId, asset);
    return { card_id: cardId, ...asset };
  }

  /** 音色状态写进卡摘要并推送 voice.card_provision_changed。 */
  private publishCardProvision(
    cardId: string,
    state: CharacterVoiceState,
    voiceId: string | null,
    error: string | null,
  ): void {
    this.patchCard(cardId, { voice_state: state });
    this.emit("voice.card_provision_changed", { card_id: cardId, state, voice_id: voiceId, error });
  }

  /**
   * 与 Sidecar 一致：校验通过后先推送 voice_creating，等待供应商期间同一张卡再次创建被拒；
   * 成功推送 voice_ready 后响应，失败推送 voice_failed 后以 voice_card_create_failed 拒绝。
   */
  private async voiceCardCreate(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireWritableCard(cardId);
    const mode = requiredString(params, "mode");
    if (mode !== "clone" && mode !== "design") {
      throw new DesktopRequestError("invalid_params", "mode 必须是 clone 或 design");
    }
    if (this.voiceProvisioningCardIds.has(cardId)) {
      throw new DesktopRequestError(VOICE_CARD_PROVISION_IN_PROGRESS, "该角色卡正在创建音色，请等待完成后再试");
    }
    this.voiceProvisioningCardIds.add(cardId);
    try {
      if (!this.voiceConfigured) {
        throw new DesktopRequestError(
          VOICE_NOT_CONFIGURED,
          "请先在语音页保存 DashScope API Key 与服务地址，再为角色创建音色",
        );
      }
      this.requireCard(cardId);
      if (mode === "clone" && !this.cardReferenceAudios.has(cardId)) {
        throw new DesktopRequestError(VOICE_REFERENCE_MISSING, "请先绑定参考音频（voice.card_bind_reference）");
      }
      if (mode === "design" && !String(params.voice_prompt ?? "").trim()) {
        throw new DesktopRequestError("voice_invalid_request", "声音设计需要非空 voice_prompt");
      }
      this.publishCardProvision(cardId, "voice_creating", null, null);
      await new Promise((resolve) => setTimeout(resolve, MOCK_VOICE_PROVIDER_DELAY_MS));
      if (this.voiceProvisionFail) {
        const detail = "模拟音色创建失败";
        // 失败保留旧音色 id，与 Sidecar 的 _mark_card_voice_failed 一致。
        const previousVoiceId = this.voiceProfiles.get(cardId)?.voice_id ?? "";
        this.voiceProfiles.set(cardId, { voice_id: previousVoiceId, state: "voice_failed" });
        this.publishCardProvision(cardId, "voice_failed", previousVoiceId || null, detail);
        throw new DesktopRequestError("voice_card_create_failed", detail);
      }
      const voiceId = `mock-voice-${Math.random().toString(36).slice(2, 8)}`;
      this.voiceProfiles.set(cardId, { voice_id: voiceId, state: "voice_ready" });
      this.publishCardProvision(cardId, "voice_ready", voiceId, null);
      return { card_id: cardId, state: "voice_ready", voice_id: voiceId };
    } finally {
      this.voiceProvisioningCardIds.delete(cardId);
    }
  }

  private voiceCardUnbind(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireWritableCard(cardId);
    this.requireCard(cardId);
    this.voiceProfiles.delete(cardId);
    this.patchCard(cardId, { voice_state: "voice_unconfigured" });
    return { card_id: cardId, state: "voice_unconfigured" };
  }

  private voiceCardPreview(params: Record<string, unknown>) {
    const cardId = requiredString(params, "card_id");
    this.requireCard(cardId);
    const profile = this.voiceProfiles.get(cardId);
    if (!profile || profile.state !== "voice_ready" || !profile.voice_id) {
      throw new DesktopRequestError(VOICE_CARD_NOT_READY, "该角色卡尚未创建可用音色");
    }
    return { voice: this.scenario.snapshot.voice };
  }

  /* 手机远程语音。 */

  private requireMobileSession(sessionId: string) {
    const session = this.mobileAudioSessions.get(sessionId);
    if (!session) throw new DesktopRequestError("voice_session_not_found", "转写会话不存在或已结束");
    return session;
  }

  private voiceMobilePttStart(params: Record<string, unknown>) {
    const conversationId = String(params.conversation_id ?? "");
    const sessionId = `mobile-ptt-${this.sequence + 1}`;
    this.mobileAudioSessions.set(sessionId, { conversation_id: conversationId, expected_seq: 0 });
    return { session_id: sessionId };
  }

  private voiceMobileAudioChunk(params: Record<string, unknown>) {
    const sessionId = requiredString(params, "session_id");
    const seq = params.seq;
    if (typeof seq !== "number" || !Number.isInteger(seq)) {
      throw new DesktopRequestError("invalid_params", "seq 必须是整数");
    }
    if (typeof params.data !== "string" || !params.data) {
      throw new DesktopRequestError("invalid_params", "data 必须是非空 base64 字符串");
    }
    const session = this.requireMobileSession(sessionId);
    if (seq !== session.expected_seq) {
      throw new DesktopRequestError(
        VOICE_AUDIO_SEQ_GAP,
        `音频分片序号跳号：期望 ${session.expected_seq}，实际 ${seq}`,
      );
    }
    session.expected_seq += 1;
    return { accepted: true };
  }

  private voiceMobilePttStop(params: Record<string, unknown>) {
    const sessionId = requiredString(params, "session_id");
    const session = this.requireMobileSession(sessionId);
    this.mobileAudioSessions.delete(sessionId);
    const conversationId = session.conversation_id;
    const transcript = this.mobileTranscriptEmpty ? "" : "模拟手机语音转写文本";
    if (transcript === "") {
      throw new DesktopRequestError(VOICE_TRANSCRIPT_EMPTY, "未识别到语音内容");
    }
    // 异步下发转写事件与角色回复/TTS 分片。
    setTimeout(() => {
      this.emit("voice.mobile_transcript", { conversation_id: conversationId, session_id: sessionId, text: transcript, is_final: false });
      this.emit("voice.mobile_transcript", { conversation_id: conversationId, session_id: sessionId, text: transcript, is_final: true });
      this.submitMessage({ conversation_id: conversationId, target: "character", text: transcript });
      const messageId = `mock-tts-${this.sequence + 1}`;
      for (let seq = 0; seq < 3; seq += 1) {
        this.emit("voice.mobile_tts_chunk", {
          conversation_id: conversationId,
          message_id: messageId,
          seq,
          mime: "audio/pcm;rate=24000",
          data: "ZmFrZS1wY20tY2h1bms=",
        });
      }
      this.emit("voice.mobile_tts_end", { conversation_id: conversationId, message_id: messageId });
    }, 50);
    return { session_id: sessionId, transcript, conversation_id: conversationId };
  }

  /* 审批仲裁：首个终态获胜，之后的裁决以 approval_already_resolved 拒绝，details 是已有终态。 */

  private resolveApproval(params: Record<string, unknown>) {
    const approvalId = String(params.approval_id ?? "");
    const decision = String(params.decision ?? "") as ApprovalResolvedPayload["decision"];
    const existing = this.resolvedApprovals.get(approvalId);
    if (existing) {
      throw new DesktopRequestError(
        APPROVAL_ALREADY_RESOLVED,
        "该审批已有裁决结果",
        existing as unknown as Record<string, unknown>,
      );
    }
    const pending = this.scenario.snapshot.approvals.find((item) => item.approval_id === approvalId);
    if (!pending) throw new DesktopRequestError("approval_not_found", `审批不存在：${approvalId}`);
    const outcome: ApprovalResolvedPayload = {
      approval_id: approvalId,
      conversation_id: pending.conversation_id,
      task_id: pending.task_id ?? "",
      decision,
      resolved_by: "desktop",
      actor: "user",
      request_reason: pending.reason,
      resolution_reason: null,
      resolved_at: new Date().toISOString(),
      error_code: null,
    };
    this.resolvedApprovals.set(approvalId, outcome);
    this.emit("approval.resolved", outcome as unknown as Record<string, unknown>);
    return { approval_id: approvalId, accepted: true, resolved_by: "desktop", decision };
  }

  /* 远程配对。 */

  private remoteIssueCode(): RemoteIssueCodeResult {
    this.pairingCode = String(100000 + this.sequence);
    // mock 不以 --serve 监听，没有远程接入地址。
    return { code: this.pairingCode, ttl_seconds: 300, serve_address: null };
  }

  private remotePair(params: Record<string, unknown>): { token: string } {
    const code = String(params.code ?? "");
    const deviceName = String(params.device_name ?? "").trim();
    if (!code || !deviceName) {
      throw new DesktopRequestError("invalid_params", "remote.pair 需要 code 与 device_name");
    }
    if (this.pairingCode === null || code !== this.pairingCode) {
      throw new DesktopRequestError("pairing_invalid_code", "配对码无效");
    }
    this.pairingCode = null;
    this.emit("remote.paired", { device_name: deviceName });
    return { token: `mock-remote-token-${deviceName}` };
  }

  subscribe(listener: (event: DesktopStreamEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** 模拟 Rust 宿主合成的连接事件，不带序号。 */
  private emitHost(event: "connection.status" | "error.reported", payload: Record<string, unknown>): void {
    for (const listener of this.listeners) {
      listener({ kind: "event", event, stream_id: MOCK_STREAM_ID, payload });
    }
  }

  emit(event: DesktopEvent["event"], payload: Record<string, unknown>): void {
    const message: DesktopEvent = {
      kind: "event",
      event,
      sequence: this.sequence + 1,
      stream_id: MOCK_STREAM_ID,
      payload,
    };
    this.sequence += 1;
    this.applyEventToSnapshot(message);
    this.scenario.snapshot.sequence = this.sequence;
    for (const listener of this.listeners) listener(message);
  }

  private snapshotResult<T>(): T {
    this.refreshCurrentPointers();
    this.scenario.snapshot.sequence = this.sequence;
    return this.clone(this.scenario.snapshot) as T;
  }

  private createProject(params: Record<string, unknown>): DesktopSnapshot {
    const rootPath = String(params.root_path ?? "C:/Projects/mock-project");
    const projectId = `mock-project-${this.scenario.snapshot.projects.length + 1}`;
    const conversationId = `${projectId}-conversation-1`;
    const firstConversation = conversation(
      conversationId,
      projectId,
      String(params.title ?? "新聊天"),
    );
    const requestedName = String(params.name ?? "").trim();
    const newProject = project(
      projectId,
      requestedName || folderNameFromPath(rootPath) || `项目 ${this.scenario.snapshot.projects.length + 1}`,
      rootPath,
      [firstConversation],
    );
    this.scenario.snapshot.projects = [...this.scenario.snapshot.projects, newProject];
    this.scenario.snapshot.current_project_id = projectId;
    this.scenario.snapshot.current_conversation_id = conversationId;
    return this.snapshotResult<DesktopSnapshot>();
  }

  private selectProject(params: Record<string, unknown>): DesktopSnapshot {
    const projectId = String(params.project_id ?? "");
    const selected = this.scenario.snapshot.projects.find((item) => item.project_id === projectId);
    if (!selected) return this.snapshotResult<DesktopSnapshot>();
    const requestedConversationId = String(params.conversation_id ?? "");
    const selectedConversation = selected.conversations.find(
      (item) => item.conversation_id === requestedConversationId,
    ) ?? selected.conversations.find((item) => !item.archived) ?? selected.conversations[0];
    this.scenario.snapshot.current_project_id = selected.project_id;
    this.scenario.snapshot.current_conversation_id = selectedConversation?.conversation_id ?? "";
    return this.snapshotResult<DesktopSnapshot>();
  }

  private updateProjectSettings(params: Record<string, unknown>): {
    project: DesktopSnapshot["current_project"];
  } {
    const projectId = String(params.project_id ?? this.scenario.snapshot.current_project_id);
    const projects = this.scenario.snapshot.projects.map((item) =>
      item.project_id === projectId
        ? {
            ...item,
            name: String(params.name ?? item.name),
            root_path: String(params.root_path ?? item.root_path),
            path_available: params.root_path ? true : item.path_available,
            approval_mode: (params.approval_mode as ProjectRecord["approval_mode"]) ?? item.approval_mode,
            reasoning_effort:
              (params.reasoning_effort as ProjectRecord["reasoning_effort"]) ?? item.reasoning_effort,
          }
        : item,
    );
    this.scenario.snapshot.projects = projects;
    // 与真实后端一致，project.changed 与返回体只带项目字段。
    const project = projectWithoutConversations(projects.find((item) => item.project_id === projectId)!);
    this.emit("project.changed", { project });
    return { project: this.clone(project) };
  }

  private setConversationMode(params: Record<string, unknown>): {
    conversation_id: string;
    mode: "chat" | "collaboration";
  } {
    const conversationId = String(
      params.conversation_id ?? this.scenario.snapshot.current_conversation_id,
    );
    const mode = params.mode === "collaboration" ? "collaboration" : "chat";
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
      ...item,
      conversations: item.conversations.map((candidate) =>
        candidate.conversation_id === conversationId
          ? { ...candidate, last_mode: mode }
          : candidate,
      ),
    }));
    const conversation = this.scenario.snapshot.projects
      .flatMap((item) => item.conversations)
      .find((item) => item.conversation_id === conversationId);
    if (conversation) this.emit("conversation.changed", { conversation });
    return { conversation_id: conversationId, mode };
  }

  /** 结果顶层带 reused。mock 场景的会话没有绑定角色卡，不参与复用，reuse_active 也总是新建。 */
  private createConversation(
    params: Record<string, unknown>,
  ): DesktopSnapshot & { reused: boolean } {
    const projectId = String(params.project_id ?? this.scenario.snapshot.current_project_id);
    const projectIndex = this.scenario.snapshot.projects.findIndex(
      (item) => item.project_id === projectId,
    );
    if (projectIndex < 0)
      return { ...this.snapshotResult<DesktopSnapshot>(), reused: false };
    const selectedProject = this.scenario.snapshot.projects[projectIndex];
    const conversationId = `${projectId}-conversation-${selectedProject.conversations.length + 1}`;
    const pairId =
      typeof params.pair_id === "string" ? params.pair_id : this.scenario.snapshot.pair.pair_id;
    const newConversation = conversation(
      conversationId,
      projectId,
      String(params.title ?? "新聊天"),
      pairId,
    );
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item, index) =>
      index === projectIndex
        ? { ...item, conversations: [...item.conversations, newConversation] }
        : item,
    );
    this.scenario.snapshot.current_project_id = projectId;
    this.scenario.snapshot.current_conversation_id = conversationId;
    return { ...this.snapshotResult<DesktopSnapshot>(), reused: false };
  }

  private selectConversation(params: Record<string, unknown>): DesktopSnapshot {
    const conversationId = String(params.conversation_id ?? "");
    for (const item of this.scenario.snapshot.projects) {
      const selected = item.conversations.find(
        (candidate) => candidate.conversation_id === conversationId && !candidate.archived,
      );
      if (selected) {
        this.scenario.snapshot.current_project_id = item.project_id;
        this.scenario.snapshot.current_conversation_id = selected.conversation_id;
        break;
      }
    }
    return this.snapshotResult<DesktopSnapshot>();
  }

  private openConversation(params: Record<string, unknown>): ConversationOpenResult {
    const conversationId = String(params.conversation_id ?? "");
    const selectedProject = this.scenario.snapshot.projects.find((candidate) =>
      candidate.conversations.some((item) => item.conversation_id === conversationId),
    );
    const selectedConversation = selectedProject?.conversations.find(
      (item) => item.conversation_id === conversationId,
    );
    if (!selectedProject || !selectedConversation) {
      throw new DesktopRequestError("conversation_not_found", `找不到聊天 ${conversationId}`);
    }
    const selectedPair = this.scenario.snapshot.pairs.find(
      (item) => item.pair_id === selectedConversation.pair_id,
    )!;
    const activeTasks = this.scenario.snapshot.active_tasks;
    return {
      conversation: this.clone(selectedConversation),
      project: this.clone(projectWithoutConversations(selectedProject)),
      pair: this.clone(selectedPair),
      messages: this.clone(
        this.scenario.snapshot.messages.filter((item) => item.conversation_id === conversationId),
      ),
      tool_runs: this.clone(
        this.scenario.snapshot.tool_runs.filter((item) => item.conversation_id === conversationId),
      ),
      turns: this.clone(
        this.scenario.snapshot.turns.filter((item) => item.conversation_id === conversationId),
      ),
      queue_items: this.clone(
        this.scenario.snapshot.queue_items.filter((item) => item.conversation_id === conversationId),
      ),
      active_task: this.clone(
        activeTasks.find((item) => item.conversation_id === conversationId) ?? null,
      ),
      sequence: this.sequence,
      stream_id: MOCK_STREAM_ID,
    };
  }

  /** 与真实 task.cancel 一致：没有匹配的运行中任务时返回 cancelled=false，不抛错。 */
  private cancelTask(params: Record<string, unknown>): TaskCancelResult {
    const conversationId = String(params.conversation_id ?? "");
    const taskId = String(params.task_id ?? "");
    const activeTasks = this.scenario.snapshot.active_tasks;
    const active = activeTasks.find(
      (item) => item.conversation_id === conversationId && item.task_id === taskId,
    );
    if (!active) {
      return { cancelled: false };
    }
    this.scenario.snapshot.active_tasks = activeTasks.filter(
      (item) => item.task_id !== taskId,
    );
    if (this.scenario.snapshot.active_task?.task_id === taskId) {
      this.scenario.snapshot.active_task = null;
    }
    this.scenario.snapshot.busy = this.scenario.snapshot.active_tasks.length > 0;
    this.emit("task.busy_changed", {
      busy: this.scenario.snapshot.busy,
      conversation_id: conversationId,
      task_id: taskId,
      active_task: null,
      active_tasks: this.scenario.snapshot.active_tasks,
    });
    return { cancelled: true };
  }

  private renameConversation(params: Record<string, unknown>): DesktopSnapshot {
    const conversationId = String(params.conversation_id ?? "");
    const title = String(params.title ?? "");
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
      ...item,
      conversations: item.conversations.map((candidate) =>
        candidate.conversation_id === conversationId ? { ...candidate, title } : candidate,
      ),
    }));
    return this.snapshotResult<DesktopSnapshot>();
  }

  /** 与真实后端一致：快照的项目列表不含已归档会话；归档非当前会话时广播带完整记录的 conversation.changed。 */
  private archiveConversation(params: Record<string, unknown>): DesktopSnapshot {
    const conversationId = String(
      params.conversation_id ?? this.scenario.snapshot.current_conversation_id,
    );
    const archived = this.scenario.snapshot.projects
      .flatMap((item) => item.conversations)
      .find((candidate) => candidate.conversation_id === conversationId);
    if (!archived) {
      throw new DesktopRequestError("conversation_not_found", `找不到聊天 ${conversationId}`);
    }
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
      ...item,
      conversations: item.conversations.filter(
        (candidate) => candidate.conversation_id !== conversationId,
      ),
    }));
    if (conversationId === this.scenario.snapshot.current_conversation_id) {
      const next = this.scenario.snapshot.projects.flatMap((item) => item.conversations)[0];
      this.scenario.snapshot.current_conversation_id = next?.conversation_id ?? "";
    } else {
      this.emit("conversation.changed", { conversation: { ...archived, archived: true } });
    }
    return this.snapshotResult<DesktopSnapshot>();
  }

  private archiveProject(params: Record<string, unknown>): DesktopSnapshot {
    const projectId = String(
      params.project_id ?? this.scenario.snapshot.current_project_id,
    );
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.filter(
      (item) => item.project_id !== projectId,
    );
    if (projectId === this.scenario.snapshot.current_project_id) {
      this.scenario.snapshot.current_project_id = "";
      this.scenario.snapshot.current_conversation_id = "";
    }
    return this.snapshotResult<DesktopSnapshot>();
  }

  private submitMessage(params: Record<string, unknown>): {
    message_id: string;
    conversation_id: string;
    status: string;
    target: string;
    turn_id: string;
  } {
    const conversationId = String(
      params.conversation_id ?? this.scenario.snapshot.current_conversation_id,
    );
    const target = params.target === "assistant" ? "assistant" : "character";
    const text = String(params.text ?? "");
    const userMessageId = `mock-user-${this.sequence + 1}`;
    // 用户消息立即落库并返回 id。聊天标题由真实后端在首次完整回复后生成，mock 不改标题。
    const userMessage = message(
      userMessageId,
      conversationId,
      "user",
      "user.text",
      text,
    );
    userMessage.target = target;
    userMessage.origin = "user";
    userMessage.status = "received";
    this.emit("message.created", { message: userMessage });
    // 回合生命周期：accepted、running、completed。
    const turnId = `mock-turn-${this.sequence + 1}`;
    const projectId = this.scenario.snapshot.projects.find((item) =>
      item.conversations.some((item) => item.conversation_id === conversationId),
    )?.project_id ?? "";
    const turn = (status: Turn["status"]): Turn =>
      mockTurn(turnId, projectId, conversationId, target, userMessageId, status);
    this.emit("turn.status_changed", { turn: turn("accepted") });
    const events =
      this.scenario.name === "chat-streaming" && conversationId === "conv-1"
        ? this.scenario.submitEvents
        : createSubmitEvents(conversationId, text, target);
    for (const event of events) this.emit(event.event, event.payload);
    this.emit("turn.started", { turn: turn("running") });
    this.emit("turn.status_changed", { turn: turn("completed") });
    return {
      message_id: userMessageId,
      conversation_id: conversationId,
      status: "received",
      target,
      turn_id: turnId,
    };
  }

  private accountList(): { accounts: DesktopSnapshot["accounts"]; current_account_id: string } {
    return {
      accounts: this.scenario.snapshot.accounts,
      current_account_id: this.scenario.snapshot.current_account_id,
    };
  }

  /* 账号命令，校验规则与真实后端一致。 */

  private accountRegister(params: Record<string, unknown>): {
    account: DesktopSnapshot["current_account"];
    accounts: DesktopSnapshot["accounts"];
  } {
    const username = String(params.username ?? "").trim();
    const password = String(params.password ?? "");
    if (!username || !password) {
      throw new DesktopRequestError("invalid_params", "注册需要 username 与 password");
    }
    if (password.length < 6) throw new DesktopRequestError("weak_password", "密码至少 6 位");
    if (this.scenario.snapshot.accounts.some((item) => item.username === username)) {
      throw new DesktopRequestError("username_taken", `用户名已存在：${username}`);
    }
    const account = {
      account_id: `mock-account-${this.scenario.snapshot.accounts.length + 1}`,
      username,
      display_name: String(params.display_name ?? username),
      avatar: "",
      last_login_at: null,
      onboarding_complete: false,
      theme: "dark" as const,
    };
    this.passwords.set(account.account_id, password);
    this.scenario.snapshot.accounts = [
      ...this.scenario.snapshot.accounts.map((item) => ({ ...item, is_last_login: false })),
      { ...account, is_last_login: true },
    ];
    this.scenario.snapshot.current_account = account;
    this.scenario.snapshot.current_account_id = account.account_id;
    this.scenario.snapshot.projects = [];
    this.scenario.snapshot.current_project_id = "";
    this.scenario.snapshot.current_conversation_id = "";
    this.emit("account.changed", {
      account,
      accounts: this.scenario.snapshot.accounts,
    });
    return { account, accounts: this.clone(this.scenario.snapshot.accounts) };
  }

  private accountLogin(params: Record<string, unknown>): {
    account: DesktopSnapshot["current_account"];
    accounts: DesktopSnapshot["accounts"];
  } {
    const accountId = String(params.account_id ?? "");
    const password = String(params.password ?? "");
    const account = this.scenario.snapshot.accounts.find((item) => item.account_id === accountId);
    // 真实后端对不存在的账号与错误密码一样按密码错误拒绝。
    if (!account || this.passwords.get(accountId) !== password) {
      throw new DesktopRequestError("wrong_password", "密码错误");
    }
    return this.switchAccount(account);
  }

  private accountChangePassword(params: Record<string, unknown>): { changed: true } {
    const oldPassword = String(params.old_password ?? "");
    const newPassword = String(params.new_password ?? "");
    if (newPassword.length < 6) throw new DesktopRequestError("weak_password", "新密码至少 6 位");
    const accountId = this.scenario.snapshot.current_account_id;
    if (this.passwords.get(accountId) !== oldPassword) {
      throw new DesktopRequestError("wrong_password", "原密码错误");
    }
    this.passwords.set(accountId, newPassword);
    return { changed: true };
  }

  /** 默认账号在真实库里始终存在；场景数据没有列出时补上。 */
  private ensureDefaultAccount(): DesktopSnapshot["accounts"][number] {
    const existing = this.scenario.snapshot.accounts.find(
      (item) => item.account_id === "default-local",
    );
    if (existing) return existing;
    const created = {
      account_id: "default-local",
      username: "default",
      display_name: "默认账号",
      avatar: "",
      last_login_at: null,
      onboarding_complete: false,
      theme: "dark" as const,
      is_last_login: false,
    };
    this.passwords.set(created.account_id, "");
    this.scenario.snapshot.accounts = [...this.scenario.snapshot.accounts, created];
    return created;
  }

  private switchAccount(account: DesktopSnapshot["accounts"][number]): {
    account: DesktopSnapshot["current_account"];
    accounts: DesktopSnapshot["accounts"];
  } {
    const next: DesktopSnapshot["current_account"] = {
      account_id: account.account_id,
      username: account.username,
      display_name: account.display_name,
      avatar: account.avatar,
      last_login_at: new Date().toISOString(),
      onboarding_complete: account.onboarding_complete,
      theme: account.theme,
    };
    this.scenario.snapshot.accounts = this.scenario.snapshot.accounts.map((item) => ({
      ...item,
      is_last_login: item.account_id === account.account_id,
    }));
    this.scenario.snapshot.current_account = next;
    this.scenario.snapshot.current_account_id = account.account_id;
    this.emit("account.changed", {
      account: next,
      accounts: this.clone(this.scenario.snapshot.accounts),
    });
    return { account: next, accounts: this.clone(this.scenario.snapshot.accounts) };
  }

  private accountCompleteOnboarding(): { account: DesktopSnapshot["current_account"] } {
    const current = this.scenario.snapshot.current_account;
    const next = { ...current, onboarding_complete: true };
    this.scenario.snapshot.current_account = next;
    this.scenario.snapshot.accounts = this.scenario.snapshot.accounts.map((item) =>
      item.account_id === next.account_id ? { ...item, onboarding_complete: true } : item,
    );
    this.emit("account.changed", {
      account: next,
      accounts: this.scenario.snapshot.accounts,
    });
    return { account: next };
  }

  private updateAccountProfile(params: Record<string, unknown>): { account: DesktopSnapshot["current_account"] } {
    const current = this.scenario.snapshot.current_account;
    const next = {
      ...current,
      display_name: String(params.display_name ?? current.display_name),
      avatar: params.avatar === undefined ? current.avatar : String(params.avatar),
    };
    this.scenario.snapshot.current_account = next;
    this.scenario.snapshot.accounts = this.scenario.snapshot.accounts.map((item) =>
      item.account_id === next.account_id ? { ...item, ...next } : item,
    );
    this.emit("account.changed", {
      account: next,
      accounts: this.scenario.snapshot.accounts,
    });
    return { account: next };
  }

  private configGet(): {
    engine: string;
    // dialogue 里除字符串外还有 provider_supported(boolean) 与 provider_unavailable(object|null)。
    dialogue: Record<string, unknown>;
    voice: Record<string, string>;
  } {
    return {
      engine: "deepseek",
      dialogue: {
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com",
        api_key_masked: "sk-d…1234",
        reasoning_effort: "auto",
        provider_supported: true,
        provider_unavailable: null,
      },
      voice: {
        enabled: "true",
        assistant_voice_enabled: "false",
        base_url: "https://dashscope.aliyuncs.com/api/v1",
        api_key_masked: this.voiceConfigured ? "sk-v…5678" : "",
        credential_source: this.voiceConfigured ? "account" : "not_configured",
        asr_model: "qwen-audio-3.0-asr-flash-streaming",
        tts_model: "qwen-audio-3.0-tts-flash",
        character_voice: "qwen-audio-3.0-tts-flash-phainon-46e9bd0087cd4c4c8d29e1b9f1b5db32",
        character_voice_name: "白厄",
        assistant_voice: "qwen-audio-3.0-tts-flash-vd-ancientmac-a26ce26e55414e219fe00360e24b4f19",
        assistant_voice_name: "神秘的古代机械",
        vad_enabled: "false",
      },
    };
  }

  private configSet(_params: Record<string, unknown>): {
    config: ReturnType<MockDesktopBackend["configGet"]>;
  } {
    return { config: this.configGet() };
  }

  emitQueueChanged(conversationId: string, items: QueueItem[]): void {
    this.scenario.snapshot.queue_items = items;
    this.emit("queue.changed", { conversation_id: conversationId, items });
  }

  private editQueueItem(params: Record<string, unknown>): { queue_item: QueueItem } {
    const queueItemId = String(params.queue_item_id ?? "");
    const text = String(params.text ?? "");
    const items = this.scenario.snapshot.queue_items.map((item) =>
      item.queue_item_id === queueItemId && item.status === "queued"
        ? { ...item, text }
        : item,
    );
    const queueItem = items.find((item) => item.queue_item_id === queueItemId)!;
    this.emitQueueChanged(queueItem.conversation_id, items);
    return { queue_item: queueItem };
  }

  private withdrawQueueItem(params: Record<string, unknown>): { queue_item: QueueItem } {
    const queueItemId = String(params.queue_item_id ?? "");
    const items = this.scenario.snapshot.queue_items.map((item) =>
      item.queue_item_id === queueItemId ? { ...item, status: "withdrawn" as const } : item,
    );
    const queueItem = items.find((item) => item.queue_item_id === queueItemId)!;
    this.emitQueueChanged(queueItem.conversation_id, items);
    return { queue_item: queueItem };
  }

  private prioritizeQueueItem(params: Record<string, unknown>): { queue_item: QueueItem } {
    const queueItemId = String(params.queue_item_id ?? "");
    // 与后端一致：其余 queued 项 position + 1，目标项置队首
    const items = this.scenario.snapshot.queue_items
      .map((item) =>
        item.queue_item_id === queueItemId && item.status === "queued"
          ? { ...item, position: 0 }
          : item.status === "queued"
            ? { ...item, position: item.position + 1 }
            : item,
      )
      .sort((a, b) => a.position - b.position);
    const queueItem = items.find((item) => item.queue_item_id === queueItemId)!;
    this.emitQueueChanged(queueItem.conversation_id, items);
    return { queue_item: queueItem };
  }

  private setVoiceState(changes: Record<string, unknown>): { voice: DesktopSnapshot["voice"] } {
    const voice = { ...this.scenario.snapshot.voice, ...changes };
    this.emit("voice.state_changed", { voice });
    return { voice: this.clone(voice) };
  }

  private refreshCurrentPointers(): void {
    const snapshot = this.scenario.snapshot;
    const projectRecord = snapshot.projects.find(
      (item) => item.project_id === snapshot.current_project_id,
    ) ?? snapshot.projects.find((item) => !item.archived);
    const conversationRecord = projectRecord?.conversations.find(
      (item) => item.conversation_id === snapshot.current_conversation_id && !item.archived,
    ) ?? projectRecord?.conversations.find((item) => !item.archived);
    snapshot.current_project_id = projectRecord?.project_id ?? "";
    snapshot.current_conversation_id = conversationRecord?.conversation_id ?? "";
    snapshot.current_project = projectRecord
      ? projectWithoutConversations(projectRecord)
      : emptyProject();
    snapshot.current_conversation = conversationRecord ?? emptyConversation(snapshot.pair.pair_id);
  }

  private applyEventToSnapshot(event: DesktopEvent): void {
    const snapshot = this.scenario.snapshot;
    if (event.event === "message.created") {
      const message = event.payload.message as Message;
      snapshot.messages = [
        ...snapshot.messages.filter((item) => item.message_id !== message.message_id),
        message,
      ];
    } else if (event.event === "message.delta") {
      const payload = event.payload as unknown as MessageDeltaPayload;
      const current = snapshot.messages.find((item) => item.message_id === payload.message_id);
      const nextMessage = applyMessageDelta(current, payload, {
        pairId: snapshot.pair.pair_id,
        createdAt: new Date().toISOString(),
      });
      snapshot.messages = [
        ...snapshot.messages.filter((item) => item.message_id !== payload.message_id),
        nextMessage,
      ];
    } else if (event.event === "message.finalized") {
      const messageId = String(event.payload.message_id ?? "");
      snapshot.messages = snapshot.messages.map((item) =>
        item.message_id === messageId ? { ...item, streaming: false } : item,
      );
    } else if (event.event === "message.status_changed") {
      const message = event.payload.message as Message;
      snapshot.messages = snapshot.messages.map((item) =>
        item.message_id === message.message_id ? message : item,
      );
    } else if (event.event === "tool_run.upserted") {
      const toolRun = event.payload.tool_run as ToolRun;
      snapshot.tool_runs = [
        ...snapshot.tool_runs.filter((item) => item.tool_call_id !== toolRun.tool_call_id),
        toolRun,
      ];
    } else if (event.event === "conversation.changed") {
      const conversation = event.payload.conversation as ConversationRecord;
      snapshot.projects = snapshot.projects.map((item) => ({
        ...item,
        conversations: item.conversations.map((candidate) =>
          candidate.conversation_id === conversation.conversation_id ? conversation : candidate,
        ),
      }));
    } else if (event.event === "turn.started" || event.event === "turn.status_changed") {
      const turn = event.payload.turn as DesktopSnapshot["turns"][number];
      snapshot.turns = [
        ...snapshot.turns.filter((item) => item.turn_id !== turn.turn_id),
        turn,
      ];
    } else if (event.event === "task.busy_changed") {
      snapshot.busy = Boolean(event.payload.busy);
      snapshot.active_task = event.payload.active_task as DesktopSnapshot["active_task"];
      snapshot.active_tasks = event.payload.active_tasks as DesktopSnapshot["active_tasks"];
    } else if (event.event === "approval.requested") {
      snapshot.approvals = [
        ...snapshot.approvals,
        event.payload as unknown as PendingApproval,
      ];
    } else if (event.event === "approval.resolved") {
      const approvalId = String(event.payload.approval_id ?? "");
      snapshot.approvals = snapshot.approvals.filter((item) => item.approval_id !== approvalId);
    } else if (event.event === "voice.state_changed") {
      snapshot.voice = { ...snapshot.voice, ...(event.payload.voice as Partial<DesktopSnapshot["voice"]>) };
    } else if (event.event === "voice.asr_partial") {
      snapshot.voice = { ...snapshot.voice, asr_partial: String(event.payload.text ?? "") };
    } else if (event.event === "power.status_changed") {
      // 快照没有电源字段，mock 记录最新状态供开发与测试检查。
      this.lastPowerStatus = event.payload as unknown as PowerStatusPayload;
    }
  }

  private clone<T>(value: T): T {
    return JSON.parse(JSON.stringify(value)) as T;
  }

  nextRequestId(): string {
    return this.requestIds.next();
  }
}

function mockTurn(
  turnId: string,
  projectId: string,
  conversationId: string,
  target: Turn["target"],
  sourceMessageId: string,
  status: Turn["status"],
): Turn {
  return {
    turn_id: turnId,
    account_id: "",
    project_id: projectId,
    conversation_id: conversationId,
    target,
    source_message_id: sourceMessageId,
    status,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function projectWithoutConversations(projectRecord: ProjectRecord): DesktopSnapshot["current_project"] {
  const { conversations: _conversations, ...currentProject } = projectRecord;
  return currentProject;
}

function emptyProject(): DesktopSnapshot["current_project"] {
  return {
    project_id: "",
    name: "",
    root_path: "",
    approval_mode: "request_approval",
    reasoning_effort: "low",
    archived: false,
    created_at: null,
    last_opened_at: null,
    path_available: false,
  };
}

function emptyConversation(pairId: string): ConversationRecord {
  return {
    conversation_id: "",
    project_id: null,
    pair_id: pairId,
    title: "",
    last_mode: "chat",
    archived: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function createSubmitEvents(
  conversationId: string,
  _text: string,
  target: "character" | "assistant",
): DesktopEvent[] {
  const source = target === "assistant" ? "assistant" : "character";
  const kind = target === "assistant" ? "assistant.natural_language" : "character.speech";
  const messageId = `mock-${source}-${Date.now()}`;
  return [
    {
      kind: "event",
      event: "message.delta",
      sequence: 0,
      payload: {
        message_id: messageId,
        conversation_id: conversationId,
        source,
        kind,
        delta: target === "assistant" ? "我会先检查这个任务。" : "好，我们继续。",
        timeline_order: nextTimelineOrder(),
      },
    },
    {
      kind: "event",
      event: "message.finalized",
      sequence: 0,
      payload: { message_id: messageId, conversation_id: conversationId },
    },
  ];
}

function folderNameFromPath(rootPath: string): string | null {
  const parts = rootPath.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? null;
}
