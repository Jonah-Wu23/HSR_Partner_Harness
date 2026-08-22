import type { MobileConnectionState } from "../lib/wsClient";
import { useMobileStore } from "../lib/mobileStore";
import { navigate } from "../lib/router";
import "./ConnectionBanner.css";

export interface ConnectionBannerProps {
  connection: MobileConnectionState;
}

const CONNECTION_MESSAGES: Record<MobileConnectionState, string> = {
  disconnected: "已断开与桌面端的连接",
  connecting: "正在连接桌面端…",
  connected: "",
  reconnecting: "与桌面端连接中断，正在重连…",
  unreachable: "无法连接到桌面端，请确认 Sidecar 已以 --serve 运行且网络通畅",
  auth_failed: "配对已失效或设备已被撤销，请重新配对",
};

/**
 * V0.3.3 手机端全局连接状态条。
 *
 * 五态视觉分级：
 * - connecting / reconnecting: 警示色 (is-warn)
 * - unreachable / auth_failed / disconnected: 醒目红色 (is-down)
 * - connected: 隐藏 (null)
 *
 * 交互入口：
 * - auth_failed 提供「重新配对」按钮（跳转 #/pair）
 * - unreachable / disconnected 提供「重试」按钮（调用 store reconnect）
 */
export function ConnectionBanner({ connection }: ConnectionBannerProps) {
  if (connection === "connected") {
    return null;
  }

  const isDown =
    connection === "unreachable" ||
    connection === "auth_failed" ||
    connection === "disconnected";
  const toneClass = isDown ? "is-down" : "is-warn";

  const handleReconnect = () => {
    useMobileStore.getState().reconnect();
  };

  const handleRePair = () => {
    // 必须先清本地凭据再跳转：App 路由守卫按 token 存在性拦截，
    // 只 navigate 会被守卫立即弹回列表页（V0.3.3 真机验收发现）。
    useMobileStore.getState().disconnect();
    navigate({ name: "pair" });
  };

  return (
    <aside
      className={`conn-banner ${toneClass}`}
      role="status"
      aria-live="polite"
      data-testid="connection-banner"
      data-state={connection}
    >
      <span className="conn-banner-message">{CONNECTION_MESSAGES[connection]}</span>
      <div className="conn-banner-actions">
        {connection === "auth_failed" && (
          <button
            type="button"
            className="conn-banner-btn"
            onClick={handleRePair}
            data-testid="btn-repair"
          >
            重新配对
          </button>
        )}
        {(connection === "unreachable" || connection === "disconnected") && (
          <button
            type="button"
            className="conn-banner-btn"
            onClick={handleReconnect}
            data-testid="btn-reconnect"
          >
            重试
          </button>
        )}
      </div>
    </aside>
  );
}
