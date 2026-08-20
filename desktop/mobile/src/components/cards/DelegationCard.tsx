import { CheckIcon, ErrorIcon, SpinnerIcon, WarningIcon } from "./icons";

export type DelegationStatus = "running" | "completed" | "failed" | "cancelled";

export interface DelegationCardProps {
  delegationId?: string;
  fromName?: string;
  summary: string;
  status: DelegationStatus;
  error?: string | null;
}

const STATUS_TEXT: Record<DelegationStatus, string> = {
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function StatusIcon({ status }: { status: DelegationStatus }) {
  if (status === "running") return <SpinnerIcon />;
  if (status === "completed") return <CheckIcon />;
  if (status === "failed") return <ErrorIcon />;
  return <WarningIcon />;
}

/**
 * V0.3.3 手机端委派任务执行卡片：
 * 展示「交给助手」委派任务的实时运行、完成、失败或取消状态。
 * 失败时如实展示真实错误，不合成成功。
 */
export function DelegationCard({
  fromName = "用户",
  summary,
  status,
  error,
}: DelegationCardProps) {
  return (
    <article
      className={`mobile-delegation-card mobile-delegation-card-${status}`}
      data-testid="delegation-card"
      data-delegation-status={status}
      aria-label={`来自${fromName}的委派任务`}
    >
      <header className="mobile-delegation-head">
        <span className="mobile-delegation-origin">来自 {fromName} 的委派</span>
        <span className={`mobile-delegation-status mobile-delegation-status-${status}`}>
          <StatusIcon status={status} />
          <span>{STATUS_TEXT[status]}</span>
        </span>
      </header>

      <p className="mobile-delegation-summary">{summary}</p>

      {error ? (
        <div className="mobile-delegation-error" role="alert">
          <span className="mobile-delegation-error-label">错误详情：</span>
          <pre className="mobile-delegation-error-text">{error}</pre>
        </div>
      ) : null}
    </article>
  );
}
