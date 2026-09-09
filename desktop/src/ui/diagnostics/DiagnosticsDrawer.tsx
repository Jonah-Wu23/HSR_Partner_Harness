import { useEffect, useRef, useState } from "react";

import type { TurnMetric } from "../../contracts/protocol";
import { MetricsPanel, type DiagnosticsLoadState } from "./MetricsPanel";
import { PromptAssemblyPanel } from "./PromptAssemblyPanel";
import type { PromptAssemblyView } from "./types";
import "./diagnostics.css";

export type DiagnosticsTab = "metrics" | "assembly";

export interface DiagnosticsDrawerProps {
  open: boolean;
  onClose: () => void;
  /** metrics.query 结果；null = 未读取/无数据，[] = 真实零条。 */
  metrics?: TurnMetric[] | null;
  metricsState?: DiagnosticsLoadState;
  metricsError?: string | null;
  metricsNextCursor?: string | null;
  /** 显式只读查询；打开抽屉即用户显式请求，内容组件挂载时调用一次。 */
  onLoadMetrics?: () => void;
  onLoadMoreMetrics?: () => void;
  /** diagnostics.prompt_assembly 结果（经 adaptPromptAssembly 适配）。 */
  assembly?: PromptAssemblyView | null;
  assemblyState?: DiagnosticsLoadState;
  assemblyError?: string | null;
  onLoadAssembly?: () => void;
  /** 隐藏原文：只有用户点「显示原文」才调用。 */
  onRequestHiddenContent?: (moduleName: string) => Promise<string>;
  initialTab?: DiagnosticsTab;
}

/**
 * V0.3.9 V03 桌面诊断抽屉：显式按钮打开、可关闭。
 *
 * 关闭即卸载内容组件，隐藏原文与页签等内部状态随之清除；普通聊天不渲染
 * 任何诊断或隐藏内容。数据全部由 props 注入（待真实接线：store 与 presenters
 * 提供 metrics.query / diagnostics.prompt_assembly 的结果）。
 */
export function DiagnosticsDrawer(props: DiagnosticsDrawerProps) {
  if (!props.open) return null;
  return <DiagnosticsContent {...props} />;
}

function DiagnosticsContent({
  onClose,
  metrics,
  metricsState,
  metricsError,
  metricsNextCursor,
  onLoadMetrics,
  onLoadMoreMetrics,
  assembly,
  assemblyState,
  assemblyError,
  onLoadAssembly,
  onRequestHiddenContent,
  initialTab = "metrics",
}: DiagnosticsDrawerProps) {
  const [tab, setTab] = useState<DiagnosticsTab>(initialTab);
  const loadedRef = useRef(false);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    onLoadMetrics?.();
    onLoadAssembly?.();
  }, [onLoadAssembly, onLoadMetrics]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="diag-backdrop" onClick={onClose}>
      <aside
        className="diag-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="诊断"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="diag-drawer-head">
          <h2>诊断</h2>
          <div className="diag-tabs" role="tablist" aria-label="诊断视图">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "metrics"}
              className={`diag-tab${tab === "metrics" ? " is-selected" : ""}`}
              onClick={() => setTab("metrics")}
            >
              指标
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "assembly"}
              className={`diag-tab${tab === "assembly" ? " is-selected" : ""}`}
              onClick={() => setTab("assembly")}
            >
              提示词装配
            </button>
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label="关闭诊断"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="diag-drawer-body">
          {tab === "metrics" ? (
            <MetricsPanel
              metrics={metrics}
              state={metricsState}
              error={metricsError}
              nextCursor={metricsNextCursor}
              onLoad={onLoadMetrics}
              onLoadMore={onLoadMoreMetrics}
            />
          ) : (
            <PromptAssemblyPanel
              assembly={assembly}
              state={assemblyState}
              error={assemblyError}
              onLoad={onLoadAssembly}
              onRequestHiddenContent={onRequestHiddenContent}
            />
          )}
        </div>
      </aside>
    </div>
  );
}
