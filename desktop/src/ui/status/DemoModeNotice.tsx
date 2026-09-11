import { useDesktopStore } from "../../stores/desktopStore";

/**
 * V039-S4-002 演示模式标识。
 *
 * Sidecar 通过 backend.ready 自报运行模式：{ pid, demo: boolean|null, mode_source }。
 * 只有自报 demo=true 时才标注「演示模式」——未上报（null）不等于真实模式，
 * 真实模式（false）也不需要常驻标识，界面不得替 Sidecar 下结论。
 *
 * 标识与连接状态药丸并列而不是合并：连通性与运行模式是两件事，
 * 「已连接」只说明链路在，不说明有没有调用真实模型。
 *
 * 直接订阅 store 的 backendInfo（与 DiagnosticsDrawerHost 同法），
 * 字段口径来自 store 的 BackendInfo，不改动 contracts / presenters 所属字段。
 */
export function DemoModeNotice({ variant = "badge" }: { variant?: "badge" | "detail" }) {
  const backendInfo = useDesktopStore((state) => state.backendInfo);
  if (backendInfo?.demo !== true) return null;
  const source = backendInfo.modeSource ? `（模式来源：${backendInfo.modeSource}）` : "";
  const pid = backendInfo.pid === null ? "" : `，PID ${backendInfo.pid}`;
  const explanation = `Sidecar 自报运行在演示模式${source}${pid}：不会调用真实模型。`;

  if (variant === "detail") {
    return (
      <div className="tech-drawer-row" data-testid="demo-mode-detail">
        <dt>运行模式</dt>
        <dd>演示模式{source}</dd>
      </div>
    );
  }

  return (
    <span
      className="demo-mode-badge"
      role="status"
      title={explanation}
      aria-label={explanation}
      data-testid="demo-mode-badge"
    >
      演示模式：未调用真实模型
    </span>
  );
}
