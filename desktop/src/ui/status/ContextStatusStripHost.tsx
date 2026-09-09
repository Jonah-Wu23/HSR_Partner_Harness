import type { HarnessActions } from "../../contracts/actions";
import { useDesktopStore } from "../../stores/desktopStore";
import {
  ContextStatusStrip,
  type SummaryRegenerateTarget,
  type SummaryTriggerInfo,
} from "./ContextStatusStrip";

interface ContextStatusStripHostProps {
  /** 重新生成摘要走 actions（summary.regenerate 真实请求）；未提供时不显示恢复按钮。 */
  actions?: HarnessActions;
}

/**
 * V0.3.9 V02 上下文状态条接线层：把 store 的摘要/记忆/触发详情/恢复目标
 * 适配为视觉组件 props。挂载于聊天视图（输入区之上），由 AppShell 摆放。
 *
 * 数据来源与空值语义（契约 §2/§5）：
 * - summaries：summariesByConversation[当前聊天]；未读取为 null，真实零条为 []；
 * - memories：服务端按冻结作用域过滤后下发的配对级生效记忆；
 * - summaryTriggers：协议尚未携带触发原因，缺失即「未报告」，由组件如实显示；
 * - summaryRegenerateTarget：只在 summary.failed 真实失败记录上出现；
 * - projectId：当前项目；null 表示日常聊天（无项目），组件如实说明不读写记忆。
 */
export function ContextStatusStripHost({ actions }: ContextStatusStripHostProps) {
  const conversationId = useDesktopStore((state) => state.activeConversationId);
  const summaries = useDesktopStore((state) =>
    conversationId ? (state.summariesByConversation[conversationId] ?? null) : null,
  );
  const memories = useDesktopStore((state) => state.memories);
  const triggers = useDesktopStore((state) =>
    conversationId ? (state.summaryTriggersByConversation[conversationId] ?? null) : null,
  );
  const regenerate = useDesktopStore((state) => state.summaryRegenerateTarget);
  const projectId = useDesktopStore(
    (state) => state.activeProjectId ?? state.currentProjectId ?? null,
  );

  if (!conversationId) return null;
  const regenerateSummary = actions?.regenerateSummary;
  if (!regenerateSummary) {
    // 没有真实重新生成能力时只展示状态，不渲染恢复按钮（组件缺省行为）。
    return (
      <ContextStatusStrip
        summaries={summaries}
        memories={memories}
        triggers={triggers as Record<string, SummaryTriggerInfo> | null | undefined}
        projectId={projectId}
      />
    );
  }
  return (
    <ContextStatusStrip
      summaries={summaries}
      memories={memories}
      triggers={triggers as Record<string, SummaryTriggerInfo> | null | undefined}
      regenerate={regenerate}
      onRegenerate={(target: SummaryRegenerateTarget) =>
        regenerateSummary({
          summary_id: target.summary_id,
          conversation_id: target.conversation_id,
          reason: target.reason,
        })
      }
      projectId={projectId}
    />
  );
}
