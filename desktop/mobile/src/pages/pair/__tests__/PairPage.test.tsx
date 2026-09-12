import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PairPage } from "../PairPage";
import { useMobileStore } from "../../../lib/mobileStore";
import { RemoteCommandError } from "../../../lib/wsClient";

const initialStoreState = useMobileStore.getState();

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const ANDROID_SHELL_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";

function stubUserAgent(ua: string): void {
  Object.defineProperty(window.navigator, "userAgent", {
    value: ua,
    configurable: true,
  });
}

function stubAndroidShell(): void {
  window.__TAURI_INTERNALS__ = {};
  stubUserAgent(ANDROID_SHELL_UA);
}

describe("PairPage 组件", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    window.history.pushState({}, "", "/");
    delete window.__TAURI_INTERNALS__;
    delete window.__TAURI__;
    stubUserAgent(BROWSER_UA);
    useMobileStore.setState({
      connection: "disconnected",
      deviceName: null,
      projects: [],
      conversationsById: {},
      activeConversationId: null,
      messages: [],
      toolRuns: [],
      approvals: [],
      lastSequence: 0,
      bootstrapped: false,
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.localStorage.clear();
    useMobileStore.setState(initialStoreState);
    delete window.BarcodeDetector;
    delete window.__TAURI_INTERNALS__;
    delete window.__TAURI__;
  });

  it("当 URL 查询参数包含 ?code= 时，自动预填配对码", () => {
    window.history.pushState({}, "", "/?code=123456");
    render(<PairPage />);
    const codeInput = screen.getByTestId("input-pair-code") as HTMLInputElement;
    expect(codeInput.value).toBe("123456");
  });

  it("设备名称默认预填「我的手机」，用户可自行修改", () => {
    render(<PairPage />);
    const deviceInput = screen.getByTestId("input-device-name") as HTMLInputElement;
    expect(deviceInput.value).toBe("我的手机");

    fireEvent.change(deviceInput, { target: { value: "我的备用机" } });
    expect(deviceInput.value).toBe("我的备用机");
  });

  it("浏览器不支持 BarcodeDetector 时，如实展示不支持提示，不伪造扫码能力", () => {
    render(<PairPage />);
    expect(screen.queryByTestId("btn-start-scan")).toBeNull();
    expect(screen.getByTestId("scan-unsupported-hint")).toHaveTextContent(
      "当前浏览器不支持原生扫码",
    );
  });

  it("浏览器支持 BarcodeDetector 时，提供扫码入口并能解析扫码结果", async () => {
    const mockStop = vi.fn();
    const mockMediaStream = {
      getTracks: () => [{ stop: mockStop }],
    };

    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);

    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockResolvedValue(mockMediaStream),
      },
      writable: true,
      configurable: true,
    });

    class MockBarcodeDetector {
      detect = vi.fn().mockResolvedValue([
        { rawValue: "http://192.168.1.100:1421/?ws=ws%3A%2F%2F192.168.1.100%3A8765%2Fws&code=998877" },
      ]);
    }
    window.BarcodeDetector = MockBarcodeDetector as unknown as typeof window.BarcodeDetector;

    render(<PairPage />);
    const startScanBtn = screen.getByTestId("btn-start-scan");
    expect(startScanBtn).toBeInTheDocument();

    fireEvent.click(startScanBtn);

    await waitFor(() => {
      const codeInput = screen.getByTestId("input-pair-code") as HTMLInputElement;
      expect(codeInput.value).toBe("998877");
    });

    expect(window.localStorage.getItem("phm.wsUrl")).toBe("ws://192.168.1.100:8765/ws");
    expect(mockStop).toHaveBeenCalled();
  });

  it("配对成功时调用 store.pair", async () => {
    const pairSpy = vi.fn().mockResolvedValue(undefined);
    useMobileStore.setState({ pairDevice: pairSpy });

    render(<PairPage />);
    const codeInput = screen.getByTestId("input-pair-code");
    const deviceInput = screen.getByTestId("input-device-name");
    const submitBtn = screen.getByTestId("btn-submit-pair");

    fireEvent.change(codeInput, { target: { value: "654321" } });
    fireEvent.change(deviceInput, { target: { value: "工作手机" } });

    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(pairSpy).toHaveBeenCalledWith("654321", "工作手机");
    });
    expect(screen.queryByTestId("pair-error")).toBeNull();
  });

  it("配对失败三态：invalid_code 提示「配对码无效或已被新码作废」且可重新提交", async () => {
    const pairSpy = vi
      .fn()
      .mockRejectedValue(new RemoteCommandError("pairing_invalid_code", "配对码错误或已失效"));
    useMobileStore.setState({ pairDevice: pairSpy });

    render(<PairPage />);
    const codeInput = screen.getByTestId("input-pair-code");
    const submitBtn = screen.getByTestId("btn-submit-pair");

    fireEvent.change(codeInput, { target: { value: "000000" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      const errorBox = screen.getByTestId("pair-error");
      expect(errorBox).toBeInTheDocument();
      expect(errorBox).toHaveTextContent("配对码无效或已被新码作废");
    });

    // 重新提交
    pairSpy.mockResolvedValueOnce(undefined);
    fireEvent.change(codeInput, { target: { value: "111222" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(pairSpy).toHaveBeenCalledWith("111222", "我的手机");
    });
  });

  it("配对失败三态：expired_code 提示「配对码已过期，请在电脑端重新生成」", async () => {
    const pairSpy = vi
      .fn()
      .mockRejectedValue(new RemoteCommandError("pairing_expired_code", "配对码已过期"));
    useMobileStore.setState({ pairDevice: pairSpy });

    render(<PairPage />);
    fireEvent.change(screen.getByTestId("input-pair-code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByTestId("btn-submit-pair"));

    await waitFor(() => {
      const errorBox = screen.getByTestId("pair-error");
      expect(errorBox).toBeInTheDocument();
      expect(errorBox).toHaveTextContent("配对码已过期，请在电脑端重新生成");
    });
  });

  it("配对失败三态：rate_limited 展示限流封锁倒计时且倒计时结束前禁用提交按钮", async () => {
    vi.useFakeTimers();
    const pairSpy = vi
      .fn()
      .mockRejectedValue(
        new RemoteCommandError("pairing_rate_limited", "来源已封锁", { retry_after_s: 30 }),
      );
    useMobileStore.setState({ pairDevice: pairSpy });

    render(<PairPage />);
    fireEvent.change(screen.getByTestId("input-pair-code"), { target: { value: "123456" } });
    const submitBtn = screen.getByTestId("btn-submit-pair");
    fireEvent.click(submitBtn);

    await vi.waitFor(() => {
      const errorBox = screen.getByTestId("pair-error");
      expect(errorBox).toBeInTheDocument();
      expect(errorBox).toHaveTextContent("限流封锁");
      expect(errorBox).toHaveTextContent("30 秒");
    });

    // 倒计时期间提交按钮禁用
    expect(submitBtn).toBeDisabled();
    expect(submitBtn).toHaveTextContent("30s");

    // 时间流逝 15 秒，倒计时更新
    vi.advanceTimersByTime(15_000);
    await vi.waitFor(() => {
      expect(screen.getByTestId("pair-error")).toHaveTextContent("15 秒");
      expect(submitBtn).toHaveTextContent("15s");
      expect(submitBtn).toBeDisabled();
    });

    // 倒计时结束，按钮重新恢复可用
    vi.advanceTimersByTime(16_000);
    await vi.waitFor(() => {
      expect(submitBtn).not.toBeDisabled();
      expect(submitBtn).toHaveTextContent("开始配对");
    });

    vi.useRealTimers();
  });

  it("D5：登录令牌过期时进入重新配对引导，如实提示最长30天或7天未使用", () => {
    useMobileStore.setState({ authFailureCode: "expired_token" });
    render(<PairPage />);
    const alert = screen.getByTestId("expired-token-alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent("登录令牌已过期（最长30天或7天未使用），请重新配对。");
  });

  it("扫码公网隧道 URL（https://xxx.trycloudflare.com/?code=...）正确规范化为 wss:// 入口", async () => {
    const mockStop = vi.fn();
    const mockMediaStream = { getTracks: () => [{ stop: mockStop }] };
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(mockMediaStream) },
      writable: true,
      configurable: true,
    });

    class MockBarcodeDetector {
      detect = vi.fn().mockResolvedValue([
        { rawValue: "https://my-tunnel.trycloudflare.com/?code=889900" },
      ]);
    }
    window.BarcodeDetector = MockBarcodeDetector as unknown as typeof window.BarcodeDetector;

    render(<PairPage />);
    fireEvent.click(screen.getByTestId("btn-start-scan"));

    await waitFor(() => {
      const codeInput = screen.getByTestId("input-pair-code") as HTMLInputElement;
      expect(codeInput.value).toBe("889900");
    });

    expect(window.localStorage.getItem("phm.wsUrl")).toBe("wss://my-tunnel.trycloudflare.com/ws");
  });

  it("连接问题（普通 Error）如实展示网络错误", async () => {
    const pairSpy = vi.fn().mockRejectedValue(new Error("WebSocket 未连接"));
    useMobileStore.setState({ pairDevice: pairSpy });

    render(<PairPage />);
    const codeInput = screen.getByTestId("input-pair-code");
    const submitBtn = screen.getByTestId("btn-submit-pair");

    fireEvent.change(codeInput, { target: { value: "123456" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      const errorBox = screen.getByTestId("pair-error");
      expect(errorBox).toHaveTextContent("WebSocket 未连接");
    });
  });
});

describe("PairPage V0.3.7 壳内桌面端地址输入", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    window.history.pushState({}, "", "/");
    delete window.__TAURI_INTERNALS__;
    delete window.__TAURI__;
    stubUserAgent(BROWSER_UA);
    useMobileStore.setState({
      connection: "disconnected",
      deviceName: null,
      projects: [],
      conversationsById: {},
      activeConversationId: null,
      messages: [],
      toolRuns: [],
      approvals: [],
      lastSequence: 0,
      bootstrapped: false,
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.localStorage.clear();
    useMobileStore.setState(initialStoreState);
    delete window.__TAURI_INTERNALS__;
    delete window.__TAURI__;
  });

  it("PWA 下不渲染地址输入区，配对体验不变", () => {
    render(<PairPage />);
    expect(screen.queryByTestId("ws-address-section")).toBeNull();
    expect(screen.queryByTestId("ws-address-input")).toBeNull();
  });

  it("Android 壳内渲染地址输入区并预填已保存的地址", () => {
    stubAndroidShell();
    window.localStorage.setItem("phm.wsUrl", "ws://192.168.1.50:8765/ws");

    render(<PairPage />);
    const input = screen.getByTestId("ws-address-input") as HTMLInputElement;
    expect(input.value).toBe("ws://192.168.1.50:8765/ws");
    expect(screen.getByTestId("btn-save-ws-address")).toBeEnabled();
  });

  it("壳内保存合法地址写入 phm.wsUrl 并立即触发重连", () => {
    stubAndroidShell();
    const reconnectSpy = vi.fn();
    useMobileStore.setState({ reconnect: reconnectSpy });

    render(<PairPage />);
    const input = screen.getByTestId("ws-address-input");
    fireEvent.change(input, { target: { value: "  ws://10.0.0.5:8765/ws  " } });
    fireEvent.click(screen.getByTestId("btn-save-ws-address"));

    expect(window.localStorage.getItem("phm.wsUrl")).toBe("ws://10.0.0.5:8765/ws");
    expect(reconnectSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("ws-address-saved")).toHaveTextContent("地址已保存");
  });

  it("壳内非法地址时保存按钮禁用，不写入 localStorage", () => {
    stubAndroidShell();

    render(<PairPage />);
    const input = screen.getByTestId("ws-address-input");
    fireEvent.change(input, { target: { value: "http://192.168.1.50:8765/ws" } });

    expect(screen.getByTestId("btn-save-ws-address")).toBeDisabled();
    expect(window.localStorage.getItem("phm.wsUrl")).toBeNull();
  });

  it("壳内再次编辑地址时「已保存」提示消失，等下次保存", () => {
    stubAndroidShell();
    useMobileStore.setState({ reconnect: vi.fn() });

    render(<PairPage />);
    const input = screen.getByTestId("ws-address-input");
    fireEvent.change(input, { target: { value: "ws://10.0.0.5:8765/ws" } });
    fireEvent.click(screen.getByTestId("btn-save-ws-address"));
    expect(screen.getByTestId("ws-address-saved")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "ws://10.0.0.9:8765/ws" } });
    expect(screen.queryByTestId("ws-address-saved")).toBeNull();
  });
});
