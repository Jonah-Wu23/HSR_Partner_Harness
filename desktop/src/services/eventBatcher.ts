import type { DesktopEvent } from "../contracts/protocol";

export function createEventBatcher(
  flush: (events: DesktopEvent[]) => void,
  delayMs = 40,
): {
  push(event: DesktopEvent): void;
  dispose(): void;
} {
  let pending: DesktopEvent[] = [];
  let timer: ReturnType<typeof setTimeout> | undefined;

  const push = (event: DesktopEvent) => {
    pending.push(event);
    if (timer !== undefined) return;
    timer = setTimeout(() => {
      const batch = pending;
      pending = [];
      timer = undefined;
      flush(batch);
    }, delayMs);
  };

  return {
    push,
    dispose() {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      // M5.5：StrictMode 卸载前同步 flush 最后一批事件，避免 pending 被丢弃。
      if (pending.length > 0) {
        const batch = pending;
        pending = [];
        flush(batch);
      }
    },
  };
}
