import type { ConnectionViewStatus } from "./types";

interface ConnectionPillProps {
  status: ConnectionViewStatus;
  /** 点击展开技术详情抽屉。 */
  onOpenDetails: () => void;
}

const LABEL: Record<ConnectionViewStatus, string> = {
  connected: "已连接",
  connecting: "连接中…",
  disconnected: "连接已断开",
};

/** 状态条连接药丸：常态几乎隐形，异常时给出人话状态，点击进技术详情。 */
export function ConnectionPill({ status, onOpenDetails }: ConnectionPillProps) {
  return (
    <button
      type="button"
      className={`connection-pill connection-pill-${status}`}
      onClick={onOpenDetails}
      aria-label={`连接状态：${LABEL[status]}，查看技术详情`}
    >
      <span className="connection-pill-dot" aria-hidden />
      <span className="connection-pill-label">{LABEL[status]}</span>
    </button>
  );
}
