import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearCredentials,
  getStoredDeviceName,
  getStoredToken,
  MobileWsClient,
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

describe("resolveWsUrl", () => {
  it("?ws= 查询参数优先并写入缓存", () => {
    window.history.pushState({}, "", "/?ws=ws://192.168.1.5:8765/ws");
    expect(resolveWsUrl()).toBe("ws://192.168.1.5:8765/ws");
    window.history.pushState({}, "", "/");
    expect(resolveWsUrl()).toBe("ws://192.168.1.5:8765/ws");
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
