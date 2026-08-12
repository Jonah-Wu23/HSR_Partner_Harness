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
      for (const listener of this.listeners) listener(event.payload);
    });
  }

  async request<T>(command: DesktopCommand): Promise<T> {
    const response = await invoke<DesktopResponse<T>>("desktop_request", {
      request: command,
    });
    return unwrapResponse(response);
  }

  async pickFolder(title = "选择项目文件夹"): Promise<string | null> {
    const selected = await open({ directory: true, multiple: false, title });
    return typeof selected === "string" ? selected : null;
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
