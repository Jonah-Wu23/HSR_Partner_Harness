import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ConnectionBanner } from "../ConnectionBanner";
import { mobileWsClient, useMobileStore } from "../../lib/mobileStore";
import { getStoredToken, saveCredentials } from "../../lib/wsClient";
import { FakeWebSocket, installFakeWebSocket, latestSocket } from "../../test/fakeWebSocket";

const DISCONNECTED_HINT = "电脑休眠、关机或 Sidecar 未运行时也会表现为断连。";

describe("ConnectionBanner 连接状态条", () => {
  beforeEach(async () => {
    installFakeWebSocket();
    window.localStorage.clear();
    window.location.hash = "#/list";
    // disconnect 把会话级状态复位到初值，并断开上一条用例留下的连接。
    await useMobileStore.getState().disconnect();
    useMobileStore.getState().start();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("已连接时不渲染", () => {
    const { container } = render(<ConnectionBanner connection="connected" />);
    expect(container.firstChild).toBeNull();
  });

  it.each([
    { connection: "connecting", message: "正在连接桌面端…", hint: false, action: null },
    { connection: "reconnecting", message: "与桌面端连接中断，正在重连…", hint: false, action: null },
    { connection: "unreachable", message: "无法连接到桌面端", hint: true, action: "btn-reconnect" },
    { connection: "disconnected", message: "已断开与桌面端的连接", hint: true, action: "btn-reconnect" },
    { connection: "auth_failed", message: "配对已失效或设备已被撤销", hint: false, action: "btn-repair" },
  ] as const)("$connection 时展示状态文案与对应操作", ({ connection, message, hint, action }) => {
    render(<ConnectionBanner connection={connection} />);

    expect(screen.getByTestId("connection-banner")).toHaveTextContent(message);
    expect(screen.queryByTestId("conn-banner-hint") !== null).toBe(hint);
    if (hint) expect(screen.getByTestId("conn-banner-hint")).toHaveTextContent(DISCONNECTED_HINT);
    for (const button of ["btn-reconnect", "btn-repair"]) {
      expect(screen.queryByTestId(button) !== null).toBe(button === action);
    }
  });

  it.each([
    { reason: "expired_token", message: "登录令牌已过期（最长30天或7天未使用），请重新配对。" },
    { reason: "revoked_token", message: "本设备已被桌面端撤销授权，请重新配对。" },
    { reason: "invalid_token", message: "配对已失效或设备已被撤销，请重新配对" },
  ] as const)("鉴权失败原因 $reason 展示对应文案", ({ reason, message }) => {
    render(<ConnectionBanner connection="auth_failed" authFailureReason={reason} />);
    expect(screen.getByTestId("connection-banner")).toHaveTextContent(message);
  });

  it("点击「重试」重新建立连接", () => {
    render(<ConnectionBanner connection="unreachable" />);
    const socketsBefore = FakeWebSocket.instances.length;

    fireEvent.click(screen.getByTestId("btn-reconnect"));

    expect(FakeWebSocket.instances).toHaveLength(socketsBefore + 1);
    expect(useMobileStore.getState().connection).toBe("connecting");
  });

  it("配对失效时「重新配对」清除本机凭据并跳转配对页", async () => {
    // 已配对的手机连上桌面端，app.bootstrap 以 unauthorized 被拒。
    saveCredentials("tok-revoked", "我的手机");
    mobileWsClient.connect();
    const socket = latestSocket();
    socket.open();
    await vi.waitFor(() => socket.lastFrame("app.bootstrap"));
    socket.respondError(socket.lastFrame("app.bootstrap"), "unauthorized", "revoked_token");
    await waitFor(() => expect(useMobileStore.getState().connection).toBe("auth_failed"));

    render(<ConnectionBanner connection="auth_failed" authFailureReason="revoked_token" />);
    fireEvent.click(screen.getByTestId("btn-repair"));

    // 凭据已失效，服务端不会接受释放控制权，直接清凭据后跳转。
    await waitFor(() => expect(window.location.hash).toBe("#/pair"));
    expect(getStoredToken()).toBeNull();
    expect(socket.sentFrames("remote.release_control")).toHaveLength(0);
  });
});
