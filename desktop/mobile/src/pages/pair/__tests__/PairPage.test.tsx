import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PairPage } from "../PairPage";
import { useMobileStore } from "../../../lib/mobileStore";
import { getStoredToken } from "../../../lib/wsClient";
import {
  FakeWebSocket,
  installFakeWebSocket,
  latestSocket,
  type SentFrame,
} from "../../../test/fakeWebSocket";

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

/**
 * 扫码平台桩：摄像头流、视频播放与 BarcodeDetector（识别出给定的二维码内容）。
 * 返回摄像头轨道的 stop，用于确认扫码结束后摄像头已关闭。
 */
function stubScanner(rawValue: string): ReturnType<typeof vi.fn> {
  const stopTrack = vi.fn();
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) },
    configurable: true,
  });
  window.BarcodeDetector = class {
    detect = vi.fn().mockResolvedValue([{ rawValue }]);
  } as unknown as typeof window.BarcodeDetector;
  return stopTrack;
}

/** 提交配对表单。配对总在新连接上进行：等新连接建立后返回发出的 remote.pair 请求帧。 */
async function submitPair(code: string): Promise<SentFrame> {
  fireEvent.change(screen.getByTestId("input-pair-code"), { target: { value: code } });
  const socketsBefore = FakeWebSocket.instances.length;
  fireEvent.click(screen.getByTestId("btn-submit-pair"));
  await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(socketsBefore));
  const socket = latestSocket();
  socket.open();
  await vi.waitFor(() => socket.lastFrame("remote.pair"));
  return socket.lastFrame("remote.pair");
}

beforeEach(async () => {
  installFakeWebSocket();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubUserAgent(BROWSER_UA);
  // disconnect 把会话级状态复位到初值，并断开上一条用例留下的连接。
  await useMobileStore.getState().disconnect();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  delete window.BarcodeDetector;
  delete (navigator as { mediaDevices?: unknown }).mediaDevices;
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
});

describe("PairPage 配对", () => {
  it("地址栏带 ?code= 时预填配对码", () => {
    window.history.pushState({}, "", "/?code=123456");
    render(<PairPage />);
    expect(screen.getByTestId("input-pair-code")).toHaveValue("123456");
  });

  it("设备名称默认预填「我的手机」", () => {
    render(<PairPage />);
    expect(screen.getByTestId("input-device-name")).toHaveValue("我的手机");
  });

  it("浏览器没有 BarcodeDetector 时不提供扫码入口并说明原因", () => {
    render(<PairPage />);
    expect(screen.queryByTestId("btn-start-scan")).toBeNull();
    expect(screen.getByTestId("scan-unsupported-hint")).toHaveTextContent(
      "当前浏览器不支持原生扫码",
    );
  });

  it("提交后在新连接上发出不带令牌的 remote.pair，成功后保存令牌并开始同步", async () => {
    render(<PairPage />);
    fireEvent.change(screen.getByTestId("input-device-name"), { target: { value: "工作手机" } });

    const frame = await submitPair("654321");
    expect(frame.params).toEqual({ code: "654321", device_name: "工作手机" });
    expect(frame).not.toHaveProperty("auth");
    latestSocket().respond(frame, { token: "tok-new" });

    await vi.waitFor(() => latestSocket().lastFrame("app.bootstrap"));
    expect(getStoredToken()).toBe("tok-new");
    expect(screen.queryByTestId("pair-error")).toBeNull();
  });

  it.each([
    { code: "pairing_invalid_code", message: "配对码无效", copy: "配对码无效或已被新码作废" },
    { code: "pairing_expired_code", message: "配对码已过期", copy: "配对码已过期，请在电脑端重新生成" },
    {
      code: "pairing_code_exhausted",
      message: "配对码错误次数过多，已作废，请在桌面端重新生成",
      copy: "配对码输错次数过多，已作废",
    },
  ])("remote.pair 返回 $code 时展示对应提示，改码后可以重新提交", async ({ code, message, copy }) => {
    render(<PairPage />);

    const frame = await submitPair("000000");
    latestSocket().respondError(frame, code, message);
    expect(await screen.findByTestId("pair-error-message")).toHaveTextContent(copy);

    const retry = await submitPair("111222");
    expect(retry.params).toEqual({ code: "111222", device_name: "我的手机" });
  });

  it("配对请求途中连接断开时展示原始错误", async () => {
    render(<PairPage />);
    await submitPair("123456");

    latestSocket().close();

    expect(await screen.findByTestId("pair-error-message")).toHaveTextContent("WebSocket 连接已关闭");
  });

  it("登录令牌过期后进入配对页时说明过期规则", () => {
    // 与 store 收到 expired_token 鉴权失败后的状态一致。
    useMobileStore.setState({
      connection: "auth_failed",
      authFailureReason: "expired_token",
      deviceName: null,
    });
    render(<PairPage />);
    expect(screen.getByTestId("expired-token-alert")).toHaveTextContent(
      "登录令牌已过期（最长30天或7天未使用），请重新配对。",
    );
  });
});

describe("PairPage 桌面端地址与扫码", () => {
  it("PWA 下不渲染地址输入区", () => {
    render(<PairPage />);
    expect(screen.queryByTestId("ws-address-section")).toBeNull();
  });

  it("Android 壳内渲染地址输入区并预填已保存的地址", () => {
    stubAndroidShell();
    window.localStorage.setItem("phm.wsUrl", "ws://192.168.1.50:8765/ws");

    render(<PairPage />);
    expect(screen.getByTestId("ws-address-input")).toHaveValue("ws://192.168.1.50:8765/ws");
    expect(screen.getByTestId("btn-save-ws-address")).toBeEnabled();
  });

  it("壳内保存合法地址：规范化后写入并立即用新地址重连", () => {
    stubAndroidShell();
    render(<PairPage />);

    fireEvent.change(screen.getByTestId("ws-address-input"), {
      target: { value: "  ws://10.0.0.5:8765/ws  " },
    });
    fireEvent.click(screen.getByTestId("btn-save-ws-address"));

    expect(window.localStorage.getItem("phm.wsUrl")).toBe("ws://10.0.0.5:8765/ws");
    expect(latestSocket().url).toBe("ws://10.0.0.5:8765/ws");
    expect(screen.getByTestId("ws-address-saved")).toHaveTextContent("地址已保存");
  });

  it("壳内地址非法时保存按钮禁用，不写入地址", () => {
    stubAndroidShell();
    render(<PairPage />);

    fireEvent.change(screen.getByTestId("ws-address-input"), {
      target: { value: "http://192.168.1.50:8765/ws" },
    });

    expect(screen.getByTestId("btn-save-ws-address")).toBeDisabled();
    expect(window.localStorage.getItem("phm.wsUrl")).toBeNull();
  });

  it("壳内保存后再次编辑地址，「已保存」提示消失", () => {
    stubAndroidShell();
    render(<PairPage />);
    const input = screen.getByTestId("ws-address-input");

    fireEvent.change(input, { target: { value: "ws://10.0.0.5:8765/ws" } });
    fireEvent.click(screen.getByTestId("btn-save-ws-address"));
    expect(screen.getByTestId("ws-address-saved")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "ws://10.0.0.9:8765/ws" } });
    expect(screen.queryByTestId("ws-address-saved")).toBeNull();
  });

  it.each([
    {
      label: "局域网二维码（带 ?ws=）",
      rawValue: "http://192.168.1.100:1421/?ws=ws%3A%2F%2F192.168.1.100%3A8765%2Fws&code=998877",
      code: "998877",
      wsUrl: "ws://192.168.1.100:8765/ws",
    },
    {
      label: "公网隧道二维码（只有 ?code=）",
      rawValue: "https://my-tunnel.trycloudflare.com/?code=889900",
      code: "889900",
      wsUrl: "wss://my-tunnel.trycloudflare.com/ws",
    },
  ])("壳内扫描$label：带入配对码与规范化地址，关闭摄像头并用该地址重连", async ({
    rawValue,
    code,
    wsUrl,
  }) => {
    stubAndroidShell();
    const stopTrack = stubScanner(rawValue);
    render(<PairPage />);

    fireEvent.click(screen.getByTestId("btn-start-scan"));

    await waitFor(() => expect(screen.getByTestId("input-pair-code")).toHaveValue(code));
    expect(screen.getByTestId("ws-address-input")).toHaveValue(wsUrl);
    expect(window.localStorage.getItem("phm.wsUrl")).toBe(wsUrl);
    expect(latestSocket().url).toBe(wsUrl);
    expect(stopTrack).toHaveBeenCalled();
    // 地址来自本次扫码，「已保存」提示不残留。
    expect(screen.queryByTestId("ws-address-saved")).toBeNull();
  });

  it("壳内扫描裸配对码：只带入配对码，地址与连接保持不变", async () => {
    stubAndroidShell();
    stubScanner("654321");
    window.localStorage.setItem("phm.wsUrl", "ws://10.0.0.5:8765/ws");
    render(<PairPage />);

    fireEvent.click(screen.getByTestId("btn-start-scan"));

    await waitFor(() => expect(screen.getByTestId("input-pair-code")).toHaveValue("654321"));
    expect(screen.getByTestId("ws-address-input")).toHaveValue("ws://10.0.0.5:8765/ws");
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("二维码地址里没有配对码时展示扫码错误原文", async () => {
    stubScanner("https://my-tunnel.trycloudflare.com/");
    render(<PairPage />);

    fireEvent.click(screen.getByTestId("btn-start-scan"));

    expect(await screen.findByTestId("scanner-error")).toHaveTextContent(
      "二维码地址里没有配对码：https://my-tunnel.trycloudflare.com/",
    );
    expect(screen.getByTestId("input-pair-code")).toHaveValue("");
  });
});
