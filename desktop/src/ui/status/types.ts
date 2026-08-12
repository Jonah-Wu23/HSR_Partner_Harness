/* 状态基座组件的视图类型。
   这些类型对应共享协议中的 connection.status / queue_item / error 分级，
   逻辑线落地协议后由 presenters 映射到这里的形状，组件本身不猜后端字段。 */

/** 连接状态机四态在界面上的三态表达（fatal 由 AppShell 整屏处理）。 */
export type ConnectionViewStatus = "connected" | "connecting" | "disconnected";

export interface ConnectionDetails {
  /** 最近错误的技术详情字符串（原始 1011 等），收进抽屉不上常态界面。 */
  lastError?: string | null;
  sidecarStatus?: string | null;
  logPath?: string | null;
}

export type ToastKind = "error" | "warning" | "info" | "success";

export interface ToastItem {
  id: string;
  kind: ToastKind;
  /** 人话主文案，例如「与本地服务失去连接，正在重试」。 */
  text: string;
  /** 可选技术详情入口；有点击回调时显示「查看技术详情」。 */
  hasDetails?: boolean;
}

export type QueueIntent = "followup" | "steer";

export interface QueueItemView {
  queueItemId: string;
  /** 发给谁：角色或助手。 */
  target: "character" | "assistant";
  /** 内容摘要（截断后的单行）。 */
  summary: string;
  /** 排在第几（从 1 开始）。 */
  position: number;
  /** 在等什么结束，例如「等待当前回复结束」。 */
  waitingFor: string;
  intent: QueueIntent;
}
