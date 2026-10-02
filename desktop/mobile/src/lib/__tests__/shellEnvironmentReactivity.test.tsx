import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import {
  detectShellEnvironment,
  onShellEnvironmentChange,
  useShellEnvironment,
  type ShellEnvironment,
} from "../shellCapabilities";

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const ANDROID_SHELL_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";

function stubUserAgent(userAgent: string): void {
  Object.defineProperty(window.navigator, "userAgent", {
    value: userAgent,
    configurable: true,
  });
}

const unsubscribes: Array<() => void> = [];

/** 订阅壳环境变化；afterEach 统一退订，最后一个订阅者退订时轮询停止，下一个用例从头开始。 */
function subscribe(): ShellEnvironment[] {
  const received: ShellEnvironment[] = [];
  unsubscribes.push(onShellEnvironmentChange((environment) => received.push(environment)));
  return received;
}

beforeEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubUserAgent(BROWSER_UA);
});

afterEach(() => {
  cleanup();
  unsubscribes.splice(0).forEach((unsubscribe) => unsubscribe());
  vi.useRealTimers();
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubUserAgent(BROWSER_UA);
});

describe("壳注入晚于首帧时的壳环境订阅", () => {
  it("首次轮询判为 PWA，壳注入后订阅回调收到 android_shell", async () => {
    vi.useFakeTimers();
    const received = subscribe();

    // 首次轮询在 50ms 后，此时壳还没注入。
    await vi.advanceTimersByTimeAsync(60);
    expect(received).toContain("pwa");

    window.__TAURI_INTERNALS__ = {};
    stubUserAgent(ANDROID_SHELL_UA);
    await vi.advanceTimersByTimeAsync(200);

    expect(received).toContain("android_shell");
    expect(detectShellEnvironment()).toBe("android_shell");
  });

  it("useShellEnvironment 在壳注入后从 pwa 更新为 android_shell", async () => {
    const { result } = renderHook(() => useShellEnvironment());
    expect(result.current).toBe("pwa");

    window.__TAURI_INTERNALS__ = {};
    stubUserAgent(ANDROID_SHELL_UA);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    expect(result.current).toBe("android_shell");
  });

  it("等待上限（2.5 秒）过后停止轮询，之后的注入不再触发回调", async () => {
    vi.useFakeTimers();
    const received = subscribe();
    await vi.advanceTimersByTimeAsync(4000);
    expect(received.every((value) => value === "pwa")).toBe(true);

    window.__TAURI_INTERNALS__ = {};
    stubUserAgent(ANDROID_SHELL_UA);
    await vi.advanceTimersByTimeAsync(500);
    expect(received.every((value) => value === "pwa")).toBe(true);
  });
});
