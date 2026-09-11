import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearCredentials,
  getStoredDeviceName,
  getStoredToken,
  INBOUND_STALE_MS,
  MobileWsClient,
  normalizeWsUrl,
  PING_INTERVAL_MS,
  RemoteCommandError,
  resolveWsUrl,
  saveCredentials,
} from "./wsClient";

/** 测试用 WS 假实现：协议帧经 emit 注入，sent 记录客户端发出的原始帧。 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;

  readyState = FakeWebSocket.CONNECTING;
  readonly url: string;
  readonly sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  send(data: string): void {
    this.sent.push(data);
  }

  emit(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
}

function lastInstance(): FakeWebSocket {
  const instance = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  if (!instance) throw new Error("没有 FakeWebSocket 实例");
  return instance;
}

function lastSentFrame(instance: FakeWebSocket): Record<string, unknown> {
  const raw = instance.sent[instance.sent.length - 1];
  if (!raw) throw new Error("客户端尚未发出任何帧");
  return JSON.parse(raw) as Record<string, unknown>;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("normalizeWsUrl", () => {
  it("公网隧道 https:// 自动映射为 wss:// 并补齐 /ws 路径", () => {
    expect(normalizeWsUrl("https://foo-bar.trycloudflare.com")).toBe(
      "wss://foo-bar.trycloudflare.com/ws",
    );
    expect(normalizeWsUrl("https://foo-bar.trycloudflare.com/")).toBe(
      "wss://foo-bar.trycloudflare.com/ws",
    );
    expect(normalizeWsUrl("https://foo-bar.trycloudflare.com/ws")).toBe(
      "wss://foo-bar.trycloudflare.com/ws",
    );
  });

  it("公网隧道带二维码参数时清理并保留标准 /ws 握手地址", () => {
    expect(
      normalizeWsUrl("https://foo-bar.trycloudflare.com/?code=123456&ws=wss://foo-bar.trycloudflare.com/ws"),
    ).toBe("wss://foo-bar.trycloudflare.com/ws");
  });

  it("wss:// 与 ws:// 地址如实保留并补齐 /ws", () => {
    expect(normalizeWsUrl("wss://foo-bar.trycloudflare.com")).toBe(
      "wss://foo-bar.trycloudflare.com/ws",
    );
    expect(normalizeWsUrl("ws://192.168.1.50:8765/ws")).toBe(
      "ws://192.168.1.50:8765/ws",
    );
    expect(normalizeWsUrl("http://192.168.1.50:8765")).toBe(
      "ws://192.168.1.50:8765/ws",
    );
  });
});

describe("resolveWsUrl", () => {
  it("?ws= 查询参数优先并写入缓存", () => {
    window.history.pushState({}, "", "/?ws=ws://192.168.1.5:8765/ws");
    expect(resolveWsUrl()).toBe("ws://192.168.1.5:8765/ws");
    window.history.pushState({}, "", "/");
    expect(resolveWsUrl()).toBe("ws://192.168.1.5:8765/ws");
  });

  it("公网隧道 https:// 地址在 ?ws= 或缓存中自动规范化为 wss://", () => {
    window.history.pushState({}, "", "/?ws=https://tunnel.trycloudflare.com");
    expect(resolveWsUrl()).toBe("wss://tunnel.trycloudflare.com/ws");
    window.history.pushState({}, "", "/");
    expect(resolveWsUrl()).toBe("wss://tunnel.trycloudflare.com/ws");
  });

  it("无参数无缓存时回退到当前站点 /ws", () => {
    expect(resolveWsUrl()).toBe(`ws://${window.location.host}/ws`);
  });
});

describe("凭证存储", () => {
  it("save/get/clear 闭环", () => {
    expect(getStoredToken()).toBeNull();
    saveCredentials("tok-1", "我的小米");
    expect(getStoredToken()).toBe("tok-1");
    expect(getStoredDeviceName()).toBe("我的小米");
    clearCredentials();
    expect(getStoredToken()).toBeNull();
  });

  it("配对写入和解绑清除会立即同步 Android 原生连接", () => {
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
  it("已配对请求自动携带 auth token", async () => {
    saveCredentials("tok-1", "我的小米");
    const client = new MobileWsClient();
    client.connect();
    const ws = lastInstance();
    ws.open();

    const pending = client.request("app.bootstrap");
    const frame = lastSentFrame(ws);
    expect(frame).toMatchObject({
      kind: "request",
      method: "app.bootstrap",
      auth: { token: "tok-1" },
    });
    ws.emit({ kind: "response", id: frame.id, ok: true, result: { sequence: 1 } });
    await expect(pending).resolves.toEqual({ sequence: 1 });
  });

  it("skipAuth（remote.pair）不携带 auth", async () => {
    saveCredentials("tok-old", "旧设备");
    const client = new MobileWsClient();
    client.connect();
    const ws = lastInstance();
    ws.open();

    const pending = client.request(
      "remote.pair",
      { code: "654321", device_name: "我的小米" },
      { skipAuth: true },
    );
    const frame = lastSentFrame(ws);
    expect(frame.method).toBe("remote.pair");
    expect(frame.auth).toBeUndefined();
    ws.emit({ kind: "response", id: frame.id, ok: true, result: { token: "tok-new" } });
    await expect(pending).resolves.toEqual({ token: "tok-new" });
  });

  it("unauthorized 响应如实拒绝并进入 auth_failed", async () => {
    saveCredentials("tok-expired", "我的小米");
    const client = new MobileWsClient();
    client.connect();
    const ws = lastInstance();
    ws.open();

    const pending = client.request("app.bootstrap");
    const frame = lastSentFrame(ws);
    ws.emit({
      kind: "response",
      id: frame.id,
      ok: false,
      error: { code: "unauthorized", message: "无效 token" },
    });
    const error = await pending.catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(RemoteCommandError);
    expect((error as RemoteCommandError).code).toBe("unauthorized");
    expect(client.getState()).toBe("auth_failed");
  });

  it("auth_failed: expired_token 响应清理本地失效 token 并记录细分错误码", async () => {
    saveCredentials("tok-expired-30d", "我的手机");
    const client = new MobileWsClient();
    client.connect();
    const ws = lastInstance();
    ws.open();

    const pending = client.request("app.bootstrap");
    const frame = lastSentFrame(ws);
    ws.emit({
      kind: "response",
      id: frame.id,
      ok: false,
      error: { code: "unauthorized", message: "expired_token" },
    });
    await expect(pending).rejects.toBeInstanceOf(RemoteCommandError);
    expect(client.getState()).toBe("auth_failed");
    expect(client.getAuthFailureCode()).toBe("expired_token");
    expect(getStoredToken()).toBeNull();
  });

  it("连接未就绪时请求如实失败", async () => {
    const client = new MobileWsClient();
    await expect(client.request("app.bootstrap")).rejects.toThrow("WebSocket 未连接");
  });

  it("事件帧分发给 onEvent 监听器", () => {
    const client = new MobileWsClient();
    const received: unknown[] = [];
    client.onEvent((event) => received.push(event));
    client.connect();
    const ws = lastInstance();
    ws.open();
    ws.emit({ kind: "event", event: "state.snapshot", sequence: 3, payload: {} });
    expect(received).toHaveLength(1);
    expect((received[0] as { event: string }).event).toBe("state.snapshot");
  });

  it("断线按退避重连，五次失败后进入 unreachable", () => {
    vi.useFakeTimers();
    const client = new MobileWsClient();
    client.connect();
    lastInstance().open();
    expect(client.getState()).toBe("connected");

    for (const delay of [1000, 2000, 4000, 8000, 16000]) {
      lastInstance().close();
      expect(client.getState()).toBe("reconnecting");
      vi.advanceTimersByTime(delay);
    }
    lastInstance().close();
    expect(client.getState()).toBe("unreachable");
  });

  it("主动 disconnect 不触发重连", () => {
    vi.useFakeTimers();
    const client = new MobileWsClient();
    client.connect();
    lastInstance().open();
    client.disconnect();
    expect(client.getState()).toBe("disconnected");
    vi.advanceTimersByTime(60000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(client.getState()).toBe("disconnected");
  });
});

describe("MobileWsClient 心跳（V0.3.8 T1 契约 §14.3）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("连接后每 15s 发一次 ping，30s 无入站即判半开主动断开重连", () => {
    saveCredentials("tok-hb", "设备");
    const client = new MobileWsClient();
    client.connect();
    const ws = lastInstance();
    ws.open();
    expect(client.getState()).toBe("connected");

    vi.advanceTimersByTime(PING_INTERVAL_MS);
    expect(lastSentFrame(ws).method).toBe("ping");

    // 收到入站消息刷新活性时间戳；超过 INBOUND_STALE_MS 无人应答才判死
    vi.advanceTimersByTime(PING_INTERVAL_MS);
    expect(lastSentFrame(ws).method).toBe("ping");

    // 30s 无入站：下一个心跳 tick 判定半开并主动 close → 走重连
    vi.advanceTimersByTime(PING_INTERVAL_MS + INBOUND_STALE_MS);
    const closedSent = ws.sent.some(
      (raw) => (JSON.parse(raw) as { method?: string }).method === "ping",
    );
    expect(closedSent).toBe(true);
    expect(client.getState()).toBe("reconnecting");
  });

  it("持续有入站消息不误判半开", () => {
    saveCredentials("tok-hb", "设备");
    const client = new MobileWsClient();
    client.connect();
    const ws = lastInstance();
    ws.open();

    for (let i = 0; i < 8; i += 1) {
      vi.advanceTimersByTime(PING_INTERVAL_MS);
      ws.emit({
        kind: "event",
        event: "queue.changed",
        sequence: i,
        payload: {},
      });
    }
    expect(client.getState()).toBe("connected");
    const pingCount = ws.sent.filter(
      (raw) => (JSON.parse(raw) as { method?: string }).method === "ping",
    ).length;
    expect(pingCount).toBeGreaterThanOrEqual(7);
  });
});

describe("MobileWsClient 回前台重同步（V0.3.8 T1 契约 §14.4）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("unreachable 终态回前台自动复位重连，不再永久停摆", () => {
    saveCredentials("tok-fg", "设备");
    const client = new MobileWsClient();
    client.connect();
    let ws = lastInstance();
    ws.open();
    ws.close();
    // 连续 5 次"连接失败"（新连接不 open 即 close）耗尽退避 → unreachable。
    // onopen 成功会重置退避计数，因此这里绝不 open。
    for (let i = 0; i < 5; i += 1) {
      vi.advanceTimersByTime(16000);
      ws = lastInstance();
      ws.close();
    }
    expect(client.getState()).toBe("unreachable");

    expect(client.notifyAppForeground()).toBe("reconnecting");
    expect(client.getState()).toBe("connecting");
  });

  it("connected 时回前台返回 resync（由调用方重新 bootstrap 补拉）", () => {
    saveCredentials("tok-fg", "设备");
    const client = new MobileWsClient();
    client.connect();
    lastInstance().open();
    expect(client.notifyAppForeground()).toBe("resync");
  });

  it("connecting/reconnecting 时回前台返回 none（维持既有流程）", () => {
    saveCredentials("tok-fg", "设备");
    const client = new MobileWsClient();
    client.connect();
    expect(client.notifyAppForeground()).toBe("none");
  });
});
