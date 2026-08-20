import type { MobileConnectionState } from "../lib/wsClient";

const CONNECTION_LABEL: Record<MobileConnectionState, string> = {
  disconnected: "未连接",
  connecting: "连接中…",
  connected: "已连接",
  reconnecting: "连接中断，重连中…",
  unreachable: "无法到达桌面端，请确认 Sidecar 已以 --serve 运行",
  auth_failed: "配对已失效，请重新配对",
};

/**
 * V0.3.3 手机端全局连接状态条（骨架占位实现，由 W4 填充五态视觉与交互）。
 *
 * TODO(W4)：五态（未连接/已连接/重连中/鉴权失败/电脑离线）视觉分级；
 * 鉴权失败给"重新配对"入口（navigate 到 #/pair）；断线必须醒目如实呈现，
 * 严禁弱化成空闲态；connected 态可收起。数据只能来自 useMobileStore 的
 * connection 字段，不得自行探测。
 */
export function ConnectionBanner(props: { connection: MobileConnectionState }) {
  if (props.connection === "connected") return null;
  const tone =
    props.connection === "unreachable" || props.connection === "auth_failed"
      ? "is-down"
      : "is-warn";
  return (
    <div className={`conn-banner ${tone}`} role="status">
      {CONNECTION_LABEL[props.connection]}
    </div>
  );
}
