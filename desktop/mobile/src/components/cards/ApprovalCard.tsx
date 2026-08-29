import type { PendingApproval } from "@shared/contracts/protocol";
import { ShieldIcon } from "./icons";

export interface ApprovalCardProps {
  approval: PendingApproval;
  conversationTitle?: string;
  /** V0.3.5：提交中状态（点击后等待服务器/事件收敛）。 */
  resolving?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
  /** V0.3.5：已决状态展示。 */
  status?: "pending" | "resolved";
  decision?: string;
  resolvedBy?: string;
}

const TOOL_KIND_LABELS: Record<string, string> = {
  file_write: "文件写入",
  file_delete: "文件删除",
  shell: "命令执行",
  patch: "代码补丁",
};

const DECISION_LABELS: Record<string, string> = {
  approve: "已批准",
  deny: "已拒绝",
};

const RESOLVED_BY_LABELS: Record<string, string> = {
  desktop: "桌面端",
  mobile: "手机端",
  remote: "手机端",
};

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
  onReject,
  status = "pending",
  decision = "approve",
  resolvedBy = "remote",
}: ApprovalCardProps) {
  const { operation, reason } = approval;
  const kindLabel = TOOL_KIND_LABELS[operation.tool_kind] || operation.tool_kind;
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
            {isResolved ? "已决操作" : "待审批操作"} · {kindLabel}
          </span>
        </div>
        {isResolved ? (
          <span className="mobile-approval-status-badge" data-testid="approval-status">
            {DECISION_LABELS[decision] || decision}
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
          <p className="mobile-approval-resolved-text" data-testid="approval-resolved-by">
            由 {RESOLVED_BY_LABELS[resolvedBy] || resolvedBy} {DECISION_LABELS[decision] || decision}
          </p>
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
