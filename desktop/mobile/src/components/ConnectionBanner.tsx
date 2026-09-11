import { useState } from "react";
import type { MobileConnectionState } from "../lib/wsClient";
import { useMobileStore } from "../lib/mobileStore";
import { navigate } from "../lib/router";
import { describeAuthFailure } from "./authFailureCopy";
import "./ConnectionBanner.css";

export interface ConnectionBannerProps {
  connection: MobileConnectionState;
  /**
   * 鉴权失败细分错误码（服务端 error.code）。null = 未取得或未细分，
   * 此时回退到通用文案，不猜测「过期」还是「撤销」。
   */
  authFailureCode?: string | null;
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
 *
 * V0.3.9 V06/V08：
 * - 鉴权失败在服务端给出细分错误码时显示具体原因（凭据过期 / 设备被撤销），
 *   未给出时保持通用文案；
 * - 断连文案补一行真实可能性说明：电脑休眠、关机或 Sidecar 未运行都会表现为断连。
 *   没有真实电源状态源时不宣称电脑「正在休眠」，只说明断连本身（契约 §3）。
 */
export function ConnectionBanner({ connection, authFailureCode }: ConnectionBannerProps) {
  const [repairError, setRepairError] = useState<string | null>(null);
  const [repairing, setRepairing] = useState(false);
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

  const handleRePair = async () => {
    // 必须先清本地凭据再跳转：App 路由守卫按 token 存在性拦截，
    // 只 navigate 会被守卫立即弹回列表页（V0.3.3 真机验收发现）。
    setRepairError(null);
    setRepairing(true);
    try {
      await useMobileStore.getState().disconnect();
      navigate({ name: "pair" });
    } catch (error) {
      console.error("重新配对前释放控制权失败", error);
      setRepairError(error instanceof Error ? error.message : String(error));
    } finally {
      setRepairing(false);
    }
  };

  return (
    <aside
      className={`conn-banner ${toneClass}`}
      role="status"
      aria-live="polite"
      data-testid="connection-banner"
      data-state={connection}
    >
      <span className="conn-banner-message">
        {connection === "auth_failed"
          ? (describeAuthFailure(authFailureCode) ?? CONNECTION_MESSAGES.auth_failed)
          : CONNECTION_MESSAGES[connection]}
      </span>
      {connection === "unreachable" || connection === "disconnected" ? (
        <span className="conn-banner-hint" data-testid="conn-banner-hint">
          电脑休眠、关机或 Sidecar 未运行时也会表现为断连。
        </span>
      ) : null}
      {repairError && <span role="alert">{repairError}</span>}
      <div className="conn-banner-actions">
        {connection === "auth_failed" && (
          <button
            type="button"
            className="conn-banner-btn"
            onClick={handleRePair}
            disabled={repairing}
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
