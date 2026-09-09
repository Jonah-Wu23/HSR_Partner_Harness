import { useState } from "react";
import type { ConversationSummary, PairMemory } from "@shared/contracts/protocol";
import {
  CheckIcon,
  ChevronDownIcon,
  ErrorIcon,
  SpinnerIcon,
  WarningIcon,
} from "./cards/icons";
import "./ContextStatusStrip.css";

/**
 * V0.3.9 V02（移动）压缩 / 记忆非消息状态条。
 *
 * 契约依据（归档正文 .archive/v0.3.9-dual-track-backup-2026-09-10/logic-worktree/V0.3.9-契约冻结.md §2）：
 * - 摘要与记忆状态用非消息状态条展示，不占用消息条目，不承载隐藏提示。
 * - 失败状态可展开原始错误（error_code + error 原文，不重写、不吞）。
 * - summary.regenerate 只针对真实存在的失败记录或用户显式请求；没有真实恢复
 *   能力时 UI 不显示恢复按钮，因此本组件只在调用方提供 onRegenerate 且状态
 *   满足条件时渲染按钮。
 * - 无数据（null / 字段缺省）与零值（0 条记忆）严格区分：memories === null
 *   不渲染记忆行，memories === [] 才显示真实零值文案。
 *
 * 待真实接线：mobileStore 目前不消费 summary.* / memory.* 事件，也没有
 * summary/memory 字段（L02–L04 未接线）。本组件只接收 protocol.ts 冻结类型
 * 的 props，数据由 pages/chat/useContextStatus.ts 适配层注入；未接线时组件
 * 整体不渲染，不显示任何伪造状态或伪造零指标。
 */

export interface ContextStatusStripProps {
  /** 真实摘要记录（summary.get / summary.started|completed|failed）；null=无数据。 */
  summary?: ConversationSummary | null;
  /** 真实记忆记录（memory.list / memory.updated|deleted）；null=无数据，[]=零条。 */
  memories?: PairMemory[] | null;
  /** 恢复回调：仅当 summary.regenerate 有真实对象（失败记录或用户显式请求）时由调用方提供。 */
  onRegenerate?: ((summaryId: string) => void) | null;
  /** 恢复提交中（等待 summary.started/completed/failed 收敛）。 */
  regenerating?: boolean;
  /** summary.regenerate 命令的真实错误原文；由调用方捕获后传入，不吞异常。 */
  regenerateError?: string | null;
  /** 用户显式请求恢复（无失败记录时也允许恢复）；默认 false。 */
  regenerateRequested?: boolean;
  /** 记忆作用域不可用时的真实原因（如项目为空的日常聊天不读写长期记忆）。 */
  memoryScopeNote?: string | null;
}

const SUMMARY_TITLES: Record<ConversationSummary["status"], string> = {
  idle: "摘要尚未生成",
  running: "正在压缩长对话…",
  completed: "已完成压缩",
  failed: "压缩失败",
};

function summaryTone(status: ConversationSummary["status"]): string {
  if (status === "running") return "is-running";
  if (status === "completed") return "is-completed";
  if (status === "failed") return "is-failed";
  return "is-idle";
}

function SummaryIcon({ status }: { status: ConversationSummary["status"] }) {
  if (status === "running") return <SpinnerIcon />;
  if (status === "completed") return <CheckIcon />;
  if (status === "failed") return <ErrorIcon />;
  return <WarningIcon />;
}

export function ContextStatusStrip({
  summary = null,
  memories = null,
  onRegenerate = null,
  regenerating = false,
  regenerateError = null,
  regenerateRequested = false,
  memoryScopeNote = null,
}: ContextStatusStripProps) {
  const [errorExpanded, setErrorExpanded] = useState(false);

  // 无数据：不渲染状态条（既不是「压缩完成」也不是「零条记忆」）。
  if (!summary && memories === null) return null;

  const activeMemories = memories
    ? memories.filter((item) => item.status === "active").length
    : null;
  const deletedMemories = memories
    ? memories.filter((item) => item.status === "deleted").length
    : null;
  const canRegenerate = Boolean(
    summary &&
      onRegenerate &&
      summary.summary_id &&
      (summary.status === "failed" || regenerateRequested),
  );
  const tone = summary ? summaryTone(summary.status) : "is-idle";

  return (
    <section
      className={`mobile-context-strip ${tone}`}
      data-testid="context-status-strip"
      data-summary-status={summary?.status ?? "none"}
      data-memory-count={activeMemories === null ? "none" : String(activeMemories)}
      aria-label="对话上下文状态"
    >
      {summary ? (
        <div
          className="mobile-context-row"
          data-testid="summary-status-row"
          data-status={summary.status}
        >
          <span
            className={`mobile-context-icon mobile-context-status-${summary.status}`}
            aria-hidden="true"
          >
            <SummaryIcon status={summary.status} />
          </span>
          <span className="mobile-context-text" data-testid="summary-status-text">
            {SUMMARY_TITLES[summary.status]}
          </span>
          {typeof summary.covers_message_count === "number" ? (
            <span className="mobile-context-meta" data-testid="summary-covered-count">
              已覆盖 {summary.covers_message_count} 条
            </span>
          ) : null}
          {summary.status === "failed" ? (
            <button
              type="button"
              className="mobile-context-toggle"
              data-testid="summary-error-toggle"
              aria-expanded={errorExpanded}
              onClick={() => setErrorExpanded((prev) => !prev)}
            >
              {errorExpanded ? "收起错误" : "展开原始错误"}
              <span
                className={`mobile-context-chevron${errorExpanded ? " is-open" : ""}`}
                aria-hidden="true"
              >
                <ChevronDownIcon />
              </span>
            </button>
          ) : null}
        </div>
      ) : null}

      {summary && summary.status === "failed" && errorExpanded ? (
        <div className="mobile-context-detail" data-testid="summary-error-detail">
          {summary.error_code !== null && summary.error_code !== undefined ? (
            <div className="mobile-context-detail-row">
              <span className="mobile-context-detail-label">error_code</span>
              <code className="mobile-context-code" data-testid="summary-error-code">
                {summary.error_code}
              </code>
            </div>
          ) : null}
          <div className="mobile-context-detail-row">
            <span className="mobile-context-detail-label">原始错误</span>
            {summary.error ? (
              <pre className="mobile-context-code" data-testid="summary-error-text">
                {summary.error}
              </pre>
            ) : (
              // 服务端未提供错误原文：如实说明缺失，不合成空结果也不补默认文案。
              <span className="mobile-context-meta" data-testid="summary-error-text">
                服务端未提供 error 原文
              </span>
            )}
          </div>
          {summary.provider || summary.model ? (
            <div className="mobile-context-detail-row">
              <span className="mobile-context-detail-label">模型</span>
              <span className="mobile-context-meta">
                {[summary.provider, summary.model].filter(Boolean).join(" / ")}
              </span>
            </div>
          ) : null}
          <p className="mobile-context-footnote">
            压缩触发阈值 80 条或 256 KiB，触发后保留最近 12 条原文；原文永久保留。
          </p>
        </div>
      ) : null}

      {canRegenerate ? (
        <div className="mobile-context-actions">
          <button
            type="button"
            className="mobile-context-regenerate"
            data-testid="summary-regenerate"
            disabled={regenerating}
            onClick={() => {
              if (summary) onRegenerate?.(summary.summary_id);
            }}
          >
            {regenerating ? "恢复中…" : "重新生成摘要"}
          </button>
        </div>
      ) : null}

      {regenerateError ? (
        <p
          className="mobile-context-error"
          role="alert"
          data-testid="summary-regenerate-error"
        >
          恢复失败：{regenerateError}
        </p>
      ) : null}

      {memories !== null ? (
        <div
          className="mobile-context-row"
          data-testid="memory-status-row"
          data-active-count={String(activeMemories ?? 0)}
        >
          <span
            className={`mobile-context-icon ${
              activeMemories && activeMemories > 0
                ? "mobile-context-status-completed"
                : "mobile-context-status-idle"
            }`}
            aria-hidden="true"
          >
            {activeMemories && activeMemories > 0 ? <CheckIcon /> : <WarningIcon />}
          </span>
          <span className="mobile-context-text" data-testid="memory-status-text">
            {activeMemories && activeMemories > 0
              ? `长期记忆 ${activeMemories} 条`
              : "长期记忆暂无记录"}
          </span>
          {deletedMemories && deletedMemories > 0 ? (
            <span className="mobile-context-meta">已删除 {deletedMemories} 条</span>
          ) : null}
        </div>
      ) : null}

      {memoryScopeNote ? (
        <p className="mobile-context-footnote" data-testid="memory-scope-note">
          {memoryScopeNote}
        </p>
      ) : null}
    </section>
  );
}
