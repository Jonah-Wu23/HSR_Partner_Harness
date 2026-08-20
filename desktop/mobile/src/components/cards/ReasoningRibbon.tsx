import { useState } from "react";
import { ChevronDownIcon, SpinnerIcon } from "./icons";

export interface ReasoningRibbonProps {
  text: string;
  streaming?: boolean;
  elapsedSeconds?: number;
  defaultExpanded?: boolean;
}

/**
 * V0.3.3 手机端思考折叠缎带：
 * 思考段默认折叠，点击展开查看推理过程；
 * 流式进行中显示动画与实时增量；思考结束后折叠成耗时摘要。
 */
export function ReasoningRibbon({
  text,
  streaming = false,
  elapsedSeconds,
  defaultExpanded = false,
}: ReasoningRibbonProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (!streaming && !text) return null;

  const isExpanded = streaming || expanded;
  const summaryText =
    elapsedSeconds != null ? `思考了 ${elapsedSeconds} 秒` : "思考完成";

  return (
    <div
      className={`mobile-reasoning-ribbon ${streaming ? "is-streaming" : ""}`}
      data-testid="reasoning-ribbon"
      data-expanded={isExpanded}
    >
      <button
        type="button"
        className="mobile-reasoning-toggle"
        onClick={() => {
          if (!streaming) {
            setExpanded((prev) => !prev);
          }
        }}
        aria-expanded={isExpanded}
        aria-label={streaming ? "正在思考中" : `${summaryText}，点击${isExpanded ? "收起" : "展开"}`}
      >
        <span className="mobile-reasoning-indicator">
          {streaming ? (
            <SpinnerIcon />
          ) : (
            <span className="mobile-reasoning-dot" aria-hidden="true" />
          )}
        </span>

        <span className="mobile-reasoning-title">
          {streaming ? "正在思考…" : summaryText}
        </span>

        {!streaming ? (
          <>
            <span className="mobile-reasoning-action">
              {isExpanded ? "收起" : "展开"}
            </span>
            <span
              className="mobile-reasoning-chevron"
              style={{
                transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
              }}
            >
              <ChevronDownIcon />
            </span>
          </>
        ) : null}
      </button>

      {isExpanded && text ? (
        <div className="mobile-reasoning-body" data-testid="reasoning-body">
          <pre className="mobile-reasoning-text">{text}</pre>
          {streaming ? <span className="mobile-streaming-caret" aria-hidden="true" /> : null}
        </div>
      ) : null}
    </div>
  );
}
