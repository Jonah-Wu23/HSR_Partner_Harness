import { useMemo, useState } from "react";

import type { HarnessActions } from "../../contracts/actions";
import { useDesktopStore } from "../../stores/desktopStore";
import { DiagnosticsDrawer } from "./DiagnosticsDrawer";
import type { DiagnosticsLoadState } from "./MetricsPanel";
import { adaptPromptAssembly, type PromptAssemblyView } from "./types";

interface DiagnosticsDrawerHostProps {
  open: boolean;
  onClose: () => void;
  /** 诊断查询与控制走 actions（metrics.query / diagnostics.prompt_assembly）。 */
  actions?: HarnessActions;
}

/**
 * V0.3.9 V03 诊断抽屉接线层：把 store 的指标/装配诊断状态适配为视觉组件 props。
 *
 * 查询状态语义（契约 §5）：
 * - metrics=null 表示「尚未读取」，[] 才是服务端返回真实零条；
 * - 查询失败把 store 中的错误原文交给抽屉展示，不吞异常、不合成成功；
 * - prompt_assembly 原始结果经视觉适配层校验结构；结构不符时把真实错误
 *   交给抽屉展示，绝不合成空数据冒充成功。
 */
export function DiagnosticsDrawerHost({ open, onClose, actions }: DiagnosticsDrawerHostProps) {
  const metrics = useDesktopStore((state) => state.turnMetrics);
  const metricsLoading = useDesktopStore((state) => state.metricsLoading);
  const metricsError = useDesktopStore((state) => state.metricsError);
  const metricsCursor = useDesktopStore((state) => state.metricsCursor);
  const assemblyRaw = useDesktopStore((state) => state.promptAssembly);
  const assemblyLoading = useDesktopStore((state) => state.promptAssemblyLoading);
  const assemblyError = useDesktopStore((state) => state.promptAssemblyError);
  // 查询是否已发起：未发起时指标传 null（未读取），查询完成（含零条）后传数组。
  const [metricsQueried, setMetricsQueried] = useState(false);
  const [assemblyQueried, setAssemblyQueried] = useState(false);

  const adapted = useMemo((): { assembly: PromptAssemblyView | null; error: string | null } => {
    if (!assemblyRaw) return { assembly: null, error: null };
    try {
      return { assembly: adaptPromptAssembly(assemblyRaw), error: null };
    } catch (error) {
      // Let It Fail：结构校验失败是真实错误，原文交给抽屉，不合成空数据。
      return {
        assembly: null,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }, [assemblyRaw]);

  const metricsState: DiagnosticsLoadState = metricsLoading
    ? "loading"
    : metricsError
      ? "failed"
      : metricsQueried
        ? "loaded"
        : "idle";
  const assemblyState: DiagnosticsLoadState = assemblyLoading
    ? "loading"
    : adapted.error ?? assemblyError
      ? "failed"
      : assemblyQueried
        ? "loaded"
        : "idle";

  const onLoadMetrics = () => {
    setMetricsQueried(true);
    void actions?.queryMetrics?.();
  };
  const onLoadMoreMetrics = () => {
    void actions?.queryMetrics?.({ cursor: metricsCursor ?? undefined });
  };
  const onLoadAssembly = () => {
    setAssemblyQueried(true);
    void actions?.queryPromptAssembly?.();
  };
  const onRequestHiddenContent = async (moduleName: string): Promise<string> => {
    if (!actions?.queryPromptAssembly) {
      throw new Error("当前环境未提供装配诊断查询能力（diagnostics.prompt_assembly）");
    }
    const view = await actions.queryPromptAssembly({ includeHidden: true });
    const module = view?.modules.find((item) => item.name === moduleName);
    return module?.hidden_content ?? "";
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
      assembly={adapted.assembly}
      assemblyState={assemblyState}
      assemblyError={assemblyError ?? adapted.error}
      onLoadAssembly={onLoadAssembly}
      onRequestHiddenContent={onRequestHiddenContent}
    />
  );
}
