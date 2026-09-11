import { useState } from "react";

import type { ConversationSummary, PairMemory } from "../../contracts/protocol";

/** 压缩触发原因：契约 §2 的两种触发条件，manual 表示用户显式请求重新生成。 */
export type SummaryTriggerReason = "message_count" | "byte_size" | "manual";

/**
 * 触发详情。contract-v1 的 ConversationSummary 与 summary.* 事件暂未携带触发原因，
 * 由父级适配后传入；缺字段保持 null，界面如实显示「无数据」，不硬编码 80 条 / 256 KiB。
 */
export interface SummaryTriggerInfo {
  reason: SummaryTriggerReason;
  /** 触发时服务端观测到的计数（消息条数或 UTF-8 正文字节数）；未提供为 null。 */
  observed: number | null;
  /** 服务端生效阈值；未提供为 null，前端不猜。 */
  threshold: number | null;
}

/**
 * 真实存在的 summary.regenerate 目标。为 null/缺省时不渲染恢复按钮
 * （契约 §2：没有真实恢复能力时 UI 不显示恢复按钮）。
 */
export interface SummaryRegenerateTarget {
  summary_id: string;
  conversation_id: string;
  /** failed_record = 真实失败记录；user_request = 用户显式请求。 */
  reason: "failed_record" | "user_request";
}

export interface ContextStatusStripProps {
  /** 压缩记录（contract-v1 §2 ConversationSummary）。null/缺省 = 未读取；[] = 真实零条。 */
  summaries?: ConversationSummary[] | null;
  /** 配对记忆记录（contract-v1 §2 PairMemory）。null/缺省 = 未读取；[] = 真实零条。 */
  memories?: PairMemory[] | null;
  /** 触发详情，键为 summary_id；协议字段待补，缺失即「未报告」。 */
  triggers?: Record<string, SummaryTriggerInfo> | null;
  /** 只在有真实对象时显示恢复按钮。 */
  regenerate?: SummaryRegenerateTarget | null;
  onRegenerate?: (target: SummaryRegenerateTarget) => void | Promise<void>;
  /** 用户处理（关闭）状态行。失败行不会自动消失；未提供时不渲染关闭按钮。 */
  onDismiss?: (summaryId: string) => void;
  /** 显式传 null 表示日常聊天（无项目）：不读写长期记忆，界面如实说明。 */
  projectId?: string | null;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MiB`;
}

function describeTrigger(trigger: SummaryTriggerInfo | null): string {
  if (!trigger) return "触发原因：未报告";
  if (trigger.reason === "manual") return "触发原因：用户显式请求";
  const unit = trigger.reason === "message_count" ? "条" : "字节";
  const label =
    trigger.reason === "message_count" ? "消息条数达到阈值" : "UTF-8 正文字节数达到阈值";
  const observed =
    trigger.observed === null
      ? "已观测：无数据"
      : `已观测：${trigger.reason === "message_count" ? `${trigger.observed} ${unit}` : formatBytes(trigger.observed)}`;
  const threshold =
    trigger.threshold === null
      ? "阈值：无数据"
      : `阈值：${trigger.reason === "message_count" ? `${trigger.threshold} ${unit}` : formatBytes(trigger.threshold)}`;
  return `触发原因：${label} · ${observed} · ${threshold}`;
}

const STATUS_LABEL: Record<ConversationSummary["status"], string> = {
  idle: "空闲",
  running: "正在压缩上下文…",
  completed: "压缩已完成",
  failed: "压缩失败",
};

/**
 * V0.3.9 V02 桌面端上下文状态条（压缩 / 长期记忆）。
 *
 * 非消息状态条（非消息条目）：挂在聊天视图内、输入区之上，形态参考 ToastStack /
 * PowerPrompt，不进入消息时间线，也不占用模态焦点。压缩失败持久保留到用户处理
 * （关闭按钮是「用户处理」），不自动消失；失败可展开 error_code 与原始 error。
 *
 * 长期记忆只展示服务端解析出的作用域分量，客户端不拼键、不写死；
 * 恢复按钮只在父级传入真实 summary.regenerate 目标时出现。
 *
 * 数据来源（待真实接线）：contract-v1 的 ConversationSummary / PairMemory 由逻辑轨
 * store 与 presenters 提供，本组件只消费 props，不订阅 store、不调协议。
 */
export function ContextStatusStrip({
  summaries,
  memories,
  triggers,
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
  const regenerateMissingRow =
    regenerate && regenerate.reason === "user_request"
      ? !rows.some((summary) => summary.summary_id === regenerate.summary_id)
      : false;

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
      // Let It Fail：恢复失败原文上屏，不吞异常、不合成成功。
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
          regenerate !== null &&
          regenerate !== undefined &&
          regenerate.summary_id === summary.summary_id &&
          (regenerate.reason === "user_request" || summary.status === "failed");
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
            <span
              className="context-strip-note"
              data-testid={`context-strip-trigger-${summary.summary_id}`}
            >
              {describeTrigger(triggers?.[summary.summary_id] ?? null)}
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

      {regenerateMissingRow && regenerate ? (
        <div className="context-strip-row is-pending" data-testid="context-strip-regenerate-orphan">
          <span className="context-strip-status context-strip-status-pending">用户请求重新生成</span>
          <span className="context-strip-value">目标摘要：{regenerate.summary_id}</span>
          {renderRegenerate(regenerate.summary_id)}
        </div>
      ) : null}

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
