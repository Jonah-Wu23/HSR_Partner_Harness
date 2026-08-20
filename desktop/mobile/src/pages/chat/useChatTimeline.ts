import { useEffect, useMemo, useState } from "react";
import type { Message, ToolRun } from "@shared/contracts/protocol";
import { mobileWsClient, useMobileStore } from "../../lib/mobileStore";
import type { WireEvent } from "../../lib/wsClient";

export type TimelineItem =
  | {
      kind: "message";
      id: string;
      message: Message;
      order: number;
    }
  | {
      kind: "tool_run";
      id: string;
      toolRun: ToolRun;
      order: number;
    };

/**
 * V0.3.3 手机端聊天时间线 Hook：
 * 1. 订阅 mobileStore 的 messages 与 toolRuns 底座状态；
 * 2. 订阅 mobileWsClient.onEvent，在文件域内对当前会话的 message.delta /
 *    message.created / message.finalized / tool_run.upserted 做实时合并；
 * 3. 将消息与工具调用按 timeline_order / 事件顺序混合统一排布。
 */
export function useChatTimeline(conversationId: string) {
  const storeMessages = useMobileStore((state) => state.messages);
  const storeToolRuns = useMobileStore((state) => state.toolRuns);

  // 本地实时流式叠加状态
  const [localMessages, setLocalMessages] = useState<Message[]>(storeMessages);
  const [localToolRuns, setLocalToolRuns] = useState<ToolRun[]>(storeToolRuns);

  // 同步 store 变更时保留本地正在流式传输的消息增量
  useEffect(() => {
    setLocalMessages((prevLocal) => {
      const streamingOnly = prevLocal.filter(
        (local) =>
          local.streaming &&
          !storeMessages.some((sm) => sm.message_id === local.message_id),
      );
      const merged = storeMessages.map((sm) => {
        const local = prevLocal.find((l) => l.message_id === sm.message_id);
        if (local && local.streaming && (!sm.text || local.text.length > sm.text.length)) {
          return {
            ...sm,
            text: local.text,
            streaming: true,
            payload: { ...sm.payload, ...local.payload },
          };
        }
        return sm;
      });
      return [...merged, ...streamingOnly];
    });
  }, [storeMessages]);

  useEffect(() => {
    setLocalToolRuns((prevLocal) => {
      const runningOnly = prevLocal.filter(
        (local) =>
          local.status === "running" &&
          !storeToolRuns.some((st) => st.tool_call_id === local.tool_call_id),
      );
      return [...storeToolRuns, ...runningOnly];
    });
  }, [storeToolRuns]);

  // 订阅 WS 实时事件流
  useEffect(() => {
    const unsubscribe = mobileWsClient.onEvent((event: WireEvent) => {
      const payload = event.payload as Record<string, unknown>;

      switch (event.event) {
        case "message.created": {
          const msg = (payload.message as Message) || (payload as unknown as Message);
          if (msg && msg.conversation_id === conversationId) {
            setLocalMessages((prev) => {
              const exists = prev.some((m) => m.message_id === msg.message_id);
              if (exists) {
                return prev.map((m) => (m.message_id === msg.message_id ? { ...m, ...msg } : m));
              }
              return [...prev, msg];
            });
          }
          break;
        }

        case "message.delta": {
          const deltaMsgId = payload.message_id as string;
          const deltaConvId = payload.conversation_id as string;
          const deltaText = (payload.delta as string) || "";
          const deltaKind = payload.kind as string;

          if (deltaConvId === conversationId && deltaMsgId) {
            setLocalMessages((prev) => {
              const existingIndex = prev.findIndex((m) => m.message_id === deltaMsgId);
              if (existingIndex >= 0) {
                const existing = prev[existingIndex]!;
                const isReasoning = deltaKind === "assistant.reasoning" || existing.kind === "assistant.reasoning";

                if (isReasoning) {
                  const currentReasoning = (existing.payload?.reasoning as string) || existing.text || "";
                  const updatedPayload = {
                    ...existing.payload,
                    reasoning: currentReasoning + deltaText,
                    reasoning_streaming: true,
                  };
                  const updated: Message = {
                    ...existing,
                    streaming: true,
                    payload: updatedPayload,
                  };
                  const next = [...prev];
                  next[existingIndex] = updated;
                  return next;
                }

                const updated: Message = {
                  ...existing,
                  text: (existing.text || "") + deltaText,
                  streaming: true,
                };
                const next = [...prev];
                next[existingIndex] = updated;
                return next;
              }

              // 新流式消息首次到达
              const isReasoning = deltaKind === "assistant.reasoning";
              const newMsg: Message = {
                message_id: deltaMsgId,
                conversation_id: deltaConvId,
                pair_id: (payload.pair_id as string) || "",
                engine_turn_id: null,
                source: (payload.source as Message["source"]) || "assistant",
                kind: (deltaKind as Message["kind"]) || "assistant.natural_language",
                text: isReasoning ? "" : deltaText,
                payload: isReasoning
                  ? { reasoning: deltaText, reasoning_streaming: true }
                  : {},
                tts_eligible: false,
                created_at: new Date().toISOString(),
                streaming: true,
                timeline_order: typeof payload.timeline_order === "number" ? payload.timeline_order : null,
              };
              return [...prev, newMsg];
            });
          }
          break;
        }

        case "message.finalized": {
          const finalMsgId = payload.message_id as string;
          const finalConvId = payload.conversation_id as string;

          if (finalConvId === conversationId && finalMsgId) {
            setLocalMessages((prev) =>
              prev.map((m) => {
                if (m.message_id === finalMsgId) {
                  const updatedPayload = { ...m.payload };
                  if (updatedPayload.reasoning_streaming) {
                    updatedPayload.reasoning_streaming = false;
                  }
                  return {
                    ...m,
                    text: (payload.text as string) ?? m.text,
                    streaming: false,
                    payload: updatedPayload,
                  };
                }
                return m;
              }),
            );
          }
          break;
        }

        case "tool_run.upserted": {
          const toolRun = (payload.tool_run as ToolRun) || (payload as unknown as ToolRun);
          if (toolRun && toolRun.conversation_id === conversationId) {
            setLocalToolRuns((prev) => {
              const idx = prev.findIndex((t) => t.tool_call_id === toolRun.tool_call_id);
              if (idx >= 0) {
                const next = [...prev];
                next[idx] = { ...next[idx]!, ...toolRun };
                return next;
              }
              return [...prev, toolRun];
            });
          }
          break;
        }

        default:
          break;
      }
    });

    return () => {
      unsubscribe();
    };
  }, [conversationId]);

  // 统一混合排序 timeline
  const items = useMemo<TimelineItem[]>(() => {
    const list: TimelineItem[] = [];

    localMessages.forEach((msg, idx) => {
      const order =
        typeof msg.timeline_order === "number"
          ? msg.timeline_order
          : idx * 10;
      list.push({
        kind: "message",
        id: `msg-${msg.message_id}`,
        message: msg,
        order,
      });
    });

    localToolRuns.forEach((run, idx) => {
      const order =
        typeof run.timeline_order === "number"
          ? run.timeline_order
          : (run.sequence ?? idx) * 10 + 5;
      list.push({
        kind: "tool_run",
        id: `tool-${run.tool_call_id}`,
        toolRun: run,
        order,
      });
    });

    // 稳定排序：按 order 升序
    list.sort((a, b) => a.order - b.order);

    return list;
  }, [localMessages, localToolRuns]);

  const isStreaming = useMemo(() => {
    return (
      localMessages.some((m) => m.streaming === true) ||
      localToolRuns.some((t) => t.status === "running")
    );
  }, [localMessages, localToolRuns]);

  return {
    items,
    messages: localMessages,
    toolRuns: localToolRuns,
    isStreaming,
  };
}
