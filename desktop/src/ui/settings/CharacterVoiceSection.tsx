import { useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type {
  CardGetResult,
  CharacterVoiceState,
  CharacterCardSource,
  CharacterCardState,
} from "../../contracts/protocol";
import type { FileFilter } from "../../services/backend";
import type { CharacterCardVoicePageViewModel } from "../../contracts/view-models";
import {
  CheckIcon,
  ErrorIcon,
  PlusIcon,
  RecordVoiceIcon,
  RefreshIcon,
  VoiceWaveIcon,
  WarningIcon,
} from "../../assets/icons/icons";

export interface CharacterVoiceSectionProps {
  characterVoice: CharacterCardVoicePageViewModel;
  voiceCardFocus?: string | null;
  /** V0.3.5：可选 actions；AppShell 传入后角色音色流程才可用。 */
  actions?: HarnessActions;
  /** V0.3.5：选择本地文件；AppShell 需传入 backend.pickFile 的包装。 */
  onPickFile?: (options?: {
    title?: string;
    filters?: FileFilter[];
  }) => Promise<string | null>;
  /** 滚动到语音页 DashScope 账号配置区（本页内跳转）。 */
  onScrollToAccountConfig?: () => void;
}

interface VoiceProfileDetail {
  voiceId: string;
  state: CharacterVoiceState;
  creationMode: string;
  prefix: string;
  referenceAudioAsset?: {
    asset_id: string;
    duration_seconds: number;
    size_bytes: number;
    mime_type: string;
  } | null;
  referenceAudioAssetId: string;
  lastError: string | null;
  updatedAt: string;
}

interface CardDetail {
  cardId: string;
  name: string;
  source: CharacterCardSource;
  state: CharacterCardState;
  readOnly: boolean;
  voiceProfile: VoiceProfileDetail;
}

type CreateMode = "clone" | "design";

type ConfirmAction = "recreate" | "unbind" | null;

const FIXED_ASR_MODEL = "qwen-audio-3.0-asr-flash-streaming";
const FIXED_TTS_MODEL = "qwen-audio-3.0-tts-flash";

function extractVoiceProfile(card: CardGetResult): VoiceProfileDetail {
  const root = (card.card ?? {}) as Record<string, unknown>;
  const data = (root.data ?? {}) as Record<string, unknown>;
  const extensions = (data.extensions ?? {}) as Record<string, unknown>;
  const hsr = (extensions.hsr ?? {}) as Record<string, unknown>;
  const profile = (hsr.voice_profile ?? {}) as Record<string, unknown>;
  const rawReference = profile.reference_audio_asset;
  let referenceAudioAsset: VoiceProfileDetail["referenceAudioAsset"] = null;
  let referenceAudioAssetId = "";
  if (typeof rawReference === "string" && rawReference) {
    referenceAudioAssetId = rawReference;
  } else if (
    rawReference !== null &&
    typeof rawReference === "object" &&
    typeof (rawReference as Record<string, unknown>).asset_id === "string"
  ) {
    const obj = rawReference as Record<string, unknown>;
    referenceAudioAssetId = String(obj.asset_id);
    referenceAudioAsset = {
      asset_id: referenceAudioAssetId,
      duration_seconds: Number(obj.duration_seconds) || 0,
      size_bytes: Number(obj.size_bytes) || 0,
      mime_type: String(obj.mime_type || ""),
    };
  }
  return {
    voiceId: typeof profile.voice_id === "string" ? profile.voice_id : "",
    state: normalizeVoiceState(profile.state),
    creationMode: typeof profile.creation_mode === "string" ? profile.creation_mode : "",
    prefix: typeof profile.prefix === "string" ? profile.prefix : "",
    referenceAudioAsset,
    referenceAudioAssetId,
    lastError: typeof profile.last_error === "string" ? profile.last_error : null,
    updatedAt: typeof profile.updated_at === "string" ? profile.updated_at : "",
  };
}

function normalizeVoiceState(value: unknown): CharacterVoiceState {
  if (
    value === "voice_unconfigured" ||
    value === "voice_creating" ||
    value === "voice_ready" ||
    value === "voice_failed"
  ) {
    return value;
  }
  return "voice_unconfigured";
}

function stateLabel(state: CharacterVoiceState): string {
  if (state === "voice_creating") return "创建中";
  if (state === "voice_ready") return "已绑定";
  if (state === "voice_failed") return "失败";
  return "未配置";
}

function sourceLabel(source: CharacterCardSource): string {
  if (source === "builtin") return "内置";
  if (source === "imported_json") return "导入 JSON";
  if (source === "imported_png") return "导入 PNG";
  return "自定义";
}

function formatDuration(seconds: number): string {
  const total = Math.round(seconds ?? 0);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function defaultPrefix(name: string): string {
  const normalized = name
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "")
    .slice(0, 10);
  return normalized || "card";
}

function isValidPrefix(value: string): boolean {
  return value === "" || /^[a-z0-9]{1,10}$/.test(value);
}

/** 角色音色区：选卡 → 绑参考音频 → 创建（clone/design）→ 进度/成功/失败/试听/解绑。 */
export function CharacterVoiceSection(props: CharacterVoiceSectionProps) {
  const { characterVoice, voiceCardFocus, actions, onPickFile, onScrollToAccountConfig } = props;

  const [selectedCardId, setSelectedCardId] = useState<string | null>(
    characterVoice.selectedCardId ?? voiceCardFocus ?? null,
  );
  const [cardDetail, setCardDetail] = useState<CardDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [createMode, setCreateMode] = useState<CreateMode>("clone");
  const [voicePrompt, setVoicePrompt] = useState("");
  const [previewText, setPreviewText] = useState("");
  const [prefix, setPrefix] = useState("");

  const [binding, setBinding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [unbinding, setUnbinding] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);

  // 与 presenter 视图的卡片摘要同步（列表、状态）。
  const selectedSummary =
    characterVoice.cards.find((card) => card.cardId === selectedCardId) ?? null;

  // voiceCardFocus 变化时同步选中。
  useEffect(() => {
    if (voiceCardFocus) setSelectedCardId(voiceCardFocus);
  }, [voiceCardFocus]);

  // 选中卡变化时拉取卡详情（参考音频/音色 id/失败错误以 cardGet 为准）。
  useEffect(() => {
    setOperationError(null);
    setCardDetail(null);
    setDetailError(null);
    if (!selectedCardId || !actions) {
      setDetailLoading(false);
      return;
    }
    setDetailLoading(true);
    let cancelled = false;
    actions
      .cardGet(selectedCardId)
      .then((result) => {
        if (cancelled) return;
        setCardDetail({
          cardId: result.card_id,
          name: String((result.card as Record<string, unknown>)?.data?.name ?? ""),
          source: result.source,
          state: result.state,
          readOnly: result.read_only,
          voiceProfile: extractVoiceProfile(result),
        });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setDetailError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedCardId, actions]);

  // 当外部 voiceState 从 creating 变成 ready/failed 时重新拉取详情，获取 voice_id/last_error。
  useEffect(() => {
    if (!selectedCardId || !actions || !cardDetail) return;
    if (
      cardDetail.voiceProfile.state === "voice_creating" &&
      selectedSummary?.voiceState !== "voice_creating"
    ) {
      setDetailLoading(true);
      actions
        .cardGet(selectedCardId)
        .then((result) => {
          setCardDetail({
            cardId: result.card_id,
            name: String((result.card as Record<string, unknown>)?.data?.name ?? ""),
            source: result.source,
            state: result.state,
            readOnly: result.read_only,
            voiceProfile: extractVoiceProfile(result),
          });
        })
        .catch((error: unknown) => setDetailError(error instanceof Error ? error.message : String(error)))
        .finally(() => setDetailLoading(false));
    }
  }, [selectedSummary?.voiceState, selectedCardId, actions, cardDetail]);

  // 切换卡时重置创建表单。
  useEffect(() => {
    setCreateMode("clone");
    setVoicePrompt("");
    setPreviewText("");
    setPrefix(cardDetail ? defaultPrefix(cardDetail.name) : "");
  }, [selectedCardId, cardDetail?.name]);

  const handlePickReference = async () => {
    if (!actions || !onPickFile || !selectedCardId) return;
    setOperationError(null);
    const path = await onPickFile({
      title: "选择参考音频",
      filters: [
        { name: "音频文件", extensions: ["wav", "mp3", "m4a"] },
        { name: "全部文件", extensions: ["*"] },
      ],
    });
    if (!path) return;
    setBinding(true);
    try {
      await actions.voiceCardBindReference(selectedCardId, path);
      const result = await actions.cardGet(selectedCardId);
      setCardDetail({
        cardId: result.card_id,
        name: String((result.card as Record<string, unknown>)?.data?.name ?? ""),
        source: result.source,
        state: result.state,
        readOnly: result.read_only,
        voiceProfile: extractVoiceProfile(result),
      });
    } catch (error: unknown) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setBinding(false);
    }
  };

  const handleCreate = async () => {
    if (!actions || !selectedCardId || !selectedSummary) return;
    setOperationError(null);
    setCreating(true);
    try {
      const opts: { prefix?: string; voicePrompt?: string; previewText?: string } = {};
      const trimmedPrefix = prefix.trim();
      if (trimmedPrefix) opts.prefix = trimmedPrefix;
      if (createMode === "design") {
        const prompt = voicePrompt.trim();
        if (!prompt) {
          setOperationError("声音设计模式必须填写声音描述词。");
          setCreating(false);
          return;
        }
        opts.voicePrompt = prompt;
        const preview = previewText.trim();
        if (preview) opts.previewText = preview;
      }
      await actions.voiceCardCreate(selectedCardId, createMode, opts);
      const result = await actions.cardGet(selectedCardId);
      setCardDetail({
        cardId: result.card_id,
        name: String((result.card as Record<string, unknown>)?.data?.name ?? ""),
        source: result.source,
        state: result.state,
        readOnly: result.read_only,
        voiceProfile: extractVoiceProfile(result),
      });
    } catch (error: unknown) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  };

  const handleUnbind = async () => {
    if (!actions || !selectedCardId) return;
    setOperationError(null);
    setUnbinding(true);
    try {
      await actions.voiceCardUnbind(selectedCardId);
      const result = await actions.cardGet(selectedCardId);
      setCardDetail({
        cardId: result.card_id,
        name: String((result.card as Record<string, unknown>)?.data?.name ?? ""),
        source: result.source,
        state: result.state,
        readOnly: result.read_only,
        voiceProfile: extractVoiceProfile(result),
      });
    } catch (error: unknown) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setUnbinding(false);
      setConfirmAction(null);
    }
  };

  const handlePreview = async () => {
    if (!actions || !selectedCardId) return;
    setOperationError(null);
    setPreviewing(true);
    try {
      const text = previewText.trim() || undefined;
      await actions.voiceCardPreview(selectedCardId, text);
    } catch (error: unknown) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setPreviewing(false);
    }
  };

  const isBusy = binding || creating || unbinding || previewing || detailLoading;
  // 详情面板以 cardGet 返回的 voice_profile.state 为准（实时），列表摘要作兜底。
  const effectiveVoiceState =
    cardDetail?.voiceProfile.state ?? selectedSummary?.voiceState ?? "voice_unconfigured";

  return (
    <section className="character-voice-section" data-testid="character-voice-section">
      <div className="character-voice-head">
        <h3 className="settings-subhead">为角色创建音色</h3>
        <span className="field-note">固定模型只读</span>
      </div>

      <p className="settings-hint">
        为自定义角色绑定参考音频并创建专属音色。音色 ID 会写入角色卡扩展字段，对话时优先使用该音色。
      </p>

      <label className="field">
        <span className="field-label">选择角色</span>
        <select
          className="character-voice-select"
          value={selectedCardId ?? ""}
          onChange={(event) => setSelectedCardId(event.target.value || null)}
          data-testid="character-voice-select"
          aria-label="选择角色"
        >
          <option value="">— 请选择 —</option>
          {characterVoice.cards.map((card) => (
            <option key={card.cardId} value={card.cardId}>
              {card.name}（{sourceLabel(card.source)}）
            </option>
          ))}
        </select>
      </label>

      {!characterVoice.voiceConfigured ? (
        <div className="settings-status-card" role="alert" data-testid="account-config-block">
          <div className="character-voice-state-hero warn">
            <WarningIcon width={24} height={24} />
          </div>
          <div>
            <div className="h3" style={{ color: "var(--warning)" }}>
              语音服务账号未配置
            </div>
            <p className="settings-hint" style={{ marginTop: 4 }}>
              尚未填写 DashScope API Key 与服务地址，无法为角色创建音色。请先完成上方账号配置。
            </p>
          </div>
          {onScrollToAccountConfig ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onScrollToAccountConfig}
              data-testid="go-to-account-config"
            >
              前往账号配置
            </button>
          ) : null}
        </div>
      ) : null}

      {selectedCardId && selectedSummary?.readOnly ? (
        <div className="settings-status-card" role="status" data-testid="builtin-readonly-block">
          <div className="character-voice-state-hero">
            <RecordVoiceIcon width={24} height={24} />
          </div>
          <div>
            <div className="h3">内置角色只读</div>
            <p className="settings-hint" style={{ marginTop: 4 }}>
              「{selectedSummary.name}」是内置角色，不提供创建音色入口。如需自定义，请先到角色库复制该卡。
            </p>
          </div>
        </div>
      ) : null}

      {selectedCardId && !selectedSummary?.readOnly && characterVoice.voiceConfigured && !actions ? (
        <div className="settings-status-card" role="alert" data-testid="environment-unavailable-block">
          <div className="character-voice-state-hero warn">
            <WarningIcon width={24} height={24} />
          </div>
          <div>
            <div className="h3" style={{ color: "var(--warning)" }}>
              角色音色服务未接入
            </div>
            <p className="settings-hint" style={{ marginTop: 4 }}>
              当前环境缺少操作接口，无法读取角色卡详情或提交音色创建。请在桌面端（Tauri + Sidecar）打开本页后重试。
            </p>
          </div>
        </div>
      ) : null}

      {selectedCardId && !selectedSummary?.readOnly && characterVoice.voiceConfigured && actions ? (
        <div className="character-voice-flow">
          <div className="character-voice-status-bar">
            <span className="character-voice-status-label">当前音色状态</span>
            <span className={`voice-state-pill voice-state-${effectiveVoiceState}`}>
              {stateLabel(effectiveVoiceState)}
            </span>
          </div>

          {detailLoading && !cardDetail ? (
            <div className="settings-hint" role="status" data-testid="detail-loading">
              正在载入音色详情…
            </div>
          ) : null}

          {detailError ? (
            <p className="field-error" role="alert" data-testid="detail-error">
              {detailError}
            </p>
          ) : null}

          {cardDetail ? (
            <>
              <div className="character-voice-reference" data-testid="reference-audio-section">
                <div className="character-voice-section-title">
                  <RecordVoiceIcon width={16} height={16} />
                  <span>参考音频</span>
                </div>
                {cardDetail.voiceProfile.referenceAudioAsset ||
                cardDetail.voiceProfile.referenceAudioAssetId ? (
                  <div className="character-voice-ref-card">
                    <div className="character-voice-ref-info">
                      <VoiceWaveIcon width={20} height={20} />
                      {cardDetail.voiceProfile.referenceAudioAsset ? (
                        <>
                          <span className="character-voice-ref-mime">
                            {cardDetail.voiceProfile.referenceAudioAsset.mime_type}
                          </span>
                          <span className="character-voice-ref-meta">
                            {formatDuration(cardDetail.voiceProfile.referenceAudioAsset.duration_seconds)} ·{" "}
                            {formatBytes(cardDetail.voiceProfile.referenceAudioAsset.size_bytes)}
                          </span>
                        </>
                      ) : (
                        <code className="character-voice-ref-mime">
                          {cardDetail.voiceProfile.referenceAudioAssetId}
                        </code>
                      )}
                    </div>
                    <button
                      type="button"
                      className="btn btn-outline"
                      disabled={isBusy || !onPickFile}
                      onClick={handlePickReference}
                      data-testid="replace-reference-btn"
                    >
                      {binding ? "绑定中…" : "重新选择"}
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="character-voice-dropzone"
                    disabled={isBusy || !onPickFile}
                    onClick={handlePickReference}
                    data-testid="pick-reference-btn"
                  >
                    <PlusIcon width={28} height={28} />
                    <div>
                      <div className="character-voice-dropzone-title">点击选择参考音频</div>
                      <div className="character-voice-dropzone-hint">
                        支持 WAV / MP3 / M4A · 时长 ≤ 60 秒 · 大小 ≤ 10 MB
                      </div>
                    </div>
                  </button>
                )}
                {!onPickFile ? (
                  <p className="field-error" role="alert">
                    文件选择器尚未接入，无法选择参考音频。
                  </p>
                ) : null}
              </div>

              <div className="character-voice-create">
                <div className="character-voice-section-title">
                  <VoiceWaveIcon width={16} height={16} />
                  <span>创建方式</span>
                </div>
                <div className="character-voice-mode-segmented" role="group" aria-label="创建方式">
                  <button
                    type="button"
                    className={createMode === "clone" ? "is-active" : ""}
                    aria-pressed={createMode === "clone"}
                    onClick={() => setCreateMode("clone")}
                    data-testid="create-mode-clone"
                  >
                    声音复刻
                  </button>
                  <button
                    type="button"
                    className={createMode === "design" ? "is-active" : ""}
                    aria-pressed={createMode === "design"}
                    onClick={() => setCreateMode("design")}
                    data-testid="create-mode-design"
                  >
                    声音设计
                  </button>
                </div>

                {createMode === "design" ? (
                  <label className="field">
                    <span className="field-label">声音描述词（必填）</span>
                    <textarea
                      value={voicePrompt}
                      onChange={(event) => setVoicePrompt(event.target.value)}
                      placeholder="例如：温柔沉稳的女声，语速适中，带有轻微的机械感"
                      rows={3}
                      data-testid="voice-prompt-input"
                    />
                  </label>
                ) : null}

                {createMode === "design" ? (
                  <label className="field">
                    <span className="field-label">
                      试听文本
                      <span className="field-note">可选；留空时服务端使用默认文本</span>
                    </span>
                    <input
                      value={previewText}
                      onChange={(event) => setPreviewText(event.target.value)}
                      placeholder="你好，我是你的专属角色。"
                      data-testid="preview-text-input"
                    />
                  </label>
                ) : null}

                <label className="field">
                  <span className="field-label">
                    音色前缀
                    <span className="field-note">可选；≤10 位小写字母/数字，缺省由角色名生成</span>
                  </span>
                  <input
                    value={prefix}
                    onChange={(event) => setPrefix(event.target.value)}
                    placeholder={defaultPrefix(cardDetail.name)}
                    data-testid="prefix-input"
                  />
                  {!isValidPrefix(prefix) ? (
                    <span className="field-error" role="alert">
                      前缀只能是 1–10 位小写字母或数字
                    </span>
                  ) : null}
                </label>

                <div className="settings-fixed-models">
                  <div>
                    <span className="field-label">ASR 模型</span>
                    <code>{FIXED_ASR_MODEL}</code>
                  </div>
                  <div>
                    <span className="field-label">TTS 模型</span>
                    <code>{FIXED_TTS_MODEL}</code>
                  </div>
                </div>

                <div className="settings-row">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={
                      isBusy ||
                      !actions ||
                      !isValidPrefix(prefix) ||
                      (createMode === "design" && !voicePrompt.trim())
                    }
                    onClick={handleCreate}
                    data-testid="create-voice-btn"
                  >
                    {creating ? "正在创建…" : "创建音色"}
                  </button>
                </div>
              </div>

              {effectiveVoiceState === "voice_creating" ? (
                <div className="settings-status-card" role="status" data-testid="voice-state-creating">
                  <div className="character-voice-state-hero accent">
                    <VoiceWaveIcon width={24} height={24} />
                  </div>
                  <div>
                    <div className="h3" style={{ color: "var(--accent)" }}>
                      正在创建音色…
                    </div>
                    <p className="settings-hint" style={{ marginTop: 4 }}>
                      已提交到 TTS 服务，通常需要 20–40 秒。创建完成前请勿重复提交。
                    </p>
                  </div>
                </div>
              ) : null}

              {effectiveVoiceState === "voice_ready" && cardDetail.voiceProfile.voiceId ? (
                <div className="settings-status-card" role="status" data-testid="voice-state-ready">
                  <div className="character-voice-state-hero ok">
                    <CheckIcon width={24} height={24} />
                  </div>
                  <div className="character-voice-ready-body">
                    <div>
                      <div className="h3" style={{ color: "var(--success)" }}>
                        音色已绑定
                      </div>
                      <code className="character-voice-id">{cardDetail.voiceProfile.voiceId}</code>
                    </div>
                    <div className="settings-row">
                      <button
                        type="button"
                        className="btn btn-outline"
                        disabled={isBusy}
                        onClick={handlePreview}
                        data-testid="preview-voice-btn"
                      >
                        {previewing ? "试听中…" : "试听"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-outline"
                        disabled={isBusy}
                        onClick={() => setConfirmAction("recreate")}
                        data-testid="recreate-voice-btn"
                      >
                        重新创建
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger-outline"
                        disabled={isBusy}
                        onClick={() => setConfirmAction("unbind")}
                        data-testid="unbind-voice-btn"
                      >
                        解除绑定
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}

              {effectiveVoiceState === "voice_failed" ? (
                <div className="settings-status-card" role="alert" data-testid="voice-state-failed">
                  <div className="character-voice-state-hero danger">
                    <ErrorIcon width={24} height={24} />
                  </div>
                  <div>
                    <div className="h3" style={{ color: "var(--danger)" }}>
                      音色创建失败
                    </div>
                    {cardDetail.voiceProfile.lastError ? (
                      <p className="field-error" style={{ marginTop: 4 }} data-testid="voice-last-error">
                        {cardDetail.voiceProfile.lastError}
                      </p>
                    ) : null}
                    <div className="settings-row" style={{ marginTop: 8 }}>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={isBusy}
                        onClick={handleCreate}
                        data-testid="retry-create-btn"
                      >
                        重试
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}

              {effectiveVoiceState === "voice_unconfigured" &&
              !cardDetail.voiceProfile.referenceAudioAsset &&
              !cardDetail.voiceProfile.referenceAudioAssetId ? (
                <div className="settings-status-card" role="status" data-testid="voice-state-unconfigured">
                  <div className="character-voice-state-hero">
                    <RecordVoiceIcon width={24} height={24} />
                  </div>
                  <div>
                    <div className="h3">尚未配置音色</div>
                    <p className="settings-hint" style={{ marginTop: 4 }}>
                      选择一段参考音频并点击「创建音色」。clone 模式依赖参考音频；design 模式需填写声音描述词。
                    </p>
                  </div>
                </div>
              ) : null}

              {operationError ? (
                <p className="field-error" role="alert" data-testid="operation-error">
                  {operationError}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      {confirmAction ? (
        <div
          className="character-voice-confirm-mask"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="voice-confirm-title"
          data-testid="voice-confirm-modal"
        >
          <div className="character-voice-confirm">
            <div className="character-voice-confirm-head">
              <span className={`character-voice-state-hero ${confirmAction === "unbind" ? "danger" : "warn"}`}>
                <WarningIcon width={20} height={20} />
              </span>
              <h3 id="voice-confirm-title">
                {confirmAction === "unbind" ? "解除音色绑定？" : "重新创建音色？"}
              </h3>
            </div>
            <p className="settings-hint">
              {confirmAction === "unbind"
                ? `解除后角色「${selectedSummary?.name ?? ""}」将回到未配置状态，音色 ID 会被移除且不可恢复。`
                : "重新创建将丢弃当前音色并回到创建流程，可再次选择参考音频或修改描述词。"}
            </p>
            <div className="settings-row" style={{ justifyContent: "flex-end" }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setConfirmAction(null)}
                data-testid="confirm-cancel"
              >
                取消
              </button>
              <button
                type="button"
                className={confirmAction === "unbind" ? "btn btn-danger" : "btn btn-primary"}
                onClick={confirmAction === "unbind" ? handleUnbind : () => {
                  setConfirmAction(null);
                  setCreateMode("clone");
                }}
                data-testid="confirm-ok"
              >
                {confirmAction === "unbind" ? (unbinding ? "解除中…" : "解除绑定") : "确认"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
