import type { RemoteControlState } from "@shared/contracts/protocol";
import { formatLocalDateTime } from "./formatTime";
import "./LeaseStatusPanel.css";

/**
 * 远程控制租约面板。租约按 device_key 独立记录，TTL 45s、断连宽限 15s、最晚 60s 回收；
 * remote_control 快照与 remote.control_changed 事件提供各字段，无值的字段显示「未知」。
 */

const STATE_LABELS: Record<RemoteControlState["state"], string> = {
  free: "空闲：没有设备持有控制权",
  held: "已由设备持有控制权",
  grace: "宽限期：断连后暂未回收控制权",
};

export interface LeaseStatusPanelProps {
  /** remote_control 快照或 remote.control_changed 状态；null 表示首次同步前。 */
  lease: RemoteControlState | null;
}

function deviceText(lease: RemoteControlState): string {
  if (lease.state === "free") return "—";
  return lease.device_key ?? "未知（服务端未提供 device_key）";
}

export function LeaseStatusPanel({ lease }: LeaseStatusPanelProps) {
  return (
    <section
      className="card lease-panel"
      aria-label="远程控制权"
      data-testid="lease-status-panel"
    >
      <h3 className="lease-panel-title">远程控制权</h3>

      {lease === null ? (
        <p className="hint" data-testid="lease-unknown">
          尚未取得控制权状态：等待 remote_control 快照或 remote.control_changed 事件。
        </p>
      ) : (
        <>
          <p
            className={`lease-state lease-status-${lease.state}`}
            data-testid="lease-state"
            data-state={lease.state}
          >
            {STATE_LABELS[lease.state]}
          </p>
          <dl className="lease-detail">
            <div className="lease-row">
              <dt>持有设备</dt>
              <dd data-testid="lease-device">{deviceText(lease)}</dd>
            </div>
            <div className="lease-row">
              <dt>到期时间</dt>
              <dd data-testid="lease-expires">
                {formatLocalDateTime(lease.expires_at) ?? "未知"}
              </dd>
            </div>
            {lease.state === "grace" ? (
              <div className="lease-row">
                <dt>宽限期结束</dt>
                <dd data-testid="lease-grace-expires">
                  {formatLocalDateTime(lease.grace_expires_at) ?? "未知"}
                </dd>
              </div>
            ) : null}
            <div className="lease-row">
              <dt>原因</dt>
              <dd data-testid="lease-reason">{lease.reason ?? "未知"}</dd>
            </div>
          </dl>
          {lease.state !== "free" ? (
            <p className="hint" data-testid="lease-self-unknown">
              持有设备显示的是服务端连接标识，手机端无法判断它是否为本机。
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
