import type { ApprovalResolvedPayload, PendingApproval } from "@shared/contracts/protocol";
import { ShieldIcon } from "./icons";

/** 卡片展示所需的审批字段；已决审批在本端没见过申请时 operation 为 null。 */
export interface ApprovalCardApproval {
  approval_id: string;
  operation: PendingApproval["operation"] | null;
  /** 申请理由。 */
  reason: string;
}

export interface ApprovalCardProps {
  approval: ApprovalCardApproval;
  conversationTitle?: string;
  /** 提交中（点击后等待服务端响应或事件收敛）。 */
  resolving?: boolean;
  onApprove?: () => void;
  /** 仅本会话内生效的批准（allow_for_conversation）。 */
  onAllowForConversation?: () => void;
  onReject?: () => void;
  status?: "pending" | "resolved";
  /** 以下为已决卡片的终态字段，取自 approval.resolved 载荷。 */
  decision?: ApprovalResolvedPayload["decision"];
  resolvedBy?: ApprovalResolvedPayload["resolved_by"];
  actor?: ApprovalResolvedPayload["actor"];
  /** 终态原因（如「等待审批超时」）；用户裁决时为 null。 */
  resolutionReason?: ApprovalResolvedPayload["resolution_reason"];
  errorCode?: ApprovalResolvedPayload["error_code"];
  resolvedAt?: string | null;
}

const TOOL_KIND_LABELS: Record<PendingApproval["operation"]["tool_kind"], string> = {
  file_write: "文件写入",
  file_delete: "文件删除",
  shell: "命令执行",
  patch: "代码补丁",
};

const DECISION_LABELS: Record<ApprovalResolvedPayload["decision"], string> = {
  allow: "已批准",
  allow_for_conversation: "已批准（本会话）",
  deny: "已拒绝",
  // timeout 只由服务端产生（等待审批超时）。
  timeout: "已超时",
};

const RESOLVED_BY_LABELS: Record<NonNullable<ApprovalResolvedPayload["resolved_by"]>, string> = {
  desktop: "桌面端",
  remote: "手机端",
  system: "系统",
};

const ACTOR_LABELS: Record<ApprovalResolvedPayload["actor"], string> = {
  user: "用户",
  reviewer: "审核者",
  system: "系统",
};

/**
 * 手机端审批卡片：展示命令、路径、摘要与申请理由，待审批时提供批准与拒绝。
 * 已决卡另行展示处理端、处理者、终态原因、错误码与时间；
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
  decision,
  resolvedBy = null,
  actor,
  resolutionReason = null,
  errorCode = null,
  resolvedAt = null,
}: ApprovalCardProps) {
  const { operation, reason } = approval;
  const kindLabel = operation ? TOOL_KIND_LABELS[operation.tool_kind] : null;
  const decisionText = decision ? DECISION_LABELS[decision] : null;
  const isResolved = status === "resolved";

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
            {isResolved ? "已决操作" : "待审批操作"}
            {kindLabel ? ` · ${kindLabel}` : null}
          </span>
        </div>
        {isResolved ? (
          <span
            className={`mobile-approval-status-badge is-${decision}`}
            data-testid="approval-status"
            data-decision={decision}
          >
            {decisionText}
          </span>
        ) : null}
      </header>

      <div className="mobile-approval-body">
        {operation?.summary ? (
          <p className="mobile-approval-summary">{operation.summary}</p>
        ) : null}

        {operation?.command ? (
          <div className="mobile-approval-row">
            <span className="mobile-approval-label">执行命令</span>
            <code className="mobile-approval-code">{operation.command}</code>
          </div>
        ) : null}

        {operation?.paths && operation.paths.length > 0 ? (
          <div className="mobile-approval-row">
            <span className="mobile-approval-label">涉及路径</span>
            <code className="mobile-approval-code">
              {operation.paths.join(", ")}
            </code>
          </div>
        ) : null}

        {operation && operation.patch_file_count !== null ? (
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
              {/* 审查智能体裁决时没有处理端，处理者见下一行。 */}
              {resolvedBy ? `由 ${RESOLVED_BY_LABELS[resolvedBy]} ${decisionText}` : decisionText}
            </p>
            {actor ? (
              <p className="mobile-approval-resolved-meta" data-testid="approval-resolved-actor">
                处理者：{ACTOR_LABELS[actor]}
              </p>
            ) : null}
            {resolutionReason ? (
              <p
                className="mobile-approval-resolved-meta"
                data-testid="approval-resolved-reason"
              >
                服务端说明：{resolutionReason}
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
