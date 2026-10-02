import { useState } from "react";
import type { AuthFailureReason, MobileConnectionState } from "../lib/wsClient";
import { useMobileStore } from "../lib/mobileStore";
import { navigate } from "../lib/router";
import { describeAuthFailure } from "./authFailureCopy";
import "./ConnectionBanner.css";

export interface ConnectionBannerProps {
  connection: MobileConnectionState;
  /** 鉴权失败原因；令牌过期与被撤销有各自文案，其余用通用文案。 */
  authFailureReason?: AuthFailureReason | null;
}

const CONNECTION_MESSAGES: Record<Exclude<MobileConnectionState, "auth_failed">, string> = {
  disconnected: "已断开与桌面端的连接",
  connecting: "正在连接桌面端…",
  connected: "",
  reconnecting: "与桌面端连接中断，正在重连…",
  unreachable: "无法连接到桌面端，请确认 Sidecar 已以 --serve 运行且网络通畅",
};

/**
 * 手机端全局连接状态条，connected 时隐藏。
 * connecting / reconnecting 用警示色，unreachable / auth_failed / disconnected 用醒目红色；
 * auth_failed 提供「重新配对」，unreachable / disconnected 提供「重试」。
 * 断连时补充说明电脑休眠、关机或 Sidecar 未运行都会表现为断连。
 */
export function ConnectionBanner({ connection, authFailureReason = null }: ConnectionBannerProps) {
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
    // 先清本地凭据再跳转：App 路由守卫按 token 存在性拦截，只 navigate 会被弹回列表页。
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
          ? describeAuthFailure(authFailureReason)
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
