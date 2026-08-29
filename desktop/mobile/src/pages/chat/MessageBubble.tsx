import type { Message, MessageSource, ToolRun } from "@shared/contracts/protocol";
import { ReasoningRibbon } from "../../components/cards/ReasoningRibbon";
import { ToolCard } from "../../components/cards/ToolCard";

export interface MessageBubbleProps {
  message: Message;
  pairNames?: {
    character?: string;
    assistant?: string;
  };
  /** V0.3.5：当前正在播放 TTS 的消息 ID。 */
  playingMessageId?: string | null;
  /** V0.3.5：停止当前朗读。 */
  onStopPlayback?: () => void;
}

function sourceBadge(source: MessageSource, pairNames?: { character?: string; assistant?: string }): string | null {
  if (source === "user") return "你";
  if (source === "character") return pairNames?.character || "角色";
  if (source === "assistant") return pairNames?.assistant || "助手";
  if (source === "system") return "系统";
  if (source === "tool") return "工具";
  return null;
}

/**
 * V0.3.5 手机端单条消息气泡：
 * 消息来源标记（角色/助手/用户/工具/思考/系统事件）清晰可区分；
 * 思考段默认折叠，点击展开；流式更新展示光标；
 * 角色自然语言回复支持朗读，其余来源保持静音。
 */
export function MessageBubble({
  message,
  pairNames,
  playingMessageId,
  onStopPlayback,
}: MessageBubbleProps) {
  const badge = sourceBadge(message.source, pairNames);
  const isTtsEligible = message.source === "character" && message.tts_eligible === true;
  const isPlaying = isTtsEligible && message.message_id === playingMessageId;
  const reasoning =
    typeof message.payload?.reasoning === "string"
      ? message.payload.reasoning
      : message.kind === "assistant.reasoning"
        ? message.text
        : null;
  const reasoningStreaming =
    message.payload?.reasoning_streaming === true ||
    (message.streaming === true && message.kind === "assistant.reasoning");
  const reasoningSeconds =
    typeof message.payload?.reasoning_seconds === "number"
      ? message.payload.reasoning_seconds
      : undefined;

  // 工具记录特殊渲染为 ToolCard
  if (message.source === "tool" || message.kind === "tool.record") {
    const run: ToolRun = {
      tool_call_id: (message.payload?.tool_call_id as string) || message.message_id,
      conversation_id: message.conversation_id,
      task_id: (message.payload?.task_id as string) || message.task_id || "",
      engine_turn_id: message.engine_turn_id || "",
      sequence: Number(message.payload?.sequence || 0),
      status: (message.payload?.status as ToolRun["status"]) || "succeeded",
      title: (message.payload?.title as string) || message.text || "工具执行",
      summary: (message.payload?.summary as string) || "",
      details: (message.payload?.details as string) || "",
    };
    return (
      <div
        className="mobile-msg-row mobile-msg-row-tool"
        data-testid="message-bubble"
        data-message-source="tool"
        data-message-id={message.message_id}
      >
        <div className="mobile-msg-tool-wrap">
          <ToolCard run={run} />
        </div>
      </div>
    );
  }

  const displayText =
    message.text ||
    (message.streaming && !reasoning ? "..." : "");

  return (
    <div
      className={`mobile-msg-row mobile-msg-row-${message.source}`}
      data-testid="message-bubble"
      data-message-source={message.source}
      data-message-id={message.message_id}
    >
      <div className={`mobile-msg-bubble mobile-msg-bubble-${message.source}`}>
        {/* 思考段折叠组件 */}
        {reasoning !== null || reasoningStreaming ? (
          <ReasoningRibbon
            text={reasoning ?? ""}
            streaming={reasoningStreaming}
            elapsedSeconds={reasoningSeconds}
          />
        ) : null}

        {/* 来源标记 */}
        {badge ? (
          <span className="mobile-msg-badge" data-testid="msg-source-badge">
            {badge}
          </span>
        ) : null}

        {/* 正文 */}
        {displayText ? (
          <div className="mobile-msg-text">
            {displayText}
            {message.streaming && message.text ? (
              <span className="mobile-streaming-caret" aria-hidden="true" />
            ) : null}
          </div>
        ) : null}

        {/* V0.3.5：角色自然语言回复的朗读入口 / 朗读中标记 */}
        {isTtsEligible ? (
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
      </div>
    </div>
  );
}
