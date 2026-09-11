import type { PendingApproval } from "@shared/contracts/protocol";
import { ShieldIcon } from "./icons";

export interface ApprovalCardProps {
  approval: PendingApproval;
  conversationTitle?: string;
  /** V0.3.5：提交中状态（点击后等待服务器/事件收敛）。 */
  resolving?: boolean;
  onApprove?: () => void;
  /** V0.3.5：仅本会话内生效的批准（ApprovalDecision.allow_for_conversation）。 */
  onAllowForConversation?: () => void;
  onReject?: () => void;
  /** V0.3.5：已决状态展示。 */
  status?: "pending" | "resolved";
  decision?: string;
  /** V0.3.9：审批终态来源（ApprovalResolvedPayload.resolved_by）。缺失传 null，
      不伪造 desktop/remote/system。 */
  resolvedBy?: string | null;
  /** V0.3.9：处理者（ApprovalResolvedPayload.actor：user|reviewer|system）。缺失 null。 */
  actor?: string | null;
  /** V0.3.9：终态原因原文（如 timeout 的「等待审批超时」）。缺失 null。 */
  resolvedReason?: string | null;
  /** V0.3.9：终态错误码（如 approval_timeout）。缺失 null。 */
  errorCode?: string | null;
  /** V0.3.9：终态时间（ApprovalResolvedPayload.resolved_at）。缺失 null。 */
  resolvedAt?: string | null;
}

const TOOL_KIND_LABELS: Record<string, string> = {
  file_write: "文件写入",
  file_delete: "文件删除",
  shell: "命令执行",
  patch: "代码补丁",
};

const DECISION_LABELS: Record<string, string> = {
  // 后端真实决策值（contract-v1 §6）：allow / allow_for_conversation / deny / timeout。
  allow: "已批准",
  allow_for_conversation: "已批准（本会话）",
  deny: "已拒绝",
  // timeout 只由服务端产生（600s 超时），不是用户决策。
  timeout: "已超时",
};

/** decision 缺失（服务端未提供）时的如实文案：不写成中性「已处理」冒充终态。 */
const DECISION_MISSING_LABEL = "已决（服务端未提供 decision）";

/**
 * V0.3.9：未知 decision 值必须展示服务端原文，不得落到中性文案。
 */
function decisionLabel(decision: string | null | undefined): string {
  if (!decision) return DECISION_MISSING_LABEL;
  return DECISION_LABELS[decision] ?? `未知决策：${decision}`;
}

const RESOLVED_BY_LABELS: Record<string, string> = {
  desktop: "桌面端",
  mobile: "手机端",
  remote: "手机端",
  system: "系统",
  reviewer: "审核者",
};

/** resolved_by 缺失保持 null 展示，不伪造处理端。 */
function resolvedByLabel(resolvedBy: string | null | undefined): string {
  if (!resolvedBy) return "来源未知";
  return RESOLVED_BY_LABELS[resolvedBy] ?? `未知来源：${resolvedBy}`;
}

const ACTOR_LABELS: Record<string, string> = {
  user: "用户",
  reviewer: "审核者",
  system: "系统",
};

function actorLabel(actor: string | null | undefined): string | null {
  if (!actor) return null;
  return ACTOR_LABELS[actor] ?? `未知处理者：${actor}`;
}

/**
 * V0.3.5 手机端审批操作卡片：
 * 展示命令、路径、摘要、理由，并提供批准/拒绝按钮。
 * 审批被另一端处理后由 store 收敛，本组件只负责渲染与回调。
 */
export function ApprovalCard({
  approval,
  conversationTitle,
  resolving = false,
  onApprove,
  onAllowForConversation,
  onReject,
  status = "pending",
  decision = "",
  resolvedBy = null,
  actor = null,
  resolvedReason = null,
  errorCode = null,
  resolvedAt = null,
}: ApprovalCardProps) {
  const { operation, reason } = approval;
  const kindLabel = TOOL_KIND_LABELS[operation.tool_kind] || operation.tool_kind;
  const isResolved = status === "resolved";
  const actorText = actorLabel(actor);

  return (
    <section
      className={`mobile-approval-card${isResolved ? " mobile-approval-resolved" : ""}`}
      data-testid="approval-card"
      aria-label={isResolved ? "已决审批操作" : "等待审批操作"}
    >
      <header className="mobile-approval-head">
        <div className="mobile-approval-title-group">
          <span className="mobile-approval-shield-icon">
            <ShieldIcon />
          </span>
          <span className="mobile-approval-title">
            {isResolved ? "已决操作" : "待审批操作"} · {kindLabel}
          </span>
        </div>
        {isResolved ? (
          <span
            className={`mobile-approval-status-badge${
              decision ? ` is-${decision}` : ""
            }`}
            data-testid="approval-status"
            data-decision={decision || "missing"}
          >
            {decisionLabel(decision)}
          </span>
        ) : null}
      </header>

      <div className="mobile-approval-body">
        {operation.summary ? (
          <p className="mobile-approval-summary">{operation.summary}</p>
        ) : null}

        {operation.command ? (
          <div className="mobile-approval-row">
            <span className="mobile-approval-label">执行命令</span>
            <code className="mobile-approval-code">{operation.command}</code>
          </div>
        ) : null}

        {operation.paths && operation.paths.length > 0 ? (
          <div className="mobile-approval-row">
            <span className="mobile-approval-label">涉及路径</span>
            <code className="mobile-approval-code">
              {operation.paths.join(", ")}
            </code>
          </div>
        ) : null}

        {operation.patch_file_count !== null && operation.patch_file_count !== undefined ? (
          <div className="mobile-approval-row">
            <span className="mobile-approval-label">变更文件</span>
            <code className="mobile-approval-code">
              {operation.patch_file_count} 个文件
            </code>
          </div>
        ) : null}

        {reason ? (
          <div className="mobile-approval-row">
            <span className="mobile-approval-label">申请理由</span>
            <p className="mobile-approval-reason">{reason}</p>
          </div>
        ) : null}

        {conversationTitle ? (
          <div className="mobile-approval-row">
            <span className="mobile-approval-label">来源聊天</span>
            <span className="mobile-approval-conv-title">{conversationTitle}</span>
          </div>
        ) : null}
      </div>

      <footer className="mobile-approval-footer">
        {isResolved ? (
          <div className="mobile-approval-resolved-block">
            <p className="mobile-approval-resolved-text" data-testid="approval-resolved-by">
              由 {resolvedByLabel(resolvedBy)} {decisionLabel(decision)}
            </p>
            {actorText ? (
              <p className="mobile-approval-resolved-meta" data-testid="approval-resolved-actor">
                处理者：{actorText}
              </p>
            ) : null}
            {resolvedReason ? (
              <p
                className="mobile-approval-resolved-meta"
                data-testid="approval-resolved-reason"
              >
                服务端说明：{resolvedReason}
              </p>
            ) : null}
            {errorCode ? (
              <p
                className="mobile-approval-resolved-meta"
                data-testid="approval-resolved-error-code"
              >
                error_code：{errorCode}
              </p>
            ) : null}
            {resolvedAt ? (
              <p className="mobile-approval-resolved-meta" data-testid="approval-resolved-at">
                终态时间：{resolvedAt}
              </p>
            ) : null}
          </div>
        ) : (
          <div className="mobile-approval-actions">
            <button
              type="button"
              className="mobile-approval-reject"
              onClick={onReject}
              disabled={resolving || !onReject}
              data-testid="approval-reject"
            >
              {resolving ? "提交中…" : "拒绝"}
            </button>
            {onAllowForConversation ? (
              <button
                type="button"
                className="mobile-approval-allow-conversation"
                onClick={onAllowForConversation}
                disabled={resolving}
                data-testid="approval-allow-conversation"
              >
                {resolving ? "提交中…" : "本会话批准"}
              </button>
            ) : null}
            <button
              type="button"
              className="mobile-approval-approve"
              onClick={onApprove}
              disabled={resolving || !onApprove}
              data-testid="approval-approve"
            >
              {resolving ? "提交中…" : "批准"}
            </button>
          </div>
        )}
      </footer>
    </section>
  );
}
