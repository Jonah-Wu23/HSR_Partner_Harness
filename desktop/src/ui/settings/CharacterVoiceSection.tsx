import { useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type {
  CardGetResult,
  CharacterVoiceState,
  CharacterCardSource,
} from "../../contracts/protocol";
import type { FileFilter } from "../../services/backend";
import type { CharacterCardVoicePageViewModel } from "../../contracts/view-models";
import {
  CheckIcon,
  ErrorIcon,
  PlusIcon,
  RecordVoiceIcon,
  VoiceWaveIcon,
  WarningIcon,
} from "../../assets/icons/icons";

export interface CharacterVoiceSectionProps {
  characterVoice: CharacterCardVoicePageViewModel;
  voiceCardFocus?: string | null;
  actions: HarnessActions;
  /** 系统文件对话框，选择参考音频。 */
  onPickFile: (options?: {
    title?: string;
    filters?: FileFilter[];
  }) => Promise<string | null>;
  /** 滚动到语音页 DashScope 账号配置区（本页内跳转）。 */
  onScrollToAccountConfig?: () => void;
}

/** card.get 中 data.extensions.hsr.voice_profile 的线缆形状（codec 序列化的字段全部为字符串）。 */
interface VoiceProfilePayload {
  state: string;
  voice_id: string;
  reference_audio_asset: string;
  last_error: string;
}

interface VoiceProfileDetail {
  voiceId: string;
  state: CharacterVoiceState;
  referenceAudioAssetId: string;
  lastError: string;
}

interface CardDetail {
  name: string;
  voiceProfile: VoiceProfileDetail;
}

type CreateMode = "clone" | "design";

type ConfirmAction = "recreate" | "unbind" | null;

const FIXED_ASR_MODEL = "qwen-audio-3.0-asr-flash-streaming";
const FIXED_TTS_MODEL = "qwen-audio-3.0-tts-flash";

const VOICE_STATE_LABEL: Record<CharacterVoiceState, string> = {
  voice_unconfigured: "未配置",
  voice_creating: "创建中",
  voice_ready: "已绑定",
  voice_failed: "失败",
};

const SOURCE_LABEL: Record<CharacterCardSource, string> = {
  builtin: "内置",
  user_created: "自定义",
  tavern_import: "导入",
};

function parseVoiceState(value: string): CharacterVoiceState {
  if (Object.hasOwn(VOICE_STATE_LABEL, value)) return value as CharacterVoiceState;
  throw new Error(`角色卡音色状态未知：${value}`);
}

/** 卡上没有 voice_profile 时按未配置处理，与卡库摘要的 voice_state 一致；状态值不在枚举内时抛错。 */
function cardDetailOf(result: CardGetResult): CardDetail {
  const data = result.card.data as {
    name: string;
    extensions?: { hsr?: { voice_profile?: VoiceProfilePayload } };
  };
  const profile = data.extensions?.hsr?.voice_profile;
  return {
    name: data.name,
    voiceProfile: profile
      ? {
          voiceId: profile.voice_id,
          state: parseVoiceState(profile.state),
          referenceAudioAssetId: profile.reference_audio_asset,
          lastError: profile.last_error,
        }
      : { voiceId: "", state: "voice_unconfigured", referenceAudioAssetId: "", lastError: "" },
  };
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

  const [selectedCardId, setSelectedCardId] = useState<string | null>(voiceCardFocus ?? null);
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

  // 选中卡变化时读取卡详情（参考音频、音色 id、失败错误以 cardGet 为准）。
  useEffect(() => {
    setOperationError(null);
    setCardDetail(null);
    setDetailError(null);
    if (!selectedCardId) {
      setDetailLoading(false);
      return;
    }
    setDetailLoading(true);
    let cancelled = false;
    actions
      .cardGet(selectedCardId)
      .then((result) => {
        if (!cancelled) setCardDetail(cardDetailOf(result));
      })
      .catch((error: unknown) => {
        if (!cancelled) setDetailError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedCardId, actions]);

  // 卡库摘要的 voiceState 离开 creating 后重新读取详情，拿到 voice_id 或 last_error。
  useEffect(() => {
    if (!selectedCardId || !cardDetail) return;
    if (
      cardDetail.voiceProfile.state === "voice_creating" &&
      selectedSummary?.voiceState !== "voice_creating"
    ) {
      setDetailLoading(true);
      actions
        .cardGet(selectedCardId)
        .then((result) => setCardDetail(cardDetailOf(result)))
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
    if (!selectedCardId) return;
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
      setCardDetail(cardDetailOf(await actions.cardGet(selectedCardId)));
    } catch (error: unknown) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setBinding(false);
    }
  };

  const handleCreate = async () => {
    if (!selectedCardId) return;
    setOperationError(null);
    setCreating(true);
    try {
      const opts: { prefix?: string; voicePrompt?: string; previewText?: string } = {};
      const trimmedPrefix = prefix.trim();
      if (trimmedPrefix) opts.prefix = trimmedPrefix;
      if (createMode === "design") {
        // 失败后的重试与确认重新创建不经过创建按钮的禁用判断，这里再校验一次描述词。
        const prompt = voicePrompt.trim();
        if (!prompt) {
          setOperationError("声音设计模式必须填写声音描述词。");
          return;
        }
        opts.voicePrompt = prompt;
        const preview = previewText.trim();
        if (preview) opts.previewText = preview;
      }
      await actions.voiceCardCreate(selectedCardId, createMode, opts);
      setCardDetail(cardDetailOf(await actions.cardGet(selectedCardId)));
    } catch (error: unknown) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  };

  const handleUnbind = async () => {
    if (!selectedCardId) return;
    setOperationError(null);
    setUnbinding(true);
    try {
      await actions.voiceCardUnbind(selectedCardId);
      setCardDetail(cardDetailOf(await actions.cardGet(selectedCardId)));
    } catch (error: unknown) {
      setOperationError(error instanceof Error ? error.message : String(error));
    } finally {
      setUnbinding(false);
      setConfirmAction(null);
    }
  };

  const handlePreview = async () => {
    if (!selectedCardId) return;
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
  // 详情读取完成前状态条显示卡库摘要的 voiceState。
  const statusBarState = cardDetail?.voiceProfile.state ?? selectedSummary?.voiceState;

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
              {card.name}（{SOURCE_LABEL[card.source]}）
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

      {selectedCardId && !selectedSummary?.readOnly && characterVoice.voiceConfigured ? (
        <div className="character-voice-flow">
          {statusBarState ? (
            <div className="character-voice-status-bar">
              <span className="character-voice-status-label">当前音色状态</span>
              <span className={`voice-state-pill voice-state-${statusBarState}`}>
                {VOICE_STATE_LABEL[statusBarState]}
              </span>
            </div>
          ) : null}

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
                {cardDetail.voiceProfile.referenceAudioAssetId ? (
                  <div className="character-voice-ref-card">
                    <div className="character-voice-ref-info">
                      <VoiceWaveIcon width={20} height={20} />
                      <code className="character-voice-ref-mime">
                        {cardDetail.voiceProfile.referenceAudioAssetId}
                      </code>
                    </div>
                    <button
                      type="button"
                      className="btn btn-outline"
                      disabled={isBusy}
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
                    disabled={isBusy}
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

              {cardDetail.voiceProfile.state === "voice_creating" ? (
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

              {cardDetail.voiceProfile.state === "voice_ready" && cardDetail.voiceProfile.voiceId ? (
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

              {cardDetail.voiceProfile.state === "voice_failed" ? (
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

              {cardDetail.voiceProfile.state === "voice_unconfigured" &&
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
                : `将按上方当前的创建方式（${createMode === "clone" ? "声音复刻" : "声音设计"}）重新提交创建，成功后新音色替换当前音色 ID。`}
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
                  void handleCreate();
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
