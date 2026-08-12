import { StopIcon } from "../../assets/icons/icons";

export type DelegationStatus = "running" | "completed" | "failed" | "cancelled";

export interface DelegationCardView {
  delegationId: string;
  /** 委派来源显示名，例如「白厄」。 */
  fromName: string;
  /** 任务摘要。 */
  summary: string;
  status: DelegationStatus;
}

interface DelegationCardProps {
  delegation: DelegationCardView;
  onCancel?: (delegationId: string) => void;
}

const STATUS_LABEL: Record<DelegationStatus, string> = {
  running: "运行中",
  completed: "已完成",
  failed: "已失败",
  cancelled: "已取消",
};

/** 委派卡：角色区与工作台之间的视觉桥梁，标明任务从谁手里到了谁手里。 */
export function DelegationCard({ delegation, onCancel }: DelegationCardProps) {
  return (
    <article
      className={`delegation-card delegation-card-${delegation.status}`}
      aria-label={`来自${delegation.fromName}的委派`}
    >
      <header className="delegation-card-head">
        <span className="delegation-card-origin">来自 {delegation.fromName} 的委派</span>
        <span className="delegation-card-status" aria-live="polite">
          {delegation.status === "running" ? <span className="delegation-card-spinner" aria-hidden /> : null}
          {STATUS_LABEL[delegation.status]}
        </span>
      </header>
      <p className="delegation-card-summary">{delegation.summary}</p>
      {delegation.status === "running" && onCancel ? (
        <button
          type="button"
          className="delegation-card-cancel"
          onClick={() => onCancel(delegation.delegationId)}
        >
          <StopIcon />
          取消任务
        </button>
      ) : null}
    </article>
  );
}
