import { useState } from "react";
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
}

/** 工具卡片：状态色条 + mono 标题 + 可展开明细，全程静音、不进入 TTS。 */
export function ToolCard({ run }: ToolCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`tool-card tool-card-status-${run.status}`} data-tool-status={run.status}>
      <button
        type="button"
        className="tool-card-head"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        <span className={`tool-status-icon tool-status-${run.status}`}>
          <StatusIcon status={run.status} />
        </span>
        <span className="tool-title">{run.title}</span>
        <span className={`tool-status-text tool-status-${run.status}`}>
          {STATUS_TEXT[run.status]}
        </span>
        <CollapseIcon
          className="tool-chevron"
          style={{ transform: expanded ? "rotate(180deg)" : "rotate(-90deg)" }}
        />
      </button>
      {run.summary ? <div className="tool-summary">{run.summary}</div> : null}
      {expanded && run.details ? <pre className="tool-details">{run.details}</pre> : null}
    </div>
  );
}
