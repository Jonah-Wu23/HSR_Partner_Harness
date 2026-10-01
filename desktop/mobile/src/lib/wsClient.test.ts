import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeWebSocket, installFakeWebSocket, latestSocket } from "../test/fakeWebSocket";
import {
  clearCredentials,
  getStoredToken,
  INBOUND_STALE_MS,
  MobileWsClient,
  parseWsAddress,
  PING_INTERVAL_MS,
  RemoteCommandError,
  resolveWsUrl,
  saveCredentials,
} from "./wsClient";

/** 新建客户端并完成握手，返回它与对应的 socket。 */
function connectedClient(): { client: MobileWsClient; ws: FakeWebSocket } {
  const client = new MobileWsClient();
  client.connect();
  const ws = latestSocket();
  ws.open();
  return { client, ws };
}

beforeEach(() => {
  installFakeWebSocket();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("parseWsAddress 规范化", () => {
  it.each([
    ["https://foo-bar.trycloudflare.com", "wss://foo-bar.trycloudflare.com/ws"],
    ["https://foo-bar.trycloudflare.com/", "wss://foo-bar.trycloudflare.com/ws"],
    ["https://foo-bar.trycloudflare.com/ws", "wss://foo-bar.trycloudflare.com/ws"],
    [
      "https://foo-bar.trycloudflare.com/?code=123456&ws=wss://foo-bar.trycloudflare.com/ws",
      "wss://foo-bar.trycloudflare.com/ws",
    ],
    ["wss://foo-bar.trycloudflare.com", "wss://foo-bar.trycloudflare.com/ws"],
    ["ws://192.168.1.50:8765/ws", "ws://192.168.1.50:8765/ws"],
  ])("%s 规范化为 %s", (raw, url) => {
    expect(parseWsAddress(raw)).toEqual({ ok: true, url });
  });
});

describe("resolveWsUrl", () => {
  it("?ws= 规范化后优先采用并写入缓存，随后从地址栏移除", () => {
    window.history.pushState({}, "", "/?ws=https://tunnel.trycloudflare.com");
    expect(resolveWsUrl()).toBe("wss://tunnel.trycloudflare.com/ws");
    expect(window.location.search).toBe("");
    expect(resolveWsUrl()).toBe("wss://tunnel.trycloudflare.com/ws");
  });

  it("无参数无缓存时回退到当前站点 /ws", () => {
    expect(resolveWsUrl()).toBe(`ws://${window.location.host}/ws`);
  });
});

describe("凭证存储", () => {
  it("配对写入和解绑清除会立即同步 Android 原生连接", () => {
    // Android 壳注入的原生接口，PWA 与 jsdom 里都没有。
    const syncConfig = vi.fn();
    vi.stubGlobal("PairHarnessNative", { syncConfig });
    window.history.pushState({}, "", "/?ws=ws://192.168.1.8:8765/ws");
    window.localStorage.setItem(
      "phm.notificationPreferences.v1",
      '{"taskCompleted":{"enabled":false,"importance":"silent"}}',
    );

    saveCredentials("tok-native", "Android");
    expect(syncConfig).toHaveBeenLastCalledWith(
      "ws://192.168.1.8:8765/ws",
      "tok-native",
      '{"taskCompleted":{"enabled":false,"importance":"silent"}}',
    );

    clearCredentials();
    expect(syncConfig).toHaveBeenLastCalledWith(
      "ws://192.168.1.8:8765/ws",
      "",
      '{"taskCompleted":{"enabled":false,"importance":"silent"}}',
    );
  });
});

describe("MobileWsClient", () => {
  it("已配对的请求在顶层携带 auth token", async () => {
    saveCredentials("tok-1", "我的小米");
    const { client, ws } = connectedClient();

    const pending = client.request("app.bootstrap");
    const frame = ws.lastFrame("app.bootstrap");
    expect(frame).toMatchObject({ kind: "request", auth: { token: "tok-1" } });
    ws.respond(frame, { sequence: 1 });
    await expect(pending).resolves.toEqual({ sequence: 1 });
  });

  it("skipAuth 的请求（remote.pair）不携带 auth", async () => {
    saveCredentials("tok-old", "旧设备");
    const { client, ws } = connectedClient();

    const pending = client.request(
      "remote.pair",
      { code: "654321", device_name: "我的小米" },
      { skipAuth: true },
    );
    const frame = ws.lastFrame("remote.pair");
    expect(frame).not.toHaveProperty("auth");
    ws.respond(frame, { token: "tok-new" });
    await expect(pending).resolves.toEqual({ token: "tok-new" });
  });

  it.each([
    ["invalid_token", "tok-1"],
    ["revoked_token", "tok-1"],
    ["expired_token", null],
  ] as const)(
    "unauthorized（%s）拒绝请求并进入 auth_failed，之后本地 token 为 %s",
    async (reason, storedToken) => {
      saveCredentials("tok-1", "我的手机");
      const { client, ws } = connectedClient();

      const pending = client.request("app.bootstrap");
      ws.respondError(ws.lastFrame("app.bootstrap"), "unauthorized", reason);

      const error = await pending.catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(RemoteCommandError);
      expect((error as RemoteCommandError).code).toBe("unauthorized");
      expect(client.getState()).toBe("auth_failed");
      expect(client.getAuthFailureReason()).toBe(reason);
      expect(getStoredToken()).toBe(storedToken);
    },
  );

  it("其他错误码即使文案含 expired_token 也不进入鉴权失败，凭据保留", async () => {
    saveCredentials("tok-valid", "我的手机");
    const { client, ws } = connectedClient();

    const pending = client.request("chat.submit");
    ws.respondError(
      ws.lastFrame("chat.submit"),
      "internal_error",
      "处理委派失败：子任务状态 expired_token 越界",
    );

    await expect(pending).rejects.toBeInstanceOf(RemoteCommandError);
    expect(client.getState()).toBe("connected");
    expect(client.getAuthFailureReason()).toBeNull();
    expect(getStoredToken()).toBe("tok-valid");
  });

  it("连接未就绪时请求直接失败", async () => {
    const client = new MobileWsClient();
    await expect(client.request("app.bootstrap")).rejects.toThrow("WebSocket 未连接");
  });

  it("事件帧分发给 onEvent 监听器", () => {
    const client = new MobileWsClient();
    const received: string[] = [];
    client.onEvent((event) => received.push(event.event));
    client.connect();
    const ws = latestSocket();
    ws.open();
    ws.emit({ kind: "event", event: "queue.changed", sequence: 3, payload: {} });
    expect(received).toEqual(["queue.changed"]);
  });

  it("断线按退避重连，五次失败后进入 unreachable", () => {
    vi.useFakeTimers();
    const { client } = connectedClient();

    for (const delay of [1000, 2000, 4000, 8000, 16000]) {
      latestSocket().close();
      expect(client.getState()).toBe("reconnecting");
      vi.advanceTimersByTime(delay);
    }
    latestSocket().close();
    expect(client.getState()).toBe("unreachable");
  });

  it("主动 disconnect 不触发重连", () => {
    vi.useFakeTimers();
    const { client } = connectedClient();
    client.disconnect();
    expect(client.getState()).toBe("disconnected");
    vi.advanceTimersByTime(60000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(client.getState()).toBe("disconnected");
  });
});

describe("MobileWsClient 心跳", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("每 15 秒发一次 ping，30 秒没有入站消息即摘除连接并重连", () => {
    saveCredentials("tok-hb", "设备");
    const { client, ws } = connectedClient();
    // 心跳由调用方在鉴权 bootstrap 成功后启动。
    client.startHeartbeat();

    vi.advanceTimersByTime(PING_INTERVAL_MS);
    expect(ws.sentFrames("ping")).toHaveLength(1);
    expect(client.getState()).toBe("connected");

    vi.advanceTimersByTime(INBOUND_STALE_MS - PING_INTERVAL_MS);
    expect(client.getState()).toBe("reconnecting");
  });

  it("服务端应答 ping 时保持连接并按周期继续发 ping", async () => {
    FakeWebSocket.autoResults.set("ping", { server_time: "2026-09-01T00:00:00+00:00" });
    saveCredentials("tok-hb", "设备");
    const { client, ws } = connectedClient();
    client.startHeartbeat();

    await vi.advanceTimersByTimeAsync(PING_INTERVAL_MS * 8);

    expect(client.getState()).toBe("connected");
    expect(ws.sentFrames("ping")).toHaveLength(8);
  });
});

describe("MobileWsClient 回前台", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("unreachable 时回前台复位退避并重新连接", () => {
    saveCredentials("tok-fg", "设备");
    const { client } = connectedClient();
    latestSocket().close();
    // 新连接不握手就关闭，连续五次耗尽退避；握手成功会复位退避计数。
    for (let i = 0; i < 5; i += 1) {
      vi.advanceTimersByTime(16000);
      latestSocket().close();
    }
    expect(client.getState()).toBe("unreachable");

    expect(client.notifyAppForeground()).toBe("reconnecting");
    expect(client.getState()).toBe("connecting");
  });

  it("connected 时回前台返回 resync，由调用方重新同步", () => {
    saveCredentials("tok-fg", "设备");
    const { client } = connectedClient();
    expect(client.notifyAppForeground()).toBe("resync");
  });

  it("握手进行中回前台返回 none", () => {
    saveCredentials("tok-fg", "设备");
    const client = new MobileWsClient();
    client.connect();
    expect(client.notifyAppForeground()).toBe("none");
  });
});
