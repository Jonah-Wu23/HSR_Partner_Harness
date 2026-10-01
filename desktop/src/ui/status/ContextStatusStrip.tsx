import { useState } from "react";

import type { ConversationSummary, PairMemory } from "../../contracts/protocol";
import type { SummaryRegenerateTarget } from "../../contracts/view-models";

export interface ContextStatusStripProps {
  /** 摘要记录。null 或缺省表示没有数据，[] 是零条。 */
  summaries?: ConversationSummary[] | null;
  /** 长期记忆记录。null 或缺省表示没有数据，[] 是零条。 */
  memories?: PairMemory[] | null;
  /** summary.failed 留下的重新生成目标；只在有目标时显示重新生成按钮。 */
  regenerate?: SummaryRegenerateTarget | null;
  onRegenerate?: (target: SummaryRegenerateTarget) => void | Promise<void>;
  /** 关闭状态行；失败行不会自动消失，未提供时不渲染关闭按钮。 */
  onDismiss?: (summaryId: string) => void;
  /** null 表示日常聊天（无项目），不读写长期记忆，界面加以说明。 */
  projectId?: string | null;
}

const STATUS_LABEL: Record<ConversationSummary["status"], string> = {
  idle: "空闲",
  running: "正在压缩上下文…",
  completed: "压缩已完成",
  failed: "压缩失败",
};

/**
 * 上下文状态条（压缩与长期记忆），挂在聊天视图的输入区之上，不进入消息时间线，
 * 也不占用模态焦点。压缩失败保留到用户关闭，可展开 error_code 与原始 error。
 * 长期记忆只展示服务端解析出的作用域分量。
 */
export function ContextStatusStrip({
  summaries,
  memories,
  regenerate,
  onRegenerate,
  onDismiss,
  projectId,
}: ContextStatusStripProps) {
  const [expanded, setExpanded] = useState<string[]>([]);
  const [pendingSummaryId, setPendingSummaryId] = useState<string | null>(null);
  const [regenerateErrors, setRegenerateErrors] = useState<Record<string, string>>({});

  const rows = (summaries ?? []).filter((summary) => summary.status !== "idle");
  const activeMemories = memories === null || memories === undefined
    ? null
    : memories.filter((memory) => memory.status === "active");
  const memoryScope = (activeMemories?.find((memory) => memory.scope) ?? memories?.find((memory) => memory.scope))?.scope ?? null;

  if (rows.length === 0 && activeMemories === null && projectId !== null) return null;

  const toggleExpanded = (summaryId: string) => {
    setExpanded((current) =>
      current.includes(summaryId)
        ? current.filter((id) => id !== summaryId)
        : [...current, summaryId],
    );
  };

  const runRegenerate = async (target: SummaryRegenerateTarget) => {
    if (!onRegenerate) return;
    setPendingSummaryId(target.summary_id);
    setRegenerateErrors((current) => {
      const next = { ...current };
      delete next[target.summary_id];
      return next;
    });
    try {
      await onRegenerate(target);
    } catch (error) {
      // 请求失败原文显示在按钮旁。
      setRegenerateErrors((current) => ({
        ...current,
        [target.summary_id]: error instanceof Error ? error.message : String(error),
      }));
    } finally {
      setPendingSummaryId(null);
    }
  };

  const renderRegenerate = (summaryId: string) => {
    if (!regenerate || !onRegenerate || regenerate.summary_id !== summaryId) return null;
    const pending = pendingSummaryId === summaryId;
    const error = regenerateErrors[summaryId];
    return (
      <div className="context-strip-actions">
        <button
          type="button"
          className="btn btn-outline context-strip-btn"
          disabled={pending}
          onClick={() => void runRegenerate(regenerate)}
          data-testid={`context-strip-regenerate-${summaryId}`}
        >
          {pending ? "正在请求重新生成…" : "重新生成摘要"}
        </button>
        {error ? (
          <span className="context-strip-action-error" role="alert">
            重新生成失败：{error}
          </span>
        ) : null}
      </div>
    );
  };

  return (
    <section
      className="context-status-strip"
      role="status"
      aria-live="polite"
      aria-label="上下文状态"
      data-testid="context-status-strip"
    >
      <div className="context-strip-head">
        <span className="context-strip-title">上下文状态</span>
      </div>

      {rows.map((summary) => {
        const isExpanded = expanded.includes(summary.summary_id);
        const canRegenerate =
          summary.status === "failed" && regenerate?.summary_id === summary.summary_id;
        return (
          <div
            key={summary.summary_id}
            className={`context-strip-row is-${summary.status}`}
            data-testid={`context-strip-summary-${summary.summary_id}`}
          >
            <span
              className={`context-strip-status context-strip-status-${summary.status}`}
              data-testid={`context-strip-status-${summary.summary_id}`}
            >
              {STATUS_LABEL[summary.status]}
            </span>
            <span className="context-strip-scope">本聊天摘要</span>
            <span
              className="context-strip-value"
              title={
                summary.covers_from_message_id && summary.covers_to_message_id
                  ? `覆盖范围：${summary.covers_from_message_id} 至 ${summary.covers_to_message_id}`
                  : undefined
              }
            >
              已覆盖 {summary.covers_message_count} 条
              {summary.provider || summary.model
                ? ` · ${summary.provider ?? "未报告供应商"}/${summary.model ?? "未报告模型"}`
                : " · 供应商与模型：未报告"}
            </span>

            {summary.status === "failed" ? (
              <>
                <button
                  type="button"
                  className="context-strip-toggle"
                  aria-expanded={isExpanded}
                  onClick={() => toggleExpanded(summary.summary_id)}
                  data-testid={`context-strip-expand-${summary.summary_id}`}
                >
                  {isExpanded ? "收起原始错误" : "展开原始错误"}
                </button>
                {isExpanded ? (
                  <dl className="context-strip-error" data-testid={`context-strip-error-${summary.summary_id}`}>
                    <div>
                      <dt>错误码</dt>
                      <dd>
                        <code>{summary.error_code ?? "服务端未返回 error_code"}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>原始错误</dt>
                      <dd>
                        <code>{summary.error ?? "服务端未返回 error 原文"}</code>
                      </dd>
                    </div>
                  </dl>
                ) : null}
              </>
            ) : null}

            {canRegenerate ? renderRegenerate(summary.summary_id) : null}

            {onDismiss ? (
              <button
                type="button"
                className="context-strip-close"
                aria-label={`关闭${STATUS_LABEL[summary.status]}状态条`}
                onClick={() => onDismiss(summary.summary_id)}
              >
                ×
              </button>
            ) : null}
          </div>
        );
      })}


      {activeMemories !== null ? (
        <div className="context-strip-row is-memory" data-testid="context-strip-memory">
          <span className="context-strip-status context-strip-status-completed">长期记忆已启用</span>
          <span className="context-strip-scope">配对共享</span>
          <span className="context-strip-value" data-testid="context-strip-memory-count">
            {activeMemories.length} 条生效
            {memories && memories.length !== activeMemories.length
              ? ` · 共 ${memories.length} 条记录（含已删除）`
              : ""}
          </span>
          {memoryScope ? (
            <dl className="context-strip-scope-facts" data-testid="context-strip-memory-scope">
              <div>
                <dt>搭档</dt>
                <dd>{memoryScope.pair_id || "未报告"}</dd>
              </div>
              <div>
                <dt>角色</dt>
                <dd>{memoryScope.character_ref}</dd>
              </div>
              <div>
                <dt>助手身份</dt>
                <dd>{memoryScope.assistant_identity}</dd>
              </div>
              <div>
                <dt>项目</dt>
                <dd>{memoryScope.project_id || "未报告"}</dd>
              </div>
              <div>
                <dt>账号</dt>
                <dd>{memoryScope.account_id || "未报告"}</dd>
              </div>
            </dl>
          ) : (
            <span className="context-strip-note">作用域：服务端未返回</span>
          )}
          <span className="context-strip-note">作用域由服务端解析，客户端只传 conversation_id</span>
        </div>
      ) : projectId === null ? (
        <div className="context-strip-row is-memory is-muted" data-testid="context-strip-memory-disabled">
          <span className="context-strip-status">长期记忆</span>
          <span className="context-strip-value">日常聊天（无项目）不读写长期记忆</span>
        </div>
      ) : null}
    </section>
  );
}
