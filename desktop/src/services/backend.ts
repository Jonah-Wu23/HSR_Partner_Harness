import type {
  DesktopCommand,
  DesktopResponse,
  DesktopStreamEvent,
} from "../contracts/protocol";

export interface FileFilter {
  name: string;
  extensions: string[];
}

/** 普通请求等待 Sidecar 回复的秒数上限。 */
export const DEFAULT_REQUEST_TIMEOUT_SECS = 30;

export interface DesktopBackend {
  /** timeoutSecs 缺省为 DEFAULT_REQUEST_TIMEOUT_SECS；null 表示一直等到 Sidecar 回复或断开。 */
  request<T>(command: DesktopCommand, timeoutSecs?: number | null): Promise<T>;
  /** 打开独立聊天窗口；非 Tauri 后端如实报告不支持。 */
  openChatWindow(conversationId: string, title: string): Promise<string>;
  pickFolder(title?: string): Promise<string | null>;
  /** 选择单个本地文件（角色卡 JSON、头像、参考音频等）。 */
  pickFile(options?: { title?: string; filters?: FileFilter[] }): Promise<string | null>;
  /** 选择保存路径（角色卡导出等）。 */
  saveFile(options?: { title?: string; defaultPath?: string; filters?: FileFilter[] }): Promise<string | null>;
  subscribe(listener: (event: DesktopStreamEvent) => void): () => void;
  /** 强制重连本地服务；Sidecar 断开时无法走 JSONL 请求，直接调用 Rust 命令。 */
  reconnectSidecar(): Promise<void>;
}

/** Sidecar 返回 ok=false 时抛出，保留协议错误码与详情。 */
export class DesktopRequestError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown> | undefined;

  constructor(code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "DesktopRequestError";
    this.code = code;
    this.details = details;
  }
}

export function unwrapResponse<T>(response: DesktopResponse<T>): T {
  if (!response.ok) {
    const error = response.error!;
    throw new DesktopRequestError(error.code, error.message, error.details);
  }
  return response.result as T;
}

/** 请求 id 为全应用唯一的 `{viewId}:{uuid}`，多窗口的请求在 Rust pending map 中互不覆盖。 */
export class RequestIdFactory {
  constructor(private readonly viewIdProvider: () => string = () => "desktop") {}

  next(): string {
    return `${this.viewIdProvider()}:${crypto.randomUUID()}`;
  }
}
