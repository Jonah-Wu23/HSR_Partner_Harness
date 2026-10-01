import { type FormEvent, useState } from "react";
import type { QueueItem } from "@shared/contracts/protocol";

export interface QueueItemRowProps {
  queueItem: QueueItem;
  onWithdraw: () => Promise<void>;
  onPrioritize: () => Promise<void>;
  onEdit: (text: string) => Promise<void>;
}

/**
 * 忙时排队的用户消息行。状态由服务端 queue.changed 全量快照驱动：
 * queued 可置顶、编辑、撤回；failed 展示服务端失败原因，可撤回。
 * 命令失败时展示原始错误，编辑框保持打开。
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
  const failed = queueItem.status === "failed";

  const startEdit = () => {
    setDraft(queueItem.text);
    setError(null);
    setEditing(true);
  };

  /** 执行命令；失败时展示原始错误并返回 false。 */
  const runAction = async (action: () => Promise<void>): Promise<boolean> => {
    setError(null);
    try {
      await action();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    }
  };

  const saveEdit = async (event?: FormEvent) => {
    event?.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (await runAction(() => onEdit(trimmed))) setEditing(false);
  };

  return (
    <div
      className={`queue-item${failed ? " queue-item-failed" : ""}`}
      data-testid="queue-item-row"
      data-queue-status={queueItem.status}
    >
      <div className="queue-item-head">
        <span className="queue-item-badge">{failed ? "发送失败" : "排队中"}</span>
        {queueItem.target === "assistant" ? (
          <span className="queue-item-target">委派</span>
        ) : null}
        <div className="queue-item-actions">
          {failed ? null : (
            <>
              <button type="button" onClick={() => void runAction(onPrioritize)}>
                置顶
              </button>
              <button type="button" onClick={startEdit}>
                编辑
              </button>
            </>
          )}
          <button type="button" onClick={() => void runAction(onWithdraw)}>
            撤回
          </button>
        </div>
      </div>
      {failed && queueItem.error ? (
        <p className="queue-item-error" role="alert" data-testid="queue-item-failure">
          {queueItem.error}
        </p>
      ) : null}
      {editing ? (
        <form className="queue-item-edit" onSubmit={(event) => void saveEdit(event)}>
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
