import type { ConnectionDetails, ConnectionViewStatus } from "./types";

interface TechDetailsDrawerProps {
  open: boolean;
  status: ConnectionViewStatus;
  details: ConnectionDetails;
  onClose: () => void;
  /** 逻辑线接入 app.reconnect 后提供；缺省时隐藏对应按钮。 */
  onReconnect?: () => void;
  onRestartSidecar?: () => void;
}

/** 技术详情抽屉：连接、Sidecar、日志等技术词全部收在这里。 */
export function TechDetailsDrawer({
  open,
  status,
  details,
  onClose,
  onReconnect,
  onRestartSidecar,
}: TechDetailsDrawerProps) {
  if (!open) return null;
  return (
    <div className="tech-drawer-backdrop" onClick={onClose}>
      <aside
        className="tech-drawer"
        role="dialog"
        aria-label="技术详情"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="tech-drawer-head">
          <h2>技术详情</h2>
          <button type="button" className="icon-btn" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>

        <dl className="tech-drawer-list">
          <div className="tech-drawer-row">
            <dt>连接状态</dt>
            <dd>
              {status === "connected" ? "已连接" : status === "connecting" ? "连接中" : "已断开"}
            </dd>
          </div>
          <div className="tech-drawer-row">
            <dt>本地服务（Sidecar）</dt>
            <dd>{details.sidecarStatus ?? "未知"}</dd>
          </div>
          {details.lastError ? (
            <div className="tech-drawer-row">
              <dt>最近错误</dt>
              <dd>
                <code className="tech-drawer-error">{details.lastError}</code>
              </dd>
            </div>
          ) : null}
          {details.logPath ? (
            <div className="tech-drawer-row">
              <dt>日志路径</dt>
              <dd>
                <code>{details.logPath}</code>
              </dd>
            </div>
          ) : null}
        </dl>

        <div className="tech-drawer-actions">
          {onReconnect ? (
            <button type="button" className="btn btn-secondary" onClick={onReconnect}>
              立即重连
            </button>
          ) : null}
          {onRestartSidecar ? (
            <button type="button" className="btn btn-outline" onClick={onRestartSidecar}>
              重启本地服务
            </button>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
