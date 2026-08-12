export type VoicePlaybackStatus = "synthesizing" | "playing" | "failed";

export interface VoiceMiniPlayerView {
  status: VoicePlaybackStatus;
  /** 当前朗读者色点身份。 */
  speaker: "character" | "assistant";
  speakerName: string;
  /** 当前朗读内容摘要。 */
  summary: string;
  /** 队列里还有几条（不含当前条）。 */
  queuedCount: number;
  /** 失败时的人话原因。 */
  errorText?: string;
}

interface VoiceMiniPlayerProps {
  view: VoiceMiniPlayerView;
  onStop: () => void;
  /** 跳下一条。 */
  onSkip: () => void;
  /** 失败后重试。 */
  onRetry?: () => void;
  onClose: () => void;
}

/**
 * 语音迷你播放条：浮现在输入区左上，合成中 / 播放中 / 失败三态。
 * 文字阅读全程不受遮挡，可随时停止或跳下一条。
 */
export function VoiceMiniPlayer({ view, onStop, onSkip, onRetry, onClose }: VoiceMiniPlayerProps) {
  return (
    <div className={`voice-mini-player voice-mini-${view.status}`} role="status" aria-live="polite">
      <span
        className={`pair-dot ${view.speaker === "character" ? "pair-dot-character" : "pair-dot-assistant"}`}
        aria-hidden
      />
      {view.status === "synthesizing" ? (
        <span className="voice-mini-text">正在合成语音…</span>
      ) : view.status === "playing" ? (
        <>
          <span className="voice-mini-wave" aria-hidden>
            <span /><span /><span />
          </span>
          <span className="voice-mini-text">
            {view.speakerName}：{view.summary}
            {view.queuedCount > 0 ? `（队列还有 ${view.queuedCount} 条）` : ""}
          </span>
        </>
      ) : (
        <span className="voice-mini-text voice-mini-error">{view.errorText ?? "语音服务没响应"}</span>
      )}

      <span className="voice-mini-actions">
        {view.status === "failed" && onRetry ? (
          <button type="button" onClick={onRetry}>重试</button>
        ) : null}
        {view.status === "playing" && view.queuedCount > 0 ? (
          <button type="button" onClick={onSkip}>跳下一条</button>
        ) : null}
        {view.status !== "failed" ? (
          <button type="button" onClick={onStop}>停止</button>
        ) : null}
        <button type="button" aria-label="关闭播放条" onClick={onClose}>×</button>
      </span>
    </div>
  );
}
