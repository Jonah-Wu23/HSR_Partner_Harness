import type { Message, MessageSource } from "@shared/contracts/protocol";
import type { ConversationItemState } from "@shared/ui/conversation/ConversationList";
import { ReasoningRibbon } from "../../components/cards/ReasoningRibbon";

export interface MessageBubbleProps {
  message: Message;
  pairNames?: {
    character?: string;
    assistant?: string;
  };
  /** 当前正在朗读的消息 ID。 */
  playingMessageId?: string | null;
  /** 停止当前朗读。 */
  onStopPlayback?: () => void;
  /** 本条消息朗读失败的错误原文（store playback.error）。 */
  playbackError?: string | null;
  itemState?: ConversationItemState;
}

const SOURCE_LABELS: Record<Exclude<MessageSource, "character" | "assistant">, string> = {
  user: "你",
  system: "系统",
  tool: "工具",
};

function sourceBadge(source: MessageSource, pairNames?: { character?: string; assistant?: string }): string {
  if (source === "character") return pairNames?.character || "角色";
  if (source === "assistant") return pairNames?.assistant || "助手";
  return SOURCE_LABELS[source];
}

/**
 * 手机端单条消息气泡：
 * 来源标记用角色与助手各自的名字；失败与取消状态连同服务端原因一起展示；
 * 思考段默认折叠，点击展开；流式更新展示光标；
 * 角色自然语言回复支持朗读，其余来源保持静音。
 */
export function MessageBubble({
  message,
  pairNames,
  playingMessageId,
  onStopPlayback,
  playbackError,
  itemState,
}: MessageBubbleProps) {
  const badge = sourceBadge(message.source, pairNames);
  // 朗读入口以服务端 tts_ready 为准：账号专属音色未生成或凭据缺失时服务端无法合成，
  // 不展示入口；没有 tts_ready 字段的消息同样不可朗读。
  const isTtsReadable =
    message.source === "character" && message.tts_eligible && message.tts_ready === true;
  const isPlaying = isTtsReadable && message.message_id === playingMessageId;
  const reasoning =
    typeof message.payload.reasoning === "string" ? message.payload.reasoning : null;
  // 思考是否仍在流式只看 reasoning_streaming：正文开始或 message.finalized 时它变为 false。
  const reasoningStreaming = message.payload.reasoning_streaming === true;
  const reasoningSeconds =
    typeof message.payload.reasoning_seconds === "number"
      ? message.payload.reasoning_seconds
      : undefined;

  const displayText =
    message.text ||
    (message.streaming && !reasoning ? "..." : "");
  // 失败与取消的原因由服务端写在 payload.error / payload.cancelled_reason。
  const isFailed = message.status === "failed";
  const isCancelled = message.status === "cancelled";
  const statusDetail = isFailed
    ? message.payload.error
    : isCancelled
      ? message.payload.cancelled_reason
      : null;

  return (
    <div
      className={`mobile-msg-row mobile-msg-row-${message.source}`}
      data-testid="message-bubble"
      data-message-source={message.source}
      data-message-id={message.message_id}
      data-message-status={message.status}
    >
      <div className={`mobile-msg-bubble mobile-msg-bubble-${message.source}`}>
        {/* 思考段折叠组件 */}
        {reasoning !== null || reasoningStreaming ? (
          <ReasoningRibbon
            text={reasoning ?? ""}
            streaming={reasoningStreaming}
            elapsedSeconds={reasoningSeconds}
            expanded={itemState?.isExpanded(`reasoning:${message.message_id}`, false)}
            onExpandedChange={(expanded) => itemState?.setExpanded(`reasoning:${message.message_id}`, expanded)}
          />
        ) : null}

        {/* 来源标记 */}
        <span className="mobile-msg-badge" data-testid="msg-source-badge">
          {badge}
        </span>

        {/* 正文 */}
        {displayText ? (
          <div className="mobile-msg-text">
            {displayText}
            {message.streaming && message.text ? (
              <span className="mobile-streaming-caret" aria-hidden="true" />
            ) : null}
          </div>
        ) : null}

        {isFailed || isCancelled ? (
          <p
            className={`mobile-msg-status mobile-msg-status-${message.status}`}
            role={isFailed ? "alert" : undefined}
            data-testid="msg-status"
          >
            {isFailed ? "失败" : "已取消"}
            {typeof statusDetail === "string" && statusDetail ? `：${statusDetail}` : null}
          </p>
        ) : null}

        {/* 角色自然语言回复的朗读入口与朗读中标记；播放失败时展示错误原文。 */}
        {isTtsReadable ? (
          <button
            type="button"
            className={`mobile-msg-tts-badge${isPlaying ? " mobile-msg-tts-badge-playing" : ""}`}
            data-testid="msg-tts-badge"
            disabled={!isPlaying}
            onClick={isPlaying ? onStopPlayback : undefined}
            aria-label={isPlaying ? "停止朗读" : "可朗读"}
          >
            <span
              className={`mobile-msg-tts-dot${isPlaying ? " mobile-msg-tts-dot-playing" : ""}`}
              aria-hidden="true"
            />
            {isPlaying ? "朗读中" : "可朗读"}
          </button>
        ) : null}
        {isTtsReadable && playbackError ? (
          <p className="mobile-msg-tts-error" role="alert" data-testid="msg-tts-error">
            朗读失败：{playbackError}
          </p>
        ) : null}
      </div>
    </div>
  );
}
