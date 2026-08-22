import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PairPage } from "../PairPage";
import { useMobileStore } from "../../../lib/mobileStore";
import { RemoteCommandError } from "../../../lib/wsClient";

const initialStoreState = useMobileStore.getState();

describe("PairPage 组件", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    window.history.pushState({}, "", "/");
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

  it("配对失败（RemoteCommandError）如实展示错误码与信息且可重试", async () => {
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
      expect(errorBox).toHaveTextContent("[pairing_invalid_code] 配对码错误或已失效");
    });

    // 重新提交
    pairSpy.mockResolvedValueOnce(undefined);
    fireEvent.change(codeInput, { target: { value: "111222" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(pairSpy).toHaveBeenCalledWith("111222", "我的手机");
    });
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
