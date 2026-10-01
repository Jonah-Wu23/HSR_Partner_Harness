import { useState } from "react";
import type { RemoteControlState } from "@shared/contracts/protocol";
import type { MobileConnectionState } from "../../lib/wsClient";
import { useMobileStore } from "../../lib/mobileStore";
import { LeaseStatusPanel } from "../../components/LeaseStatusPanel";
import "./ConnectionDetails.css";

/**
 * 会话列表页的「连接详情」抽屉（显式按钮打开，可关闭）。
 *
 * 内容：连接状态与远程控制租约（LeaseStatusPanel）。设备列表与撤销属于桌面端
 * 控制面方法，手机连接无权调用，只在桌面端「设置 → 远程设备」管理。
 * 每个字段无数据时如实显示「尚未取得 / 未知」，不用 0 或默认值顶替。
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
  const extensions = useMobileStore(
    (state) => state as unknown as ConnectionStoreExtensions,
  );

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
        </div>
      ) : null}
    </section>
  );
}
