import type { MobileConnectionState } from "../lib/wsClient";
import { formatLocalDateTime } from "./formatTime";
import "./ChatStatusHint.css";

/**
 * V0.3.9 V06：聊天页页内连接/租约提示条。
 *
 * 与全局 ConnectionBanner 的分工：ConnectionBanner 在应用顶部常驻，负责全局连接态与
 * 重试/重新配对入口；本组件在聊天页内提供就地提示，避免用户正在读长聊天时看不到状态变化：
 * - 连接非 connected：就地说明当前连接状态；
 * - resyncing：快照/事件重放未完成时的「正在重新同步」提示（连接可能已建立）；
 * - leaseLostAt：本机失去电脑控制权的轻提示（真实事实驱动，不猜测）。
 *
 * 无任何需要提示的事实时返回 null；不渲染空状态、不伪造指标。
 *
 * 挂载点：ChatPage（desktop/mobile/src/pages/chat/ChatPage.tsx，归 V-C）——
 * 建议放在 .mobile-chat-header 之后、.mobile-chat-scroll 之前：
 *   <ChatStatusHint connection={connection} resyncing={!bootstrapped && isConnected} leaseLostAt={controlLostAt} />
 * 其中 remote_control 快照与 controlLostAt 需 store 提供（见交付报告跨轨需求）。
 */

const CONNECTION_HINTS: Record<MobileConnectionState, string> = {
  connected: "",
  connecting: "正在连接桌面端…",
  reconnecting: "与桌面端连接中断，正在重连…",
  unreachable: "无法连接到桌面端，正在重试…",
  disconnected: "已断开与桌面端的连接",
  auth_failed: "配对已失效或设备已被撤销，请重新配对",
};

export interface ChatStatusHintProps {
  connection: MobileConnectionState;
  /** 连接已建立但快照/事件重放尚未完成。 */
  resyncing: boolean;
  /** 本机失去控制权的真实时点（ISO）；无此事实为 null。 */
  leaseLostAt: string | null;
  /** 是否在页内重复展示连接状态（默认 true；接线方按需关闭以免与顶部横幅重复）。 */
  showConnection?: boolean;
}

export function ChatStatusHint({
  connection,
  resyncing,
  leaseLostAt,
  showConnection = true,
}: ChatStatusHintProps) {
  const connectionText = CONNECTION_HINTS[connection];
  const showConnLine = showConnection && connection !== "connected" && connectionText !== "";
  const lostText = formatLocalDateTime(leaseLostAt);

  if (!showConnLine && !resyncing && !lostText) {
    return null;
  }

  return (
    <aside
      className="chat-status-hint"
      role="status"
      aria-live="polite"
      data-testid="chat-status-hint"
    >
      {showConnLine ? (
        <span
          className={`chat-status-line is-${connection}`}
          data-testid="chat-status-connection"
        >
          {connectionText}
        </span>
      ) : null}
      {resyncing ? (
        <span className="chat-status-line is-resync" data-testid="chat-status-resync">
          正在重新同步…
        </span>
      ) : null}
      {lostText ? (
        <span className="chat-status-line is-lease-lost" data-testid="chat-status-lease-lost">
          已失去对电脑的控制权（{lostText}）
        </span>
      ) : null}
    </aside>
  );
}
