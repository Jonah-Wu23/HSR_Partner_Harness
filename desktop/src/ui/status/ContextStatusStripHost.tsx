import { memo } from "react";
import type { HarnessActions } from "../../contracts/actions";
import { selectWindowProjectId, useDesktopStore } from "../../stores/desktopStore";
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
 */
export const ContextStatusStripHost = memo(function ContextStatusStripHost({
  actions,
}: ContextStatusStripHostProps) {
  const conversationId = useDesktopStore((state) => state.activeConversationId);
  const summaries = useDesktopStore((state) =>
    conversationId ? (state.summariesByConversation[conversationId] ?? null) : null,
  );
  const memories = useDesktopStore((state) => state.memories);
  const regenerate = useDesktopStore((state) => state.summaryRegenerateTarget);
  const projectId = useDesktopStore(selectWindowProjectId);

  if (!conversationId) return null;
  return (
    <ContextStatusStrip
      summaries={summaries}
      memories={memories}
      regenerate={regenerate}
      onRegenerate={(target) => actions.regenerateSummary(target.summary_id, target.conversation_id)}
      projectId={projectId}
    />
  );
});
