import type {
  DesktopCommand,
  DesktopEvent,
  DesktopResponse,
} from "../contracts/protocol";

export interface DesktopBackend {
  request<T>(command: DesktopCommand): Promise<T>;
  /** 打开独立聊天窗口；非 Tauri 后端应明确报告不支持，不伪造成功。 */
  openChatWindow(conversationId: string, projectId: string, title: string): Promise<string>;
  pickFolder(title?: string): Promise<string | null>;
  subscribe(listener: (event: DesktopEvent) => void): () => void;
  /** 强制重连本地服务；Sidecar 断开时无法走 JSONL 请求，直接触达 Rust 命令。 */
  reconnectSidecar(): Promise<void>;
}

export function unwrapResponse<T>(response: DesktopResponse<T>): T {
  if (!response.ok) {
    throw new Error(response.error?.message ?? "桌面后端请求失败");
  }
  return response.result as T;
}

/**
 * 请求 id 生成器：V0.3.2 M5 起为全应用唯一 `{viewId}:{uuid}`。
 * 多窗口各自从 1 递增会在 Rust pending map 中互相覆盖，必须携带窗口级 viewId。
 */
export class RequestIdFactory {
  constructor(private readonly viewIdProvider: () => string = () => "desktop") {}

  next(): string {
    const viewId = this.viewIdProvider() || "desktop";
    const unique =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    return `${viewId}:${unique}`;
  }
}
