import { useCallback, useEffect, useRef, useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { ApprovalMode, ReasoningEffort } from "../../contracts/protocol";
import type { ComposerViewModel, VoiceViewModel } from "../../contracts/view-models";
import {
  CollapseIcon,
  RecordVoiceIcon,
  SendIcon,
  StopIcon,
  VoiceWaveIcon,
} from "../../assets/icons/icons";
import { Menu } from "../primitives/Menu";
import { VoiceMiniPlayer } from "./VoiceMiniPlayer";
import type { VoiceMiniPlayerView } from "./VoiceMiniPlayer";

const APPROVAL_LABEL: Record<ApprovalMode, string> = {
  request_approval: "请求批准",
  review: "帮我审核",
  full_auto: "完全允许运行",
};

const EFFORT_LABEL: Record<ReasoningEffort, string> = {
  low: "推理 · 轻度",
  medium: "推理 · 中",
  high: "推理 · 高",
  xhigh: "推理 · 极高",
  max: "推理 · 最高",
};

const COLLAPSE_ROTATED_STYLE = { transform: "rotate(-90deg)" };
const PTT_KEY_CODE = "AltRight";

function voiceStatusText(voice: VoiceViewModel): string {
  if (voice.error) return `语音异常：${voice.error}`;
  if (voice.ptt) return "聆听中（按键说话）";
  if (voice.tts === "playing") return "语音播放中";
  if (voice.vad_enabled) {
    switch (voice.vad) {
      case "listening":
        return "VAD 聆听中";
      case "speech_started":
      case "start":
        return "VAD 识别中";
      case "speech_ended":
      case "end":
        return "VAD 已结束";
      case "false_trigger":
        return "VAD 未识别到语音";
      case "playing":
        return "VAD 暂停";
      default:
        return `VAD ${voice.vad}`;
    }
  }
  if (!voice.supported) return "语音不可用";
  return voice.vad === "unavailable" ? "语音已连接，VAD 不可用" : "语音就绪";
}

function voiceStatusTone(voice: VoiceViewModel): string {
  if (voice.error) return "error";
  switch (voice.vad) {
    case "listening":
      return "listening";
    case "speech_started":
    case "start":
      return "speaking";
    case "speech_ended":
    case "end":
    case "false_trigger":
      return "ended";
    case "playing":
      return "playing";
    case "unavailable":
      return "unavailable";
    default:
      return voice.ptt ? "speaking" : "idle";
  }
}

function vadButtonTitle(voice: VoiceViewModel, target: "character" | "assistant"): string {
  if (target !== "character") return "VAD 仅用于对角色说";
  if (voice.vad === "unavailable") return "VAD 模型不可用";
  if (!voice.supported) return "语音运行时未启用";
  return voice.vad_enabled ? "关闭 VAD" : "开启 VAD";
}

interface ComposerProps {
  composer: ComposerViewModel;
  voice: VoiceViewModel;
  mode: "chat" | "collaboration";
  actions: HarnessActions;
  /** V0.2 M4：语音迷你播放条视图；tts 播放/合成/失败时非空。 */
  voiceMiniPlayer?: VoiceMiniPlayerView | null;
  /** V0.2 M4：QueueStrip「编辑」拉回的草稿（nonce 变化时写入输入区）。 */
  draftSeed?: { text: string; nonce: number } | null;
}

/** 输入区：目标切换、自动增高文本框、审批/推理档位、语音控制条。 */
export function Composer({
  composer,
  voice,
  mode,
  actions,
  voiceMiniPlayer,
  draftSeed,
}: ComposerProps) {
  const [target, setTarget] = useState<"character" | "assistant">(composer.target);
  const [draft, setDraft] = useState("");
  const [pttRequested, setPttRequested] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const lastSeedNonce = useRef<number | null>(null);
  const pttToggleActive = useRef(false);
  const pttRequestVersion = useRef(0);
  // V0.2 M4：QueueStrip「编辑」拉回的草稿——nonce 变化时写入输入区
  useEffect(() => {
    if (draftSeed && draftSeed.nonce !== lastSeedNonce.current) {
      lastSeedNonce.current = draftSeed.nonce;
      setDraft(draftSeed.text);
    }
  }, [draftSeed]);

  const requestPtt = useCallback(
    (active: boolean) => {
      const requestVersion = ++pttRequestVersion.current;
      pttToggleActive.current = active;
      setPttRequested(active);
      const request = active
        ? actions.startPushToTalk(target)
        : actions.stopPushToTalk();
      void Promise.resolve(request).catch(() => {
        if (requestVersion !== pttRequestVersion.current) return;
        // 真实请求失败时只收回本地“正在聆听”意图，不生成假成功。
        pttToggleActive.current = false;
        setPttRequested(false);
      });
    },
    [actions, target],
  );

  const togglePtt = useCallback(() => {
    requestPtt(!pttToggleActive.current);
  }, [requestPtt]);

  useEffect(() => {
    const isRightAlt = (event: KeyboardEvent) =>
      event.code === PTT_KEY_CODE ||
      ((event.key === "Alt" || event.key === "AltGraph") && event.location === 2);
    const canUsePtt =
      composer.enabled &&
      voice.enabled !== false &&
      voice.supported &&
      voice.canPushToTalk;

    const stopPttOnFocusLoss = () => {
      if (pttToggleActive.current) requestPtt(false);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (!isRightAlt(event) || event.repeat || !canUsePtt) return;
      event.preventDefault();
      togglePtt();
    };
    const onWindowBlur = () => stopPttOnFocusLoss();
    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible") stopPttOnFocusLoss();
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("blur", onWindowBlur);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("blur", onWindowBlur);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      stopPttOnFocusLoss();
    };
  }, [composer.enabled, requestPtt, togglePtt, voice.canPushToTalk, voice.enabled, voice.supported]);

  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 160)}px`;
  }, [draft]);

  const canSend = composer.enabled && draft.trim().length > 0;

  const submit = () => {
    const text = draft.trim();
    if (!composer.enabled || !text) return;
    setDraft("");
    void actions.submitMessage(text, target);
  };

  const asrText = voice.asr_partial || composer.asrPartial;
  const vadUnavailable = voice.vad === "unavailable";
  const canUseVad = voice.supported && !vadUnavailable && target === "character";
  const voiceStatus = voiceStatusText(voice);
  const pttActive = pttRequested || voice.ptt;

  return (
    <div className={`composer${composer.enabled ? "" : " is-disabled"}`} data-testid="composer">
      {voiceMiniPlayer ? (
        // V0.2 M4：语音迷你播放条——停止/关闭走 tts_stop，跳下一条走 tts_skip
        <VoiceMiniPlayer
          view={voiceMiniPlayer}
          onStop={() => void actions.stopSpeech()}
          onSkip={() => void actions.skipSpeech()}
          onClose={() => void actions.stopSpeech()}
        />
      ) : null}
      <div className="composer-main">
        <div className="composer-input-wrap">
          <div className="segmented" role="tablist" aria-label="发送对象">
            <button
              type="button"
              role="tab"
              aria-selected={target === "character"}
              className={`segmented-item${target === "character" ? " is-selected" : ""}`}
              onClick={() => setTarget("character")}
            >
              对角色说
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={target === "assistant"}
              className={`segmented-item${target === "assistant" ? " is-selected" : ""}`}
              disabled={mode !== "collaboration"}
              title={mode !== "collaboration" ? "切换到协作模式后可直接交给助手" : undefined}
              onClick={() => setTarget("assistant")}
            >
              交给助手
            </button>
          </div>
          <textarea
            ref={inputRef}
            className="composer-input"
            rows={1}
            placeholder={target === "character" ? "和角色聊聊…" : "描述要交给助手的任务…"}
            value={draft}
            disabled={!composer.enabled}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submit();
              }
            }}
            aria-label="消息输入"
          />
          {asrText ? <div className="composer-asr">{asrText}</div> : null}
        </div>
        <button
          type="button"
          className="btn btn-primary composer-send"
          disabled={!canSend}
          onClick={submit}
          aria-label="发送"
        >
          <SendIcon />
          发送
        </button>
      </div>

      <div className="composer-toolbar">
        <Menu
          ariaLabel="审批模式"
          align="left"
          dropUp
          selectedId={composer.approvalMode}
          trigger={() => (
            <button type="button" className="select-chip" aria-label="审批模式">
              {APPROVAL_LABEL[composer.approvalMode]}
              <CollapseIcon style={COLLAPSE_ROTATED_STYLE} />
            </button>
          )}
          items={(Object.keys(APPROVAL_LABEL) as ApprovalMode[]).map((value) => ({
            id: value,
            label: APPROVAL_LABEL[value],
          }))}
          onSelect={(id) => void actions.setApprovalMode(id as ApprovalMode)}
        />
        <Menu
          ariaLabel="推理档位"
          align="left"
          dropUp
          selectedId={composer.reasoningEffort}
          trigger={() => (
            <button type="button" className="select-chip" aria-label="推理档位">
              {EFFORT_LABEL[(composer.reasoningEffort as ReasoningEffort) ?? "medium"] ??
                `推理 · ${composer.reasoningEffort}`}
              <CollapseIcon style={COLLAPSE_ROTATED_STYLE} />
            </button>
          )}
          items={(Object.keys(EFFORT_LABEL) as ReasoningEffort[]).map((value) => ({
            id: value,
            label: EFFORT_LABEL[value],
          }))}
          onSelect={(id) => void actions.setReasoningEffort(id as ReasoningEffort)}
        />

        <div className="composer-toolbar-spacer" />

        {/* 语音按钮组：语音功能关闭时整体隐藏（设置页 voice.enabled=false） */}
        {voice.enabled !== false ? (
          <>
        <button
          type="button"
          className="icon-btn"
          disabled={!canUseVad}
          title={vadButtonTitle(voice, target)}
          aria-label="VAD"
          aria-pressed={voice.vad_enabled}
          onClick={() => void actions.setVadEnabled(!voice.vad_enabled)}
        >
          <VoiceWaveIcon />
        </button>
        <button
          type="button"
          className="icon-btn"
          disabled={!voice.supported || !voice.canPushToTalk}
          title={pttActive ? "结束聆听（点击或右 Alt）" : "开始聆听（点击或右 Alt）"}
          aria-label="按键说话"
          aria-pressed={pttActive}
          onClick={togglePtt}
        >
          <RecordVoiceIcon />
        </button>
        <button
          type="button"
          className="icon-btn"
          disabled={voice.tts === "idle" || voice.tts === "failed"}
          title="停止播报"
          aria-label="停止播报"
          onClick={() => void actions.stopSpeech()}
        >
          <StopIcon />
        </button>
        <span className={`voice-status voice-status-${voiceStatusTone(voice)}`} aria-live="polite">
          <span className="pair-dot voice-status-dot" />
          {voiceStatus}
        </span>
          </>
        ) : null}
      </div>
    </div>
  );
}
