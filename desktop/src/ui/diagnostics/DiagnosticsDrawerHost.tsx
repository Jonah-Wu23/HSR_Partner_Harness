import { useState } from "react";

import type { HarnessActions } from "../../contracts/actions";
import { useDesktopStore } from "../../stores/desktopStore";
import { DiagnosticsDrawer } from "./DiagnosticsDrawer";
import type { DiagnosticsLoadState } from "./MetricsPanel";

interface DiagnosticsDrawerHostProps {
  open: boolean;
  onClose: () => void;
  /** 诊断查询走 metrics.query 与 diagnostics.prompt_assembly。 */
  actions: HarnessActions;
}

/**
 * 诊断抽屉接线层：把 store 的指标与装配诊断状态交给视觉组件。
 *
 * metrics 为 null 表示尚未读取，[] 是服务端返回的零条；查询失败把错误原文交给抽屉。
 * 装配结果在 actions 层已按协议校验，结构不符时同样以错误原文呈现。
 */
export function DiagnosticsDrawerHost({ open, onClose, actions }: DiagnosticsDrawerHostProps) {
  const metrics = useDesktopStore((state) => state.turnMetrics);
  const metricsLoading = useDesktopStore((state) => state.metricsLoading);
  const metricsError = useDesktopStore((state) => state.metricsError);
  const metricsCursor = useDesktopStore((state) => state.metricsCursor);
  const assembly = useDesktopStore((state) => state.promptAssembly);
  const assemblyLoading = useDesktopStore((state) => state.promptAssemblyLoading);
  const assemblyError = useDesktopStore((state) => state.promptAssemblyError);
  // 未发起查询时指标传 null，查询完成（含零条）后传数组。
  const [metricsQueried, setMetricsQueried] = useState(false);
  const [assemblyQueried, setAssemblyQueried] = useState(false);

  const metricsState: DiagnosticsLoadState = metricsLoading
    ? "loading"
    : metricsError
      ? "failed"
      : metricsQueried
        ? "loaded"
        : "idle";
  const assemblyState: DiagnosticsLoadState = assemblyLoading
    ? "loading"
    : assemblyError
      ? "failed"
      : assemblyQueried
        ? "loaded"
        : "idle";

  const onLoadMetrics = () => {
    setMetricsQueried(true);
    void actions.queryMetrics();
  };
  const onLoadMoreMetrics = () => {
    void actions.queryMetrics({ cursor: metricsCursor ?? undefined });
  };
  const onLoadAssembly = () => {
    setAssemblyQueried(true);
    void actions.queryPromptAssembly();
  };
  const onRequestHiddenContent = async (moduleName: string): Promise<string> => {
    const view = await actions.queryPromptAssembly({ includeHidden: true });
    const module = view.modules.find((item) => item.name === moduleName);
    if (!module) throw new Error(`装配结果中没有模块「${moduleName}」`);
    if (module.hidden_content === null) {
      throw new Error(`服务端没有返回模块「${moduleName}」的隐藏原文`);
    }
    return module.hidden_content;
  };

  return (
    <DiagnosticsDrawer
      open={open}
      onClose={onClose}
      metrics={metricsQueried ? metrics : null}
      metricsState={metricsState}
      metricsError={metricsError}
      metricsNextCursor={metricsCursor}
      onLoadMetrics={onLoadMetrics}
      onLoadMoreMetrics={onLoadMoreMetrics}
      assembly={assembly}
      assemblyState={assemblyState}
      assemblyError={assemblyError}
      onLoadAssembly={onLoadAssembly}
      onRequestHiddenContent={onRequestHiddenContent}
    />
  );
}
