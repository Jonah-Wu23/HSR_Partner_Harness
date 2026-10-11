import { memo, useEffect } from "react";
import type { HarnessActions } from "../../contracts/actions";
import { isCharacterIdentityAvailable } from "../../presenters/conversationIdentity";
import { findPairAssistantName, pickMemoryScope } from "../../presenters/memoryScope";
import {
  selectWindowCharacterIdentity,
  selectWindowProjectId,
  useDesktopStore,
} from "../../stores/desktopStore";
import { ContextStatusStrip } from "./ContextStatusStrip";

interface ContextStatusStripHostProps {
  /** 重新生成摘要走 summary.regenerate。 */
  actions: HarnessActions;
}

/**
 * 上下文状态条接线层：把 store 的摘要、记忆与重新生成目标交给视觉组件，
 * 挂在聊天视图的输入区之上。
 *
 * summaries 为 null 表示该聊天还没有摘要事件；重新生成目标只在 summary.failed 后出现；
 * projectId 为 null 表示日常聊天（无项目），组件说明不读写长期记忆。
 *
 * 状态条展示的记忆作用域就是本窗口活动会话的作用域，因此角色显示名取该会话的
 * character_identity，助手显示名按作用域 pair_id 在搭档目录里查；两者都拿不到时
 * 传 null，组件回退服务端原始 id。
 */
export const ContextStatusStripHost = memo(function ContextStatusStripHost({
  actions,
}: ContextStatusStripHostProps) {
  const conversationId = useDesktopStore((state) => state.activeConversationId);
  const summaries = useDesktopStore((state) =>
    conversationId ? (state.summariesByConversation[conversationId] ?? null) : null,
  );
  const memories = useDesktopStore((state) =>
    conversationId ? (state.memoriesByConversation[conversationId] ?? null) : null,
  );
  const regenerate = useDesktopStore((state) =>
    state.summaryRegenerateTarget?.conversation_id === conversationId
      ? state.summaryRegenerateTarget
      : null,
  );
  const projectId = useDesktopStore(selectWindowProjectId);
  const characterIdentity = useDesktopStore(selectWindowCharacterIdentity);
  const pairs = useDesktopStore((state) => state.pairs);

  useEffect(() => {
    if (!conversationId || projectId === null) return;
    void actions.listMemories({ conversationId });
  }, [actions, conversationId, projectId]);

  if (!conversationId) return null;
  return (
    <ContextStatusStrip
      key={conversationId}
      summaries={summaries}
      memories={memories}
      regenerate={regenerate}
      onRegenerate={(target) => actions.regenerateSummary(target.summary_id, target.conversation_id)}
      projectId={projectId}
      characterName={isCharacterIdentityAvailable(characterIdentity) ? characterIdentity.name : null}
      assistantName={findPairAssistantName(pairs, pickMemoryScope(memories)?.pair_id)}
    />
  );
});
