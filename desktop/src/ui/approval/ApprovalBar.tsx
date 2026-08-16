import { useState } from "react";
import type { HarnessActions } from "../../contracts/actions";
import type { ApprovalViewModel } from "../../contracts/view-models";

interface ApprovalBarProps {
  approval: ApprovalViewModel;
  actions: HarnessActions;
}

/** 审批条：请求批准三选一；帮我审核展示审查结论；完全允许不渲染。 */
export function ApprovalBar({ approval, actions }: ApprovalBarProps) {
  // M1.5：不再用组件内 resolvedIds 长期隐藏审批；渲染完全来自 store 的
  // pending/resolving 状态。errors 只保存请求失败的可见提示。
  const [errors, setErrors] = useState<Record<string, string>>({});

  if (approval.mode === "full_auto") return null;

  const resolve = async (approvalId: string, decision: string) => {
    setErrors((prev) => {
      const { [approvalId]: _removed, ...rest } = prev;
      return rest;
    });
    try {
      await actions.resolveApproval(approvalId, decision);
    } catch (error) {
      // 请求失败：store 的 setApprovalResolving(false) 已恢复按钮，
      // 这里保留可见错误，审批条不会消失。
      setErrors((prev) => ({
        ...prev,
        [approvalId]: error instanceof Error ? error.message : String(error),
      }));
    }
  };

  const pending = approval.pending[0];

  if (approval.mode === "review") {
    // V0.2 问题 14：只有审查智能体真正被调用（reviewActive）或存在待审
    // 操作时才显示审查状态；低风险直接放行、空闲与普通回复不显示。
    if (!approval.reviewActive && !pending) return null;
    const error = pending ? errors[pending.approval_id] : undefined;
    return (
      <div className="approval-bar" data-testid="approval-bar" aria-live="polite">
        <div className={`approval-review ${approval.reviewText ? "" : "approval-review-pending"}`}>
          {approval.reviewText ?? "审查智能体正在评估高风险操作…"}
        </div>
        {pending ? (
          <>
            <div className="approval-actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={pending.resolving}
                onClick={() => resolve(pending.approval_id, "allow")}
              >
                {pending.resolving ? "处理中…" : "仍然允许"}
              </button>
              <button
                type="button"
                className="btn btn-danger-outline"
                disabled={pending.resolving}
                onClick={() => resolve(pending.approval_id, "deny")}
              >
                {pending.resolving ? "处理中…" : "否决"}
              </button>
            </div>
            {error ? <div className="approval-error" role="alert">{error}</div> : null}
          </>
        ) : null}
      </div>
    );
  }

  if (!pending) return null;

  const { operation } = pending;
  const error = errors[pending.approval_id];
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
          disabled={pending.resolving}
          onClick={() => resolve(pending.approval_id, "allow")}
        >
          {pending.resolving ? "处理中…" : "允许"}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={pending.resolving}
          onClick={() => resolve(pending.approval_id, "allow_for_conversation")}
        >
          {pending.resolving ? "处理中…" : "本对话内允许"}
        </button>
        <button
          type="button"
          className="btn btn-danger-outline"
          disabled={pending.resolving}
          onClick={() => resolve(pending.approval_id, "deny")}
        >
          {pending.resolving ? "处理中…" : "否决"}
        </button>
      </div>
      {error ? <div className="approval-error" role="alert">{error}</div> : null}
    </div>
  );
}
