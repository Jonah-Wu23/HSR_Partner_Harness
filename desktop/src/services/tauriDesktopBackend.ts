import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";

import type {
  DesktopCommand,
  DesktopEvent,
  DesktopResponse,
} from "../contracts/protocol";
import type { DesktopBackend } from "./backend";
import { unwrapResponse } from "./backend";

export class TauriDesktopBackend implements DesktopBackend {
  private readonly listeners = new Set<(event: DesktopEvent) => void>();
  private readonly unlisten: Promise<UnlistenFn>;

  constructor() {
    this.unlisten = listen<DesktopEvent>("sidecar://event", (event) => {
      const payload = event.payload as unknown as {
        kind?: string;
        sequence?: unknown;
      };
      // M6.3：sequence 是 stream_id 代次内的整数序号，始终处于 JS 安全
      // 整数范围；用 Number.isSafeInteger 对齐新协议，而不是宽松的 isFinite。
      if (payload.kind !== "event" || !Number.isSafeInteger(payload.sequence)) return;
      for (const listener of this.listeners) listener(event.payload);
    });
  }

  async request<T>(command: DesktopCommand): Promise<T> {
    const response = await invoke<DesktopResponse<T>>("desktop_request", {
      request: command,
    });
    return unwrapResponse(response);
  }

  async openChatWindow(conversationId: string, projectId: string, title: string): Promise<string> {
    return invoke<string>("open_chat_window", {
      conversation_id: conversationId,
      project_id: projectId,
      title,
    });
  }

  async pickFolder(title = "选择项目文件夹"): Promise<string | null> {
    const selected = await open({ directory: true, multiple: false, title });
    return typeof selected === "string" ? selected : null;
  }

  async reconnectSidecar(): Promise<void> {
    // Sidecar 可能已断开，不能经 desktop_request 转发，直接调用 Rust 命令
    await invoke<{ reconnected: boolean }>("sidecar_reconnect");
  }

  subscribe(listener: (event: DesktopEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async dispose(): Promise<void> {
    const unlisten = await this.unlisten;
    unlisten();
    this.listeners.clear();
  }
}
