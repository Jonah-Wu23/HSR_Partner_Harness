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
});
