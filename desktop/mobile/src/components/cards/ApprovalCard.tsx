import type { PendingApproval } from "@shared/contracts/protocol";
import { ShieldIcon } from "./icons";

export interface ApprovalCardProps {
  approval: PendingApproval;
  conversationTitle?: string;
}

const TOOL_KIND_LABELS: Record<string, string> = {
  file_write: "文件写入",
  file_delete: "文件删除",
  shell: "命令执行",
  patch: "代码补丁",
};

/**
 * V0.3.3 手机端等待审批只读卡片：
 * 审批在手机端只读可见（展示命令、路径、摘要、理由）；
 * 明确标注「请在电脑端处理」——本阶段手机端不应答，UI 中严禁出现批准/拒绝按钮。
 */
export function ApprovalCard({ approval, conversationTitle }: ApprovalCardProps) {
  const { operation, reason } = approval;
  const kindLabel = TOOL_KIND_LABELS[operation.tool_kind] || operation.tool_kind;

  return (
    <section
      className="mobile-approval-card"
      data-testid="approval-card"
      aria-label="等待审批操作（只读）"
    >
      <header className="mobile-approval-head">
        <div className="mobile-approval-title-group">
          <span className="mobile-approval-shield-icon">
            <ShieldIcon />
          </span>
          <span className="mobile-approval-title">
            待审批操作 · {kindLabel}
          </span>
        </div>
        <span className="mobile-approval-readonly-badge">
          请在电脑端处理
        </span>
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
        <span className="mobile-approval-hint">
          手机端当前仅支持查看审批详情。为确保操作安全，请在电脑端完成批准或否决。
        </span>
      </footer>
    </section>
  );
}
