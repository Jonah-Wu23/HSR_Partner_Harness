import { useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { ApprovalViewModel } from "../../contracts/view-models";

interface ApprovalBarProps {
  approval: ApprovalViewModel;
  actions: HarnessActions;
}

/** 审批条：请求批准三选一；帮我审核展示审查结论；完全允许不渲染。 */
export function ApprovalBar({ approval, actions }: ApprovalBarProps) {
  const [resolvedIds, setResolvedIds] = useState<Set<string>>(new Set());

  if (approval.mode === "full_auto") return null;

  const resolve = (approvalId: string, decision: string) => {
    setResolvedIds((prev) => new Set(prev).add(approvalId));
    void actions.resolveApproval(approvalId, decision);
  };

  const pending = approval.pending.find((item) => !resolvedIds.has(item.approval_id));

  if (approval.mode === "review") {
    return (
      <div className="approval-bar" data-testid="approval-bar" aria-live="polite">
        <div className={`approval-review ${approval.reviewText ? "" : "approval-review-pending"}`}>
          {approval.reviewText ?? "审查智能体正在评估高风险操作…"}
        </div>
        {pending ? (
          <div className="approval-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => resolve(pending.approval_id, "allow")}
            >
              仍然允许
            </button>
            <button
              type="button"
              className="btn btn-danger-outline"
              onClick={() => resolve(pending.approval_id, "deny")}
            >
              否决
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  if (!pending) return null;

  const { operation } = pending;
  return (
    <div className="approval-bar" data-testid="approval-bar" aria-live="polite">
      <div className="approval-summary">
        {operation.summary || "待审批操作"}
        {operation.command ? <code>{operation.command}</code> : null}
        {operation.paths.length > 0 ? <code>{operation.paths.join(", ")}</code> : null}
        {operation.patch_file_count !== null ? <code>{operation.patch_file_count} 个文件</code> : null}
      </div>
      {pending.reason ? <div className="approval-reason">{pending.reason}</div> : null}
      <div className="approval-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => resolve(pending.approval_id, "allow")}
        >
          允许
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => resolve(pending.approval_id, "allow_for_conversation")}
        >
          本对话内允许
        </button>
        <button
          type="button"
          className="btn btn-danger-outline"
          onClick={() => resolve(pending.approval_id, "deny")}
        >
          否决
        </button>
      </div>
    </div>
  );
}
