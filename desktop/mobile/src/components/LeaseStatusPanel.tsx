import type { RemoteControlState } from "@shared/contracts/protocol";
import { formatLocalDateTime } from "./formatTime";
import "./LeaseStatusPanel.css";

/**
 * V0.3.9 V06：远程控制租约面板（契约 §6）。
 *
 * 契约口径：租约按 device_key 独立记录，TTL 45s、断连宽限 15s、最晚 60s 回收；
 * `remote_control` 快照与 `remote.control_changed` 事件提供
 * state / device_key / expires_at / grace_expires_at / reason，无值使用 null。
 *
 * 呈现纪律：
 * - lease === null 表示「尚未取得快照」→ 如实说明，不显示任何伪造的 free/held 状态；
 * - 每个字段 null 显示「未知」，不填默认值；
 * - 是否「本机持有」只在 selfDeviceKey 已知且与 device_key 相等时判定；selfDeviceKey 为 null
 *   时如实展示服务端给的 device_key 原文，不猜是不是自己；
 * - controlLostAt 只由「本机曾持有控制权、现已失去」的真实事实驱动（store 派生），
 *   组件不按 state 变化或文案关键词猜测丢失。
 *
 * 待真实接线：mobileStore 尚未提供 remote_control 快照与 remote.control_changed 消费，
 * 也尚未提供本机 device_key / 失去控制权时点；接入前本面板如实显示「尚未取得控制权状态」。
 */

const STATE_LABELS: Record<RemoteControlState["state"], string> = {
  free: "空闲：没有设备持有控制权",
  held: "已由设备持有控制权",
  grace: "宽限期：断连后暂未回收控制权",
};

export interface LeaseStatusPanelProps {
  /** remote_control 快照或 remote.control_changed 状态；null = 尚未取得。 */
  lease: RemoteControlState | null;
  /** 本机 device_key（服务端鉴权身份）；未知为 null。 */
  selfDeviceKey: string | null;
  /** 本机曾持有控制权、现已失去的真实时点（ISO）；无此事实为 null。 */
  controlLostAt: string | null;
}

function deviceText(lease: RemoteControlState, selfDeviceKey: string | null): string {
  if (lease.state === "free") return "—";
  if (lease.device_key === null) return "未知（服务端未提供 device_key）";
  if (selfDeviceKey !== null && lease.device_key === selfDeviceKey) return "本机";
  return lease.device_key;
}

export function LeaseStatusPanel({
  lease,
  selfDeviceKey,
  controlLostAt,
}: LeaseStatusPanelProps) {
  const lostText = formatLocalDateTime(controlLostAt);

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
              <dd data-testid="lease-device">{deviceText(lease, selfDeviceKey)}</dd>
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
          {lease.state !== "free" && selfDeviceKey === null ? (
            <p className="hint" data-testid="lease-self-unknown">
              本机设备标识尚未取得，无法判断持有者是否为本机。
            </p>
          ) : null}
        </>
      )}

      {lostText ? (
        <p className="lease-lost" role="status" data-testid="lease-lost-hint">
          已失去对电脑的控制权（{lostText}）
        </p>
      ) : null}
    </section>
  );
}
