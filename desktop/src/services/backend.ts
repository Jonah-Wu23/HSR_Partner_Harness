import type {
  DesktopCommand,
  DesktopEvent,
  DesktopResponse,
} from "../contracts/protocol";

export interface DesktopBackend {
  request<T>(command: DesktopCommand): Promise<T>;
  pickFolder(title?: string): Promise<string | null>;
  subscribe(listener: (event: DesktopEvent) => void): () => void;
}

export function unwrapResponse<T>(response: DesktopResponse<T>): T {
  if (!response.ok) {
    throw new Error(response.error?.message ?? "桌面后端请求失败");
  }
  return response.result as T;
}

export class RequestIdFactory {
  private value = 0;

  next(): string {
    this.value += 1;
    return `desktop-${this.value}`;
  }
}
