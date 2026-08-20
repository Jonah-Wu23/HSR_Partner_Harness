import { useState } from "react";
import type { ToolRun, ToolRunStatus } from "@shared/contracts/protocol";
import {
  CheckIcon,
  ChevronDownIcon,
  ErrorIcon,
  SpinnerIcon,
  WarningIcon,
} from "./icons";

const STATUS_TEXT: Record<ToolRunStatus, string> = {
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  denied: "已否决",
};

function StatusIcon({ status }: { status: ToolRunStatus }) {
  if (status === "running") return <SpinnerIcon />;
  if (status === "succeeded") return <CheckIcon />;
  if (status === "failed") return <ErrorIcon />;
  return <WarningIcon />;
}

export interface ToolCardProps {
  run: ToolRun;
  defaultExpanded?: boolean;
}

/**
 * V0.3.3 手机端结构化工具事件卡片：
 * 状态色条 + 状态指示 + 可展开折叠的命令与执行结果明细。
 * 手机端保持静音、不提供 TTS 入口。
 */
export function ToolCard({ run, defaultExpanded = false }: ToolCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const hasDetails = Boolean(run.title || run.details || run.summary);
  const displayTitle = "工具调用";

  return (
    <div
      className={`mobile-tool-card mobile-tool-card-${run.status}`}
      data-testid="tool-card"
      data-tool-status={run.status}
    >
      <button
        type="button"
        className="mobile-tool-card-head"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        aria-label={`${displayTitle}：${STATUS_TEXT[run.status]}`}
      >
        <span className={`mobile-tool-icon mobile-tool-icon-${run.status}`}>
          <StatusIcon status={run.status} />
        </span>
        <span className="mobile-tool-title">{displayTitle}</span>
        <span className={`mobile-tool-status-text mobile-tool-status-${run.status}`}>
          {STATUS_TEXT[run.status]}
        </span>
        <span
          className="mobile-tool-chevron"
          style={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}
        >
          <ChevronDownIcon />
        </span>
      </button>

      {expanded && hasDetails ? (
        <div className="mobile-tool-body">
          {run.title ? (
            <div className="mobile-tool-section">
              <span className="mobile-tool-label">执行命令</span>
              <pre className="mobile-tool-pre">{run.title}</pre>
            </div>
          ) : null}

          {run.summary && run.summary !== run.details ? (
            <div className="mobile-tool-section">
              <span className="mobile-tool-label">状态说明</span>
              <pre className="mobile-tool-pre">{run.summary}</pre>
            </div>
          ) : null}

          {run.details ? (
            <div className="mobile-tool-section">
              <span className="mobile-tool-label">执行输出</span>
              <pre className="mobile-tool-pre">{run.details}</pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
