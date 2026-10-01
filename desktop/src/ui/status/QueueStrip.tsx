import { memo } from "react";
import type { QueueItemView } from "./types";

interface QueueStripProps {
  items: QueueItemView[];
  /** 搭档显示名，缺省回退到「角色/助手」。 */
  names?: { character: string; assistant: string };
  /** 编辑：把该条拉回输入区。 */
  onEdit: (queueItemId: string) => void;
  /** 撤回：从队列移除。 */
  onWithdraw: (queueItemId: string) => void;
  /** 立即插入：请求中断当前回合后优先处理。 */
  onPrioritize: (queueItemId: string) => void;
}

/** 排队条：输入区上方的横向胶囊条，忙碌时发送的消息在这里可见可操作。 */
export const QueueStrip = memo(function QueueStrip({
  items,
  names,
  onEdit,
  onWithdraw,
  onPrioritize,
}: QueueStripProps) {
  if (items.length === 0) return null;
  const targetLabel = {
    character: `给${names?.character ?? "角色"}`,
    assistant: `给${names?.assistant ?? "助手"}`,
  } as const;
  return (
    <section className="queue-strip" aria-label={`排队 ${items.length} 条`}>
      <span className="queue-strip-count">排队 {items.length} 条</span>
      <ol className="queue-strip-list">
        {items.map((item) => (
          <li
            key={item.queueItemId}
            className={`queue-capsule${item.failed ? " is-failed" : ""}`}
            data-queue-status={item.failed ? "failed" : undefined}
          >
            <span
              className={`pair-dot ${item.target === "character" ? "pair-dot-character" : "pair-dot-assistant"}`}
              aria-hidden
            />
            <span className="queue-capsule-text">
              <span className="queue-capsule-target">{targetLabel[item.target]}</span>
              <span className="queue-capsule-summary">「{item.summary}」</span>
              {item.failed ? (
                <span className="queue-capsule-error" role="alert">
                  {" "}· 派发失败{item.error ? `：${item.error}` : ""}
                </span>
              ) : (
                <span className="queue-capsule-waiting"> · {item.waitingFor}</span>
              )}
            </span>
            <span className="queue-capsule-actions">
              {/* 失败项不会再被派发，后端只接受撤回 */}
              {item.failed ? null : (
                <button type="button" onClick={() => onEdit(item.queueItemId)}>
                  编辑
                </button>
              )}
              <button type="button" onClick={() => onWithdraw(item.queueItemId)}>
                撤回
              </button>
              {item.failed ? null : (
                <button type="button" onClick={() => onPrioritize(item.queueItemId)}>
                  立即插入
                </button>
              )}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
});
