import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  detectShellEnvironment,
  onShellEnvironmentChange,
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

beforeEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubUserAgent(BROWSER_UA);
});

afterEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubUserAgent(BROWSER_UA);
  vi.restoreAllMocks();
});

describe("壳注入竞态的订阅式判定（真机 00:58 实证缺陷的回归）", () => {
  it("首判 PWA、internals 延迟注入后，订阅回调收到壳值", async () => {
    vi.useFakeTimers();
    const received: string[] = [];
    const unsubscribe = onShellEnvironmentChange((environment) => {
      received.push(environment);
    });

    // 首次轮询（50ms 后）：注入未发生，如实回调 pwa。
    await vi.advanceTimersByTimeAsync(60);
    expect(received).toContain("pwa");

    // 模拟 document-start 脚本注入完成（真机竞态窗口内）。
    window.__TAURI_INTERNALS__ = {};
    stubUserAgent(ANDROID_SHELL_UA);
    await vi.advanceTimersByTimeAsync(200);

    expect(received).toContain("android_shell");
    expect(detectShellEnvironment()).toBe("android_shell");
    unsubscribe();
    vi.useRealTimers();
  });

  it("useShellEnvironment hook 在注入后从 pwa 更新为 android_shell", async () => {
    // 模块单例（轮询状态）被前序用例污染：用全新模块实例做自包含验证。
    vi.resetModules();
    const { useShellEnvironment: freshHook } = await import("../shellCapabilities");
    const { result } = renderHook(() => freshHook());
    expect(result.current).toBe("pwa");

    window.__TAURI_INTERNALS__ = {};
    stubUserAgent(ANDROID_SHELL_UA);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    expect(result.current).toBe("android_shell");
    vi.resetModules();
  });

  it("宽限期后不再轮询：注入永远不来时回调停止在 pwa", async () => {
    vi.useFakeTimers();
    const received: string[] = [];
    const unsubscribe = onShellEnvironmentChange((environment) => {
      received.push(environment);
    });
    // 超过 SHELL_INJECTION_GRACE_MS（2500ms）仍未注入。
    await vi.advanceTimersByTimeAsync(4000);
    expect(received.every((value) => value === "pwa")).toBe(true);

    // 宽限期后注入不再被感知（轮询已停）——设计语义：竞态窗口有限，
    // 注入超过 2.5 秒仍未发生视为非壳环境（PWA），不做常驻探针。
    window.__TAURI_INTERNALS__ = {};
    stubUserAgent(ANDROID_SHELL_UA);
    await vi.advanceTimersByTimeAsync(500);
    expect(received.every((value) => value === "pwa")).toBe(true);
    unsubscribe();
    vi.useRealTimers();
  });
});
