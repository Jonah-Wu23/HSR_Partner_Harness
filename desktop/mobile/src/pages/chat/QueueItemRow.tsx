import { type FormEvent, useState } from "react";
import type { QueueItem } from "@shared/contracts/protocol";

export interface QueueItemRowProps {
  queueItem: QueueItem;
  onWithdraw: () => void | Promise<void>;
  onPrioritize: () => void | Promise<void>;
  onEdit: (text: string) => void | Promise<void>;
}

/**
 * V0.3.8 T5（契约 §14.1）：忙时排队中的用户消息行。
 * 状态由服务端 queue.changed 全量快照驱动；三个命令真实下发，失败
 * 如实呈现错误，不伪造成功。
 */
export function QueueItemRow({
  queueItem,
  onWithdraw,
  onPrioritize,
  onEdit,
}: QueueItemRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(queueItem.text);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setDraft(queueItem.text);
    setError(null);
    setEditing(true);
  };

  const runAction = async (action: () => void | Promise<void>) => {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  };

  const saveEdit = (event?: FormEvent) => {
    event?.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    void runAction(() => onEdit(trimmed)).then(() => setEditing(false));
  };

  return (
    <div className="queue-item" data-testid="queue-item-row">
      <div className="queue-item-head">
        <span className="queue-item-badge">排队中</span>
        {queueItem.target === "assistant" ? (
          <span className="queue-item-target">委派</span>
        ) : null}
        <div className="queue-item-actions">
          <button type="button" onClick={() => void runAction(onPrioritize)}>
            置顶
          </button>
          <button type="button" onClick={startEdit}>
            编辑
          </button>
          <button type="button" onClick={() => void runAction(onWithdraw)}>
            撤回
          </button>
        </div>
      </div>
      {editing ? (
        <form className="queue-item-edit" onSubmit={saveEdit}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={3}
            aria-label="编辑排队消息"
          />
          <div className="queue-item-edit-actions">
            <button type="submit" disabled={!draft.trim()}>
              保存
            </button>
            <button type="button" onClick={() => setEditing(false)}>
              取消
            </button>
          </div>
        </form>
      ) : (
        <p className="queue-item-text">{queueItem.text}</p>
      )}
      {error ? (
        <p className="queue-item-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
