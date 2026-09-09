import { useMemo } from "react";
import type { ConversationSummary, PairMemory } from "@shared/contracts/protocol";
import { useMobileStore } from "../../lib/mobileStore";

/**
 * V0.3.9 V02（移动）压缩 / 记忆状态适配层。
 *
 * 待真实接线：mobileStore 目前不消费 `summary.started/completed/failed` 与
 * `memory.updated/deleted` 事件，也没有摘要 / 记忆字段（L02–L04 未接线）。
 * 本适配层按 protocol.ts 冻结类型（ConversationSummary / PairMemory）读取，
 * 字段缺失时一律返回 null（无数据），不合成零值、不伪造状态、不猜默认值。
 *
 * 精确跨轨需求（字段 / 事件）见交付报告；一旦 store 提供下列任一来源，本
 * 适配层无需改动即可消费：
 * 1. `summaryByConversationId: Record<string, ConversationSummary>`
 * 2. `memoriesByConversationId: Record<string, PairMemory[]>`
 * 3. ConversationRecord 上的 `summary` / `memories` 字段（快照随会话下发）
 * 4. `regenerateSummary(summaryId)` 动作（对应 summary.regenerate 命令）
 */

/** 逻辑轨待提供的 store 扩展字段（缺失即为 undefined，不做默认值填充）。 */
interface ContextStatusStoreFields {
  summaryByConversationId?: Record<string, ConversationSummary | undefined>;
  memoriesByConversationId?: Record<string, PairMemory[] | undefined>;
  regenerateSummary?: (summaryId: string) => Promise<void>;
}

/** 会话记录上待提供的快照字段（与 conversation.open 快照同源）。 */
interface ConversationContextFields {
  summary?: ConversationSummary | null;
  memories?: PairMemory[] | null;
}

export interface ContextStatusView {
  /** 真实摘要记录；null 表示无数据（尚未接线或服务端未下发）。 */
  summary: ConversationSummary | null;
  /** 真实记忆记录；null 表示无数据，[] 表示服务端确认零条。 */
  memories: PairMemory[] | null;
  /** 真实恢复动作；未接线时为 null，UI 因此不渲染恢复按钮。 */
  regenerateSummary: ((summaryId: string) => Promise<void>) | null;
}

export function useContextStatus(conversationId: string): ContextStatusView {
  const summary = useMobileStore((state) => {
    const extended = state as typeof state & ContextStatusStoreFields;
    const fromMap = extended.summaryByConversationId?.[conversationId];
    if (fromMap !== undefined) return fromMap ?? null;
    const record = state.conversationsById[conversationId] as
      | (typeof state.conversationsById[string] & ConversationContextFields)
      | undefined;
    return record?.summary ?? null;
  });

  const memories = useMobileStore((state) => {
    const extended = state as typeof state & ContextStatusStoreFields;
    const fromMap = extended.memoriesByConversationId?.[conversationId];
    if (fromMap !== undefined) return fromMap;
    const record = state.conversationsById[conversationId] as
      | (typeof state.conversationsById[string] & ConversationContextFields)
      | undefined;
    return record?.memories ?? null;
  });

  const regenerateSummary = useMobileStore(
    (state) => (state as typeof state & ContextStatusStoreFields).regenerateSummary ?? null,
  );

  return useMemo(
    () => ({ summary, memories, regenerateSummary }),
    [summary, memories, regenerateSummary],
  );
}
