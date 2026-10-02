import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";

import type {
  DesktopCommand,
  DesktopResponse,
  DesktopStreamEvent,
} from "../contracts/protocol";
import type { DesktopBackend, FileFilter } from "./backend";
import { DEFAULT_REQUEST_TIMEOUT_SECS, unwrapResponse } from "./backend";

export class TauriDesktopBackend implements DesktopBackend {
  private readonly listeners = new Set<(event: DesktopStreamEvent) => void>();

  constructor() {
    // sidecar://event 也会转发 Sidecar 输出的其他非响应行，只把 kind=event 交给订阅方。
    // 后端实例与窗口同生命周期，监听不需要注销。
    void listen<DesktopStreamEvent>("sidecar://event", (event) => {
      if (event.payload.kind !== "event") return;
      for (const listener of this.listeners) listener(event.payload);
    });
  }

  async request<T>(
    command: DesktopCommand,
    timeoutSecs: number | null = DEFAULT_REQUEST_TIMEOUT_SECS,
  ): Promise<T> {
    const response = await invoke<DesktopResponse<T>>("desktop_request", {
      request: command,
      timeout_secs: timeoutSecs,
    });
    return unwrapResponse(response);
  }

  async openChatWindow(conversationId: string, title: string): Promise<string> {
    return invoke<string>("open_chat_window", { conversation_id: conversationId, title });
  }

  async pickFolder(title = "选择项目文件夹"): Promise<string | null> {
    const selected = await open({ directory: true, multiple: false, title });
    return typeof selected === "string" ? selected : null;
  }

  async pickFile(options?: { title?: string; filters?: FileFilter[] }): Promise<string | null> {
    const selected = await open({
      directory: false,
      multiple: false,
      title: options?.title ?? "选择文件",
      filters: options?.filters,
    });
    return typeof selected === "string" ? selected : null;
  }

  async saveFile(options?: { title?: string; defaultPath?: string; filters?: FileFilter[] }): Promise<string | null> {
    const selected = await save({
      title: options?.title ?? "保存文件",
      defaultPath: options?.defaultPath,
      filters: options?.filters,
    });
    return typeof selected === "string" ? selected : null;
  }

  async reconnectSidecar(): Promise<void> {
    await invoke<{ reconnected: boolean }>("sidecar_reconnect");
  }

  subscribe(listener: (event: DesktopStreamEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
