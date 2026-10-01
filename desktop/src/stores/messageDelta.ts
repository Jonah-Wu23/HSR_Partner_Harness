import type { Message, MessageDeltaPayload } from "../contracts/protocol";

/** 首片 delta 创建消息时需要的归属与时间；后续分片沿用已有消息的字段。 */
export interface MessageDeltaOrigin {
  pairId: string;
  createdAt: string;
}

/** 角色 reasoning 通道与助手 assistant.reasoning 分片写入 payload.reasoning，其余写入正文。 */
export function isReasoningDelta(payload: Pick<MessageDeltaPayload, "source" | "channel" | "kind">): boolean {
  return (
    (payload.source === "character" && payload.channel === "reasoning") ||
    (payload.source === "assistant" && payload.kind === "assistant.reasoning")
  );
}

/**
 * 把一条 message.delta 投影到消息上，返回新消息。
 *
 * reasoning_streaming 以载荷显式值为准；载荷只给出 started/completed 时，
 * completed=true 结束思考流，started 或 completed=false 表示仍在流式。
 * 首片（current 为 undefined）按载荷与 origin 新建一条 streaming 消息。
 */
export function applyMessageDelta(
  current: Message | undefined,
  payload: MessageDeltaPayload,
  origin: MessageDeltaOrigin,
): Message {
  const delta = payload.delta ?? "";
  const messagePayload: Record<string, unknown> = { ...(current?.payload ?? {}) };
  let text = current?.text ?? "";
  if (payload.reasoning_streaming !== undefined) {
    messagePayload.reasoning_streaming = payload.reasoning_streaming;
  }
  if (isReasoningDelta(payload)) {
    const reasoning = typeof messagePayload.reasoning === "string" ? messagePayload.reasoning : "";
    messagePayload.reasoning = reasoning + delta;
    if (
      payload.reasoning_streaming === undefined &&
      (payload.started || payload.completed !== undefined)
    ) {
      messagePayload.reasoning_streaming = !payload.completed;
    }
  } else {
    text += delta;
  }
  if (current) {
    return { ...current, text, payload: messagePayload, streaming: true };
  }
  return {
    message_id: payload.message_id,
    conversation_id: payload.conversation_id,
    pair_id: payload.pair_id ?? origin.pairId,
    engine_turn_id: null,
    source: payload.source,
    kind: payload.kind as Message["kind"],
    text,
    payload: messagePayload,
    tts_eligible: payload.source === "character" || payload.source === "assistant",
    created_at: origin.createdAt,
    streaming: true,
    task_id: payload.task_id ?? null,
    timeline_order: payload.timeline_order,
  };
}
