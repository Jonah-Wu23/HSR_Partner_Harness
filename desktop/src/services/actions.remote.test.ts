import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopCommand, DesktopEvent } from "../contracts/protocol";
import { desktopStore } from "../stores/desktopStore";
import type { DesktopBackend } from "./backend";
import { createActionController } from "./actions";

function fakeBackend(respond: (command: DesktopCommand) => unknown): DesktopBackend {
  return {
    async request<T>(command: DesktopCommand): Promise<T> {
      return respond(command) as T;
    },
    openChatWindow: vi.fn(),
    pickFolder: vi.fn(),
    pickFile: vi.fn(),
    saveFile: vi.fn(),
    subscribe: (_listener: (event: DesktopEvent) => void) => () => {},
    reconnectSidecar: vi.fn(),
  } as unknown as DesktopBackend;
}

describe("远程设备页服务地址（V039-S4-004）", () => {
  beforeEach(() => {
    desktopStore.setState({
      status: "ready",
      needsBootstrap: false,
      lastSequence: -1,
      streamId: null,
      eventBuffer: [],
      remotePairing: {
        code: null,
        ttlSeconds: 300,
        issuedAtEpochMs: null,
        devices: [],
        loading: false,
        error: null,
        serveAddress: null,
        servePort: null,
        serveUnavailableReason: null,
        serveFailure: null,
        tunnel: {
          state: "off",
          publicUrl: null,
          hostname: null,
          error: null,
          loading: false,
        },
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("remote.issue_code 返回 serve_address 时按真实地址生成二维码依据", async () => {
    const backend = fakeBackend((command) => {
      if (command.method === "remote.issue_code") {
        return {
          code: "659304",
          ttl_seconds: 300,
          serve_address: { host: "192.168.1.42", port: 8765 },
        };
      }
      return {};
    });
    const { actions } = createActionController(backend);

    await actions.issuePairingCode();

    const remote = desktopStore.getState().remotePairing;
    expect(remote.code).toBe("659304");
    expect(remote.serveAddress).toEqual({ host: "192.168.1.42", port: 8765 });
    expect(remote.serveFailure).toBeNull();
  });

  it("serve_address 上报 host=null 时保留真实端口与原因码，不生成不可达地址", async () => {
    const backend = fakeBackend(() => ({
      code: "659304",
      ttl_seconds: 300,
      serve_address: { host: null, port: 8765, reason: "no_lan_address" },
    }));
    const { actions } = createActionController(backend);

    await actions.issuePairingCode();

    const remote = desktopStore.getState().remotePairing;
    expect(remote.serveAddress).toBeNull();
    expect(remote.servePort).toBe(8765);
    expect(remote.serveUnavailableReason).toBe("no_lan_address");
  });

  it("返回体未带 serve_address 时保持既有状态，不覆盖已收到的地址", async () => {
    desktopStore.getState().setServeAddress({ host: "192.168.1.7", port: 8765 });
    const backend = fakeBackend(() => ({ code: "659304", ttl_seconds: 300 }));
    const { actions } = createActionController(backend);

    await actions.issuePairingCode();

    expect(desktopStore.getState().remotePairing.serveAddress).toEqual({
      host: "192.168.1.7",
      port: 8765,
    });
  });

  it("listRemoteDevices 映射设备 expiresAt 字段", async () => {
    const backend = fakeBackend(() => ({
      devices: [
        {
          device_name: "iPhone 16",
          issued_at: "2026-09-11T12:00:00Z",
          last_used_at: "2026-09-11T12:01:00Z",
          expires_at: "2026-09-18T12:01:00Z",
          revoked: false,
        },
      ],
    }));
    const { actions } = createActionController(backend);

    await actions.listRemoteDevices();

    const devices = desktopStore.getState().remotePairing.devices;
    expect(devices).toHaveLength(1);
    expect(devices[0].deviceName).toBe("iPhone 16");
    expect(devices[0].expiresAt).toBe("2026-09-18T12:01:00Z");
  });

  it("tunnelStart 与 queryTunnelStatus 正确派发并写入 store", async () => {
    const backend = fakeBackend((cmd) => {
      if (cmd.method === "remote.tunnel_start") {
        return { status: "starting" };
      }
      if (cmd.method === "remote.tunnel_status") {
        return {
          state: "ready",
          public_url: "https://actions-test.trycloudflare.com",
          hostname: "actions-test.trycloudflare.com",
          error: null,
        };
      }
      return {};
    });
    const { actions } = createActionController(backend);

    await actions.tunnelStart();
    expect(desktopStore.getState().remotePairing.tunnel?.state).toBe("starting");

    await actions.queryTunnelStatus();
    expect(desktopStore.getState().remotePairing.tunnel?.state).toBe("ready");
    expect(desktopStore.getState().remotePairing.tunnel?.publicUrl).toBe("https://actions-test.trycloudflare.com");
  });

  it("tunnel 事件流正确驱动 store 五态变更", () => {
    // 初始状态
    expect(desktopStore.getState().remotePairing.tunnel?.state).toBe("off");

    // tunnel.started 事件
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "tunnel.started",
        sequence: 1,
        payload: {
          public_url: "https://event-test.trycloudflare.com",
          hostname: "event-test.trycloudflare.com",
        },
      },
    ]);
    expect(desktopStore.getState().remotePairing.tunnel?.state).toBe("ready");
    expect(desktopStore.getState().remotePairing.tunnel?.publicUrl).toBe("https://event-test.trycloudflare.com");

    // tunnel.failed 事件
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "tunnel.failed",
        sequence: 2,
        payload: {
          error: "进程异常退出",
        },
      },
    ]);
    expect(desktopStore.getState().remotePairing.tunnel?.state).toBe("failed");
    expect(desktopStore.getState().remotePairing.tunnel?.error).toBe("进程异常退出");

    // tunnel.stopped 事件
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "tunnel.stopped",
        sequence: 3,
        payload: {
          reason: "user_requested",
        },
      },
    ]);
    expect(desktopStore.getState().remotePairing.tunnel?.state).toBe("off");
    expect(desktopStore.getState().remotePairing.tunnel?.publicUrl).toBeNull();
  });
});
