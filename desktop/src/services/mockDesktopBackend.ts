import type {
  CardAvatarPayload,
  CardSummaryPayload,
  CharacterVoiceState,
  ConversationRecord,
  DesktopCommand,
  DesktopEvent,
  DesktopSnapshot,
  Message,
  PendingApproval,
  PairRecord,
  ProjectRecord,
  QueueItem,
  ToolRun,
  Turn,
} from "../contracts/protocol";
import type { FileFilter } from "./backend";
import {
  APPROVAL_ALREADY_RESOLVED,
  CARD_AVATAR_TOO_LARGE,
  CARD_AVATAR_UNSUPPORTED,
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
import {
  createMockScenario,
  conversation,
  message,
  project,
  type MockScenario,
  type MockScenarioName,
} from "../mocks/scenarios";
import {
  MOCK_BUILTIN_CARDS,
  MOCK_ARCHIVED_CARD_IDS,
  MOCK_REMOTE_DEVICES,
  MOCK_USER_CARDS,
  mockCardPayload,
} from "../mocks/characterCards";

/** V0.3.5 mock 后端可配置开关，便于 UI 开发与测试覆盖异常路径。 */
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
  private readonly listeners = new Set<(event: DesktopEvent) => void>();
  private readonly requestIds = new RequestIdFactory();
  private scenario: MockScenario;
  private sequence: number;
  /** 记录全部 request 命令（供测试断言接线与参数，不参与 mock 行为）。 */
  readonly recordedRequests: DesktopCommand[] = [];

  /* V0.3.3：角色卡 mock 可变状态（card.* 命令模拟；样例数据见 mocks/characterCards）。 */
  private cards: CardSummaryPayload[] = MOCK_USER_CARDS.map((card) => ({ ...card }));
  private archivedCardIds = new Set<string>(MOCK_ARCHIVED_CARD_IDS);

  /* V0.3.5：mock 可配置开关。 */
  voiceConfigured: boolean;
  voiceProvisionFail: boolean;
  mobileTranscriptEmpty: boolean;
  pickFileResult: string | null;
  saveFileResult: string | null;

  /* V0.3.5：角色卡头像/参考音频/音色创建状态。 */
  private cardAvatars = new Map<string, CardAvatarPayload>();
  private cardReferenceAudios = new Map<string, { asset_id: string; duration_seconds: number; size_bytes: number; mime_type: string }>();
  private voiceProvisioningCardIds = new Set<string>();
  private voiceProfiles = new Map<string, { voice_id: string; state: CharacterVoiceState }>();

  /* V0.3.5：审批仲裁状态。 */
  private resolvedApprovals = new Map<string, { decision: string; resolved_by: string }>();

  /* V0.3.5：手机语音会话状态。 */
  private mobileAudioSessions = new Map<string, { conversation_id: string; last_seq: number | null }>();

  constructor(
    scenarioName: MockScenarioName = "single-project",
    options: MockDesktopBackendOptions = {},
  ) {
    this.scenario = createMockScenario(scenarioName);
    this.sequence = this.scenario.snapshot.sequence;
    this.voiceConfigured = options.voiceConfigured ?? true;
    this.voiceProvisionFail = options.voiceProvisionFail ?? false;
    this.mobileTranscriptEmpty = options.mobileTranscriptEmpty ?? false;
    this.pickFileResult = options.pickFileResult ?? null;
    this.saveFileResult = options.saveFileResult ?? null;
  }

  setScenario(name: MockScenarioName): void {
    this.scenario = createMockScenario(name);
    this.sequence = this.scenario.snapshot.sequence;
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

  async request<T>(command: DesktopCommand): Promise<T> {
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
        // V0.2 M4：mock 简化——跳下一条等价于停止播放（tts 回 idle）
        return this.setVoiceState({ tts: "idle" }) as T;
      case "account.list":
        return this.accountList() as T;
      case "account.register":
        return this.accountRegister(command.params) as T;
      case "account.login":
        return this.accountLogin(command.params) as T;
      case "account.logout":
        return this.accountLogin({ account_id: "default-local", password: "" }) as T;
      case "account.onboarding_complete":
        return this.accountCompleteOnboarding() as T;
      case "account.update_profile":
        return this.updateAccountProfile(command.params) as T;
      case "account.change_password":
        return { changed: true } as T;
      case "config.get":
        return this.configGet() as T;
      case "config.set":
        return this.configSet(command.params) as T;
      case "config.test_connection":
        return { ok: true, message: "连接正常（延迟 12 ms）" } as T;
      case "codex.oauth_start":
        return { status: "waiting", note: "mock 登录" } as T;
      case "codex.oauth_status":
        return { status: "logged_in", account_label: "mock@openai" } as T;
      case "codex.logout":
        return { status: "logged_out" } as T;
      case "codex.api_login":
        return { status: "logged_in", account_label: "OpenAI API Key" } as T;
      case "voice.preview":
        return { voice: this.scenario.snapshot.voice } as T;
      case "voice.provision":
        throw new Error("Mock 后端不提供真实音色生成；请在 Tauri + Python Sidecar 中联调");
      /* —— V0.3.3 角色卡（card.*）与远程配对（remote.*）—— */
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
      case "card.delete":
        return this.cardDelete(command.params) as T;
      case "card.select_active":
        return this.cardSelectActive(command.params) as T;
      /* —— V0.3.5 角色卡导入导出/发布/头像 —— */
      case "card.peek_import_json":
        return this.cardPeekImportJson(command.params) as T;
      case "card.import_json":
        return this.cardImportJson(command.params) as T;
      case "card.export_json":
        return this.cardExportJson(command.params) as T;
      case "card.publish":
        return this.cardPublish(command.params) as T;
      case "card.set_avatar":
        return this.cardSetAvatar(command.params) as T;
      case "card.remove_avatar":
        return this.cardRemoveAvatar(command.params) as T;
      /* —— V0.3.5 角色卡音色 —— */
      case "voice.card_bind_reference":
        return this.voiceCardBindReference(command.params) as T;
      case "voice.card_create":
        return this.voiceCardCreate(command.params) as T;
      case "voice.card_unbind":
        return this.voiceCardUnbind(command.params) as T;
      case "voice.card_preview":
        return this.voiceCardPreview(command.params) as T;
      /* —— V0.3.5 手机远程语音 —— */
      case "voice.mobile_ptt_start":
        return this.voiceMobilePttStart(command.params) as T;
      case "voice.mobile_audio_chunk":
        return this.voiceMobileAudioChunk(command.params) as T;
      case "voice.mobile_ptt_stop":
        return this.voiceMobilePttStop(command.params) as T;
      case "voice.mobile_tts_stop":
        return {} as T;
      case "remote.issue_code":
        return { code: "483920", ttl_seconds: 300 } as T;
      case "remote.pair":
        return { token: "mock-remote-token" } as T;
      case "remote.list_devices":
        return { devices: MOCK_REMOTE_DEVICES } as T;
      case "remote.revoke":
        return {
          device_name: String(command.params.device_name ?? ""),
          revoked_tokens: 1,
        } as T;
      default:
        // 尚未实现的 V0.2 命令在 mock 中返回空对象（不阻断前端流程）
        return {} as T;
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

  async openChatWindow(_conversationId: string, _projectId: string, _title: string): Promise<string> {
    throw new Error("独立聊天窗口需要在 Tauri 桌面运行时打开");
  }

  async reconnectSidecar(): Promise<void> {
    // 模拟一次断线-恢复：先断开并上报可恢复错误，随后立即恢复
    // （connection.status connected 会驱动 store 进入 booting 并重新 bootstrap）。
    this.emit("connection.status", { status: "disconnected" });
    this.emit("error.reported", {
      code: "backend_disconnected",
      message: "Python Sidecar 已断开，正在重连…",
      severity: "recoverable",
      source: "sidecar",
    });
    this.emit("connection.status", { status: "connected" });
  }

  /* —— V0.3.3 card.* mock 实现（真实失败直接抛错，不合成成功）—— */

  private activeCardId: string | null = "card-saved-002";

  private cardList(params: Record<string, unknown>): { cards: CardSummaryPayload[] } {
    const includeArchived = params.include_archived === true;
    const cards = this.cards
      .filter((card) => includeArchived || !this.archivedCardIds.has(card.card_id))
      .map((card) => ({ ...card, active: card.card_id === this.activeCardId }));
    return { cards: [...cards, ...MOCK_BUILTIN_CARDS.map((card) => ({ ...card }))] };
  }

  private cardGet(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const builtin = MOCK_BUILTIN_CARDS.find((card) => card.card_id === cardId);
    if (builtin) {
      return {
        card_id: builtin.card_id,
        state: builtin.state,
        source: builtin.source,
        created_at: "",
        updated_at: "",
        card: mockCardPayload(builtin.name),
        read_only: true,
        avatar: this.cardAvatars.get(cardId) ?? null,
      };
    }
    const found = this.cards.find((card) => card.card_id === cardId);
    if (!found) throw new Error("角色卡不存在");
    return {
      card_id: found.card_id,
      state: found.state,
      source: found.source,
      created_at: found.updated_at,
      updated_at: found.updated_at,
      card: mockCardPayload(found.name),
      read_only: false,
      avatar: this.cardAvatars.get(cardId) ?? null,
    };
  }

  private cardCreateDraft(params: Record<string, unknown>) {
    const name = String(params.name ?? "").trim();
    if (!name) throw new Error("card.create_draft 需要 name");
    const cardId = `card-mock-${this.cards.length + 1}`;
    const now = new Date().toISOString();
    this.cards = [
      {
        card_id: cardId,
        name,
        state: "draft",
        source: "user_created",
        updated_at: now,
        has_avatar: false,
        voice_state: "voice_unconfigured" as const,
        active: false,
        read_only: false,
      },
      ...this.cards,
    ];
    return { card_id: cardId, state: "draft" };
  }

  private cardUpdate(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const now = new Date().toISOString();
    this.cards = this.cards.map((card) =>
      card.card_id === cardId ? { ...card, updated_at: now } : card,
    );
    return { card_id: cardId, updated_at: now };
  }

  private cardDuplicate(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const source = this.cards.find((card) => card.card_id === cardId);
    if (!source) throw new Error("角色卡不存在");
    const newId = `card-mock-copy-${this.cards.length + 1}`;
    const name = `${source.name}（副本）`;
    this.cards = [{ ...source, card_id: newId, name, active: false }, ...this.cards];
    return { card_id: newId, name };
  }

  private cardArchive(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const source = this.cards.find((card) => card.card_id === cardId);
    if (!source) throw new Error("角色卡不存在");
    if (source.state === "draft") throw new Error("草稿不能归档，请先保存");
    this.archivedCardIds.add(cardId);
    return { card_id: cardId, archived: true };
  }

  private cardDelete(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    if (params.confirm !== true) throw new Error("删除需要确认");
    this.cards = this.cards.filter((card) => card.card_id !== cardId);
    this.archivedCardIds.delete(cardId);
    this.cardAvatars.delete(cardId);
    this.cardReferenceAudios.delete(cardId);
    this.voiceProfiles.delete(cardId);
    return { card_id: cardId, deleted: true };
  }

  private cardSelectActive(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    if (this.archivedCardIds.has(cardId)) {
      throw new Error(`已归档角色卡不能设为当前使用: ${cardId}`);
    }
    this.activeCardId = cardId;
    return { card_id: cardId };
  }

  /* —— V0.3.5 角色卡导入导出/发布/头像 mock 实现 —— */

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
        not_executed: ["data.extensions.hsr.command_panels"],
        normalized_from_root: [],
        warnings: [],
        errors: [],
      },
    };
  }

  private cardPeekImportJson(params: Record<string, unknown>) {
    const path = String(params.path ?? "");
    if (path.includes("invalid") || path.includes("missing")) {
      const error = new Error(`模拟导入失败：无法解析 ${path}`);
      (error as Error & { code?: string }).code = CARD_IMPORT_FAILED;
      throw error;
    }
    return { preview: this.sampleBaiImportPreview() };
  }

  private cardImportJson(params: Record<string, unknown>) {
    const path = String(params.path ?? "");
    if (path.includes("invalid") || path.includes("missing")) {
      const error = new Error(`模拟导入失败：无法解析 ${path}`);
      (error as Error & { code?: string }).code = CARD_IMPORT_FAILED;
      throw error;
    }
    const asDuplicate = params.as_duplicate === true;
    const preview = this.sampleBaiImportPreview();
    const now = new Date().toISOString();
    const cardId = `card-imported-${this.cards.length + 1}`;
    const name = asDuplicate ? `${preview.name}（副本）` : preview.name;
    this.cards = [
      {
        card_id: cardId,
        name,
        state: "imported",
        source: "imported_json",
        updated_at: now,
        has_avatar: false,
        voice_state: "voice_unconfigured",
        active: false,
        read_only: false,
      },
      ...this.cards,
    ];
    return { card_id: cardId, name, state: "imported", report: preview.report };
  }

  private cardExportJson(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    if (cardId.startsWith("builtin:")) {
      const error = new Error("内置角色卡只读，导出前请先复制");
      (error as Error & { code?: string }).code = CARD_READ_ONLY;
      throw error;
    }
    const path = String(params.path ?? "");
    const saveAvatar = params.save_avatar === true;
    return {
      exported: true,
      path,
      avatar_saved: saveAvatar && this.cardAvatars.has(cardId),
    };
  }

  private cardPublish(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const card = this.cards.find((item) => item.card_id === cardId);
    if (!card) throw new Error("角色卡不存在");
    if (card.state !== "draft") {
      return { card_id: cardId, state: card.state };
    }
    const payload = mockCardPayload(card.name);
    const firstMes = String((payload.data as Record<string, unknown>)?.first_mes ?? "");
    if (!card.name.trim()) {
      const error = new Error("card_publish_invalid：缺少 name");
      (error as Error & { code?: string }).code = CARD_PUBLISH_INVALID;
      throw error;
    }
    if (!firstMes.trim()) {
      const error = new Error("card_publish_invalid：缺少 first_mes");
      (error as Error & { code?: string }).code = CARD_PUBLISH_INVALID;
      throw error;
    }
    this.cards = this.cards.map((item) =>
      item.card_id === cardId ? { ...item, state: "saved" as const } : item,
    );
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
    const cardId = String(params.card_id ?? "");
    const path = String(params.path ?? "");
    const mimeType = this.avatarMimeFromPath(path);
    if (!mimeType) {
      const error = new Error("card_avatar_unsupported：仅支持 png/jpeg/webp");
      (error as Error & { code?: string }).code = CARD_AVATAR_UNSUPPORTED;
      throw error;
    }
    // mock 不读真实文件，固定返回 1x1 PNG data URI 占位。
    const dataUri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
    const base64 = dataUri.split(",")[1] ?? "";
    const assetId = `avatar-${cardId}`;
    this.cardAvatars.set(cardId, { mime_type: mimeType, data_base64: base64 });
    this.cards = this.cards.map((card) =>
      card.card_id === cardId ? { ...card, has_avatar: true } : card,
    );
    return { card_id: cardId, asset_id: assetId, mime_type: mimeType };
  }

  private cardRemoveAvatar(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    this.cardAvatars.delete(cardId);
    this.cards = this.cards.map((card) =>
      card.card_id === cardId ? { ...card, has_avatar: false } : card,
    );
    return { card_id: cardId, removed: true };
  }

  /* —— V0.3.5 角色卡音色 mock 实现 —— */

  private referenceMimeFromPath(path: string): string | null {
    const lower = path.toLowerCase();
    if (lower.endsWith(".wav")) return "audio/wav";
    if (lower.endsWith(".mp3")) return "audio/mpeg";
    if (lower.endsWith(".m4a")) return "audio/mp4";
    return null;
  }

  private voiceCardBindReference(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const path = String(params.path ?? "");
    const mimeType = this.referenceMimeFromPath(path);
    if (!mimeType) {
      const error = new Error("voice_reference_invalid：仅支持 wav/mp3/m4a");
      (error as Error & { code?: string }).code = VOICE_REFERENCE_INVALID;
      throw error;
    }
    const assetId = `ref-audio-${cardId}`;
    const asset = { asset_id: assetId, duration_seconds: 5.2, size_bytes: 102400, mime_type: mimeType };
    this.cardReferenceAudios.set(cardId, asset);
    return { card_id: cardId, ...asset };
  }

  private voiceCardCreate(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const mode = String(params.mode ?? "clone") as "clone" | "design";
    if (!this.voiceConfigured) {
      const error = new Error("voice_not_configured：账号未配置语音 Key");
      (error as Error & { code?: string }).code = VOICE_NOT_CONFIGURED;
      throw error;
    }
    if (this.voiceProvisioningCardIds.has(cardId)) {
      const error = new Error("voice_card_provision_in_progress：同卡创建中");
      (error as Error & { code?: string }).code = VOICE_CARD_PROVISION_IN_PROGRESS;
      throw error;
    }
    if (mode === "clone" && !this.cardReferenceAudios.has(cardId)) {
      const error = new Error("voice_reference_missing：clone 模式需要参考音频");
      (error as Error & { code?: string }).code = VOICE_REFERENCE_MISSING;
      throw error;
    }
    this.voiceProvisioningCardIds.add(cardId);
    this.emit("voice.card_provision_changed", { card_id: cardId, state: "voice_creating", voice_id: null, error: null });
    const voiceId = `mock-voice-${Math.random().toString(36).slice(2, 8)}`;
    setTimeout(() => {
      if (this.voiceProvisionFail) {
        this.voiceProfiles.set(cardId, { voice_id: "", state: "voice_failed" });
        this.voiceProvisioningCardIds.delete(cardId);
        this.emit("voice.card_provision_changed", {
          card_id: cardId,
          state: "voice_failed",
          voice_id: null,
          error: "模拟音色创建失败",
        });
        return;
      }
      this.voiceProfiles.set(cardId, { voice_id: voiceId, state: "voice_ready" });
      this.voiceProvisioningCardIds.delete(cardId);
      this.cards = this.cards.map((card) =>
        card.card_id === cardId ? { ...card, voice_state: "voice_ready" as const } : card,
      );
      this.emit("voice.card_provision_changed", {
        card_id: cardId,
        state: "voice_ready",
        voice_id: voiceId,
        error: null,
      });
    }, 50);
    return { card_id: cardId, state: "voice_ready", voice_id: voiceId };
  }

  private voiceCardUnbind(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    this.voiceProfiles.delete(cardId);
    this.cards = this.cards.map((card) =>
      card.card_id === cardId ? { ...card, voice_state: "voice_unconfigured" as const } : card,
    );
    return { card_id: cardId, state: "voice_unconfigured" };
  }

  private voiceCardPreview(params: Record<string, unknown>) {
    const cardId = String(params.card_id ?? "");
    const profile = this.voiceProfiles.get(cardId);
    if (!profile || profile.state !== "voice_ready") {
      const error = new Error("voice_card_not_ready：卡音色未就绪");
      (error as Error & { code?: string }).code = VOICE_CARD_NOT_READY;
      throw error;
    }
    return { voice: { voice_id: profile.voice_id, state: profile.state } };
  }

  /* —— V0.3.5 手机远程语音 mock 实现 —— */

  private voiceMobilePttStart(params: Record<string, unknown>) {
    const conversationId = String(params.conversation_id ?? "");
    const sessionId = `mobile-ptt-${this.sequence + 1}`;
    this.mobileAudioSessions.set(sessionId, { conversation_id: conversationId, last_seq: null });
    return { session_id: sessionId };
  }

  private voiceMobileAudioChunk(params: Record<string, unknown>) {
    const sessionId = String(params.session_id ?? "");
    const seq = Number(params.seq ?? -1);
    const session = this.mobileAudioSessions.get(sessionId);
    if (!session) throw new Error("转写会话不存在");
    if (session.last_seq !== null && seq !== session.last_seq + 1) {
      const error = new Error("voice_audio_seq_gap：音频分片 seq 不连续");
      (error as Error & { code?: string }).code = VOICE_AUDIO_SEQ_GAP;
      throw error;
    }
    session.last_seq = seq;
    return {};
  }

  private voiceMobilePttStop(params: Record<string, unknown>) {
    const sessionId = String(params.session_id ?? "");
    const session = this.mobileAudioSessions.get(sessionId);
    if (!session) throw new Error("转写会话不存在");
    const conversationId = session.conversation_id;
    const transcript = this.mobileTranscriptEmpty ? "" : "模拟手机语音转写文本";
    if (transcript === "") {
      const error = new Error("voice_transcript_empty：转写结果为空");
      (error as Error & { code?: string }).code = VOICE_TRANSCRIPT_EMPTY;
      throw error;
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

  /* —— V0.3.5 审批仲裁 mock 实现 —— */

  private resolveApproval(params: Record<string, unknown>) {
    const approvalId = String(params.approval_id ?? "");
    const decision = String(params.decision ?? "approve");
    const existing = this.resolvedApprovals.get(approvalId);
    if (existing) {
      const error = new Error(`已由 ${existing.resolved_by} ${existing.decision === "approve" ? "批准" : "拒绝"}`);
      (error as Error & { code?: string }).code = APPROVAL_ALREADY_RESOLVED;
      throw error;
    }
    const resolvedBy = "desktop";
    this.resolvedApprovals.set(approvalId, { decision, resolved_by: resolvedBy });
    this.emit("approval.resolved", { approval_id: approvalId, decision, resolved_by: resolvedBy });
    return { accepted: true };
  }

  subscribe(listener: (event: DesktopEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(event: DesktopEvent["event"], payload: Record<string, unknown>): void {
    const message: DesktopEvent = {
      kind: "event",
      event,
      sequence: this.sequence + 1,
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

  private updateProjectSettings(params: Record<string, unknown>): { project: ProjectRecord } {
    const projectId = String(params.project_id ?? this.scenario.snapshot.current_project_id);
    const projects = this.scenario.snapshot.projects.map((item) =>
      item.project_id === projectId
        ? {
            ...item,
            name: String(params.name ?? item.name),
            root_path: String(params.root_path ?? item.root_path),
            path_available: params.root_path ? true : item.path_available,
            approval_mode: (params.approval_mode as ProjectRecord["approval_mode"]) ?? item.approval_mode,
            reasoning_effort: String(params.reasoning_effort ?? item.reasoning_effort),
          }
        : item,
    );
    this.scenario.snapshot.projects = projects;
    const project = projects.find((item) => item.project_id === projectId)!;
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

  private createConversation(params: Record<string, unknown>): DesktopSnapshot {
    const projectId = String(params.project_id ?? this.scenario.snapshot.current_project_id);
    const projectIndex = this.scenario.snapshot.projects.findIndex(
      (item) => item.project_id === projectId,
    );
    if (projectIndex < 0) return this.snapshotResult<DesktopSnapshot>();
    const selectedProject = this.scenario.snapshot.projects[projectIndex];
    const conversationId = `${projectId}-conversation-${selectedProject.conversations.length + 1}`;
    const pairId =
      typeof params.pair_id === "string"
        ? params.pair_id
        : this.scenario.snapshot.pair?.pair_id ?? "phainon_ancient_machine";
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
    return this.snapshotResult<DesktopSnapshot>();
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

  private openConversation(params: Record<string, unknown>): {
    conversation: ConversationRecord;
    project: ProjectRecord;
    pair: PairRecord;
    messages: Message[];
    tool_runs: ToolRun[];
    turns: Turn[];
    queue_items: QueueItem[];
    active_task: DesktopSnapshot["active_task"];
  } {
    const conversationId = String(params.conversation_id ?? "");
    const selectedProject = this.scenario.snapshot.projects.find((candidate) =>
      candidate.conversations.some((item) => item.conversation_id === conversationId),
    );
    const selectedConversation = selectedProject?.conversations.find(
      (item) => item.conversation_id === conversationId,
    );
    if (!selectedProject || !selectedConversation) {
      throw new Error(`找不到聊天 ${conversationId}`);
    }
    const selectedPair =
      this.scenario.snapshot.pairs.find((item) => item.pair_id === selectedConversation.pair_id) ??
      this.scenario.snapshot.pair;
    const activeTasks = this.scenario.snapshot.active_tasks ?? [];
    return {
      conversation: this.clone(selectedConversation),
      project: this.clone(selectedProject),
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
    };
  }

  private cancelTask(params: Record<string, unknown>): { cancelled: true; conversation_id: string; task_id: string } {
    const conversationId = String(params.conversation_id ?? "");
    const taskId = String(params.task_id ?? "");
    const activeTasks = this.scenario.snapshot.active_tasks ?? [];
    const active = activeTasks.find(
      (item) => item.conversation_id === conversationId && item.task_id === taskId,
    );
    if (!active) {
      throw new Error("当前聊天没有匹配的活动任务");
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
    return { cancelled: true, conversation_id: conversationId, task_id: taskId };
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

  private archiveConversation(params: Record<string, unknown>): DesktopSnapshot {
    const conversationId = String(
      params.conversation_id ?? this.scenario.snapshot.current_conversation_id,
    );
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
      ...item,
      conversations: item.conversations.map((candidate) =>
        candidate.conversation_id === conversationId ? { ...candidate, archived: true } : candidate,
      ),
    }));
    if (conversationId === this.scenario.snapshot.current_conversation_id) {
      const fallback = this.scenario.snapshot.projects
        .flatMap((item) => item.conversations)
        .find((candidate) => !candidate.archived);
      this.scenario.snapshot.current_conversation_id = fallback?.conversation_id ?? "";
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
    const hadUserMessage = this.scenario.snapshot.messages.some(
      (item) => item.conversation_id === conversationId && item.source === "user",
    );
    const text = String(params.text ?? "");
    const userMessageId = `mock-user-${this.sequence + 1}`;
    // 快速接受：用户消息立即落库并返回真实 id
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
    // V0.2 M2：Turn 生命周期模拟——accepted → running → completed
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
    if (!hadUserMessage) {
      const title = titleFromMessage(text);
      this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
        ...item,
        conversations: item.conversations.map((candidate) =>
          candidate.conversation_id === conversationId && candidate.title === "新聊天"
            ? { ...candidate, title, updated_at: new Date().toISOString() }
            : candidate,
        ),
      }));
      const conversation = this.scenario.snapshot.projects
        .flatMap((item) => item.conversations)
        .find((item) => item.conversation_id === conversationId);
      if (conversation) this.emit("conversation.changed", { conversation });
    }
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

  private accountRegister(params: Record<string, unknown>): {
    account: DesktopSnapshot["current_account"];
    accounts: DesktopSnapshot["accounts"];
  } {
    const username = String(params.username ?? "mock-user");
    const account = {
      account_id: `mock-account-${this.scenario.snapshot.accounts.length + 1}`,
      username,
      display_name: String(params.display_name ?? username),
      avatar: "",
      last_login_at: null,
      onboarding_complete: false,
      theme: "dark" as const,
    };
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
    const accountId = String(params.account_id ?? "default-local");
    const account = this.scenario.snapshot.accounts.find(
      (item) => item.account_id === accountId,
    ) ?? this.scenario.snapshot.accounts[0];
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
    // V0.2 M4：首次引导完成——置 onboarding_complete 并广播 account.changed
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
    dialogue: Record<string, string>;
    voice: Record<string, string>;
    codex: Record<string, string | null>;
  } {
    return {
      engine: "deepseek",
      dialogue: {
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com",
        api_key_masked: "sk-d…1234",
        reasoning_effort: "auto",
      },
      voice: {
        enabled: "true",
        assistant_voice_enabled: "false",
        base_url: "https://dashscope.aliyuncs.com/api/v1",
        api_key_masked: "sk-v…5678",
        asr_model: "qwen-audio-3.0-asr-flash-streaming",
        tts_model: "qwen-audio-3.0-tts-flash",
        character_voice: "qwen-audio-3.0-tts-flash-phainon-46e9bd0087cd4c4c8d29e1b9f1b5db32",
        character_voice_name: "白厄",
        assistant_voice: "qwen-audio-3.0-tts-flash-vd-ancientmac-a26ce26e55414e219fe00360e24b4f19",
        assistant_voice_name: "神秘的古代机械",
        vad_enabled: "false",
      },
      codex: { status: "logged_in", account_label: "mock@openai" },
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
    snapshot.current_conversation = conversationRecord ?? emptyConversation();
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
      const payload = event.payload as {
        message_id: string;
        conversation_id: string;
        source: Message["source"];
        kind: Message["kind"];
        delta?: string;
        channel?: string;
        started?: boolean;
        completed?: boolean;
        reasoning_streaming?: boolean;
      };
      const current = snapshot.messages.find((item) => item.message_id === payload.message_id);
      const delta = String(payload.delta ?? "");
      const reasoningDelta =
        (payload.source === "character" && payload.channel === "reasoning") ||
        (payload.source === "assistant" && payload.kind === "assistant.reasoning");
      const messagePayload: Record<string, unknown> = { ...(current?.payload ?? {}) };
      let text = current?.text ?? "";
      if (payload.reasoning_streaming !== undefined) {
        messagePayload.reasoning_streaming = payload.reasoning_streaming;
      }
      if (reasoningDelta) {
        const reasoning = typeof messagePayload.reasoning === "string" ? messagePayload.reasoning : "";
        messagePayload.reasoning = reasoning + delta;
        if (payload.reasoning_streaming === undefined && (payload.started || payload.completed !== undefined)) {
          messagePayload.reasoning_streaming = !payload.completed;
        }
      } else {
        text += delta;
      }
      const nextMessage: Message = current
        ? { ...current, text, payload: messagePayload, streaming: true }
        : {
            message_id: payload.message_id,
            conversation_id: payload.conversation_id,
            pair_id: snapshot.pair.pair_id,
            engine_turn_id: null,
            source: payload.source,
            kind: payload.kind,
            text,
            payload: messagePayload,
            tts_eligible: payload.source === "character" || payload.source === "assistant",
            created_at: new Date().toISOString(),
            streaming: true,
          };
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
      const conversation = event.payload.conversation as ConversationRecord | undefined;
      if (conversation) {
        snapshot.projects = snapshot.projects.map((item) => ({
          ...item,
          conversations: item.conversations.map((candidate) =>
            candidate.conversation_id === conversation.conversation_id
              ? conversation
              : candidate,
          ),
        }));
      }
    } else if (event.event === "turn.started" || event.event === "turn.status_changed") {
      const turn = event.payload.turn as DesktopSnapshot["turns"][number];
      snapshot.turns = [
        ...snapshot.turns.filter((item) => item.turn_id !== turn.turn_id),
        turn,
      ];
    } else if (event.event === "task.busy_changed") {
      snapshot.busy = Boolean(event.payload.busy);
      snapshot.active_task = (event.payload.active_task as DesktopSnapshot["active_task"]) ?? null;
      if (Array.isArray(event.payload.active_tasks)) {
        snapshot.active_tasks = event.payload.active_tasks as DesktopSnapshot["active_tasks"];
      } else if (snapshot.active_task) {
        snapshot.active_tasks = [snapshot.active_task];
      } else if (!snapshot.busy) {
        snapshot.active_tasks = [];
      }
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

function emptyConversation(): ConversationRecord {
  return {
    conversation_id: "",
    project_id: null,
    pair_id: "phainon_ancient_machine",
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

function titleFromMessage(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return "新聊天";
  return `关于${compact.slice(0, 14)}`;
}

function folderNameFromPath(rootPath: string): string | null {
  const parts = rootPath.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? null;
}

export function isDesktopSnapshot(value: unknown): value is DesktopSnapshot {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as DesktopSnapshot).projects) &&
    typeof (value as DesktopSnapshot).current_conversation_id === "string"
  );
}
