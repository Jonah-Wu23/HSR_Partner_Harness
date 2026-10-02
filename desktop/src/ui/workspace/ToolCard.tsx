import type { ToolRun, ToolRunStatus } from "../../contracts/protocol";
import { CheckIcon, CollapseIcon, ErrorIcon, RefreshIcon, WarningIcon } from "../../assets/icons/icons";

const STATUS_TEXT: Record<ToolRunStatus, string> = {
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  denied: "已否决",
};

function StatusIcon({ status }: { status: ToolRunStatus }) {
  if (status === "running") return <RefreshIcon className="ph-spin" />;
  if (status === "succeeded") return <CheckIcon />;
  if (status === "failed") return <ErrorIcon />;
  return <WarningIcon />;
}

interface ToolCardProps {
  run: ToolRun;
  /** 展开状态由时间线按条目保存，行被虚拟列表回收后再出现时保持原状。 */
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
}

/** 工具卡片：状态色条 + mono 标题 + 可展开明细，全程静音、不进入 TTS。 */
export function ToolCard({ run, expanded, onExpandedChange }: ToolCardProps) {
  const hasCommand = Boolean(run.title || run.details);

  return (
    <div className={`tool-card tool-card-status-${run.status}`} data-tool-status={run.status}>
      <button
        type="button"
        className="tool-card-head"
        onClick={() => onExpandedChange(!expanded)}
        aria-expanded={expanded}
      >
        <span className={`tool-status-icon tool-status-${run.status}`}>
          <StatusIcon status={run.status} />
        </span>
        <span className="tool-title">工具调用</span>
        <span className={`tool-status-text tool-status-${run.status}`}>
          {STATUS_TEXT[run.status]}
        </span>
        <CollapseIcon
          className="tool-chevron"
          style={{ transform: expanded ? "rotate(180deg)" : "rotate(-90deg)" }}
        />
      </button>
      {expanded && hasCommand ? (
        <div className="tool-expanded-body">
          {run.title ? (
            <div className="tool-command">
              <span className="tool-detail-label">命令</span>
              <pre>{run.title}</pre>
            </div>
          ) : null}
          {run.details ? (
            <div className="tool-result">
              <span className="tool-detail-label">执行结果</span>
              <pre className="tool-details">{run.details}</pre>
            </div>
          ) : null}
          {run.summary && run.summary !== run.details ? (
            <div className="tool-result">
              <span className="tool-detail-label">状态说明</span>
              <pre className="tool-details">{run.summary}</pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
