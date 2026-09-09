import { useState } from "react";
import type { RemoteControlState } from "@shared/contracts/protocol";
import type { MobileConnectionState } from "../../lib/wsClient";
import { useMobileStore } from "../../lib/mobileStore";
import { LeaseStatusPanel } from "../../components/LeaseStatusPanel";
import { DeviceListPanel } from "../../components/DeviceListPanel";
import { useRemoteDevices } from "./useRemoteDevices";
import "./ConnectionDetails.css";

/**
 * V0.3.9 V06：会话列表页的「连接详情」抽屉（显式按钮打开，可关闭）。
 *
 * 内容：连接状态、远程控制租约（LeaseStatusPanel）、远程设备列表（DeviceListPanel）。
 * 移动端没有独立设置页，会话列表是常驻首页，因此把连接详情放在这里，默认收起，
 * 用户显式点开才发 remote.list_devices 只读请求。
 *
 * 呈现纪律：每个字段无数据时如实显示「尚未取得 / 未知」，不用 0 或默认值顶替；
 * 失败保留原始错误文本。
 *
 * 待真实接线：store 尚未提供 remote_control 快照、本机 device_key 与失去控制权时点，
 * 三个字段接入前保持 null（面板如实显示「尚未取得控制权状态」）。
 */

const CONNECTION_LABELS: Record<MobileConnectionState, string> = {
  connected: "已连接",
  connecting: "正在连接…",
  reconnecting: "连接中断，正在重连…",
  unreachable: "无法连接到桌面端",
  disconnected: "已断开",
  auth_failed: "配对已失效或设备已被撤销",
};

interface ConnectionStoreExtensions {
  remoteControl?: RemoteControlState | null;
  selfDeviceKey?: string | null;
  controlLostAt?: string | null;
}

export function ConnectionDetails() {
  const [open, setOpen] = useState(false);
  const connection = useMobileStore((state) => state.connection);
  const currentDeviceName = useMobileStore((state) => state.deviceName);
  const extensions = useMobileStore(
    (state) => state as unknown as ConnectionStoreExtensions,
  );
  const devices = useRemoteDevices(open);

  return (
    <section className="card connection-details" data-testid="connection-details">
      <button
        type="button"
        className="connection-details-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        data-testid="btn-toggle-connection-details"
      >
        <span>连接详情</span>
        <span className="connection-details-caret">{open ? "收起" : "展开"}</span>
      </button>

      {open ? (
        <div className="connection-details-body">
          <p className="hint" data-testid="connection-state-line">
            连接状态：{CONNECTION_LABELS[connection]}
          </p>
          <LeaseStatusPanel
            lease={extensions.remoteControl ?? null}
            selfDeviceKey={extensions.selfDeviceKey ?? null}
            controlLostAt={extensions.controlLostAt ?? null}
          />
          <DeviceListPanel
            devices={devices.devices}
            currentDeviceName={currentDeviceName}
            loading={devices.loading}
            error={devices.error}
            revokingDeviceName={devices.revokingDeviceName}
            revokeError={devices.revokeError}
            onRefresh={devices.refresh}
            onRevoke={devices.revoke}
          />
        </div>
      ) : null}
    </section>
  );
}
