import { beforeEach, describe, expect, it } from "vitest";

import type { DesktopCommand, DesktopEvent } from "../contracts/protocol";
import { createMockScenario } from "../mocks/scenarios";
import { desktopStore } from "../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../test/fakeBackend";
import { createActionController } from "./actions";
import { MockDesktopBackend } from "./mockDesktopBackend";

beforeEach(() => {
  desktopStore.setState(desktopStore.getInitialState(), true);
  desktopStore.getState().hydrate(createMockScenario("single-project").snapshot);
});

function respondTo(results: Record<string, unknown>) {
  return (command: DesktopCommand) =>
    command.method in results ? results[command.method] : unexpectedCommand(command);
}

describe("远程设备页命令", () => {
  it.each([
    [
      "局域网接入地址",
      { host: "192.168.1.42", port: 8765, mode: "lan", tls: false },
      {
        serveAddress: { host: "192.168.1.42", port: 8765, mode: "lan", tls: false },
        servePort: 8765,
        serveUnavailableReason: null,
      },
    ],
    [
      "已监听但没有局域网地址",
      { host: null, port: 8765, mode: "lan", tls: false, reason: "no_lan_address" },
      { serveAddress: null, servePort: 8765, serveUnavailableReason: "no_lan_address" },
    ],
    [
      "远程服务未监听（null）",
      null,
      { serveAddress: null, servePort: null, serveUnavailableReason: null },
    ],
  ])("remote.issue_code 带%s时写入配对码与对应的接入状态", async (_name, serveAddress, expected) => {
    const { backend } = fakeBackend(
      respondTo({
        "remote.issue_code": { code: "659304", ttl_seconds: 300, serve_address: serveAddress },
      }),
    );
    const { actions } = createActionController(backend);

    await actions.issuePairingCode();

    expect(desktopStore.getState().remotePairing).toMatchObject({
      code: "659304",
      ttlSeconds: 300,
      loading: false,
      serveFailure: null,
      ...expected,
    });
  });

  it("listRemoteDevices 把设备记录映射为视图字段", async () => {
    const { backend } = fakeBackend(
      respondTo({
        "remote.list_devices": {
          devices: [
            {
              device_name: "iPhone 16",
              issued_at: "2026-09-11T12:00:00+00:00",
              last_used_at: "2026-09-11T12:01:00+00:00",
              expires_at: "2026-09-18T12:01:00+00:00",
              revoked: false,
            },
          ],
        },
      }),
    );
    const { actions } = createActionController(backend);

    await actions.listRemoteDevices();

    expect(desktopStore.getState().remotePairing.devices).toEqual([
      {
        deviceName: "iPhone 16",
        issuedAt: "2026-09-11T12:00:00+00:00",
        lastUsedAt: "2026-09-11T12:01:00+00:00",
        expiresAt: "2026-09-18T12:01:00+00:00",
        revoked: false,
      },
    ]);
  });

  it("tunnelStart 先记为启动中，queryTunnelStatus 按查询结果写入隧道状态", async () => {
    const { backend } = fakeBackend(
      respondTo({
        "remote.tunnel_start": { status: "starting" },
        "remote.tunnel_status": {
          state: "ready",
          public_url: "https://actions-test.trycloudflare.com",
          hostname: "actions-test.trycloudflare.com",
          error: null,
        },
      }),
    );
    const { actions } = createActionController(backend);

    await actions.tunnelStart();
    expect(desktopStore.getState().remotePairing.tunnel).toMatchObject({
      state: "starting",
      loading: true,
    });

    await actions.queryTunnelStatus();
    expect(desktopStore.getState().remotePairing.tunnel).toMatchObject({
      state: "ready",
      publicUrl: "https://actions-test.trycloudflare.com",
      loading: false,
    });
  });

  it("远程服务未监听时 tunnelStart 如实失败，隧道记为失败并保留原因", async () => {
    const backend = new MockDesktopBackend("single-project");
    const { actions } = createActionController(backend);

    await expect(actions.tunnelStart()).rejects.toMatchObject({ code: "serve_not_started" });
    expect(desktopStore.getState().remotePairing.tunnel).toMatchObject({
      state: "failed",
      error: "远程服务未启动（--serve 未监听或端口被占用），无法开启公网接入",
      loading: false,
    });
  });
});

describe("远程配对与隧道事件", () => {
  const tunnelEvent = (
    sequence: number,
    event: "tunnel.started" | "tunnel.failed" | "tunnel.stopped",
    payload: Record<string, unknown>,
    streamId?: string,
  ): DesktopEvent => ({
    kind: "event",
    event,
    sequence,
    payload,
    ...(streamId ? { stream_id: streamId } : {}),
  });
  const tunnel = () => desktopStore.getState().remotePairing.tunnel;

  it("tunnel.started、tunnel.failed、tunnel.stopped 依次把隧道置为就绪、失败与关闭", () => {
    desktopStore.getState().applyEvents([
      tunnelEvent(1, "tunnel.started", {
        public_url: "https://event-test.trycloudflare.com",
        hostname: "event-test.trycloudflare.com",
      }),
    ]);
    expect(tunnel()).toMatchObject({
      state: "ready",
      publicUrl: "https://event-test.trycloudflare.com",
    });

    desktopStore.getState().applyEvents([
      tunnelEvent(2, "tunnel.failed", { error: "隧道进程已被外部终止 (退出码 1)" }),
    ]);
    expect(tunnel()).toMatchObject({
      state: "failed",
      error: "隧道进程已被外部终止 (退出码 1)",
      publicUrl: null,
    });

    desktopStore.getState().applyEvents([
      tunnelEvent(3, "tunnel.stopped", { reason: "user_requested" }),
    ]);
    expect(tunnel()).toMatchObject({ state: "off", error: null, publicUrl: null });
  });

  it("旧连接代次迟到的 tunnel.failed 不覆盖当前隧道状态", () => {
    desktopStore.setState({ streamId: "2" });
    desktopStore.getState().applyEvents([
      tunnelEvent(3, "tunnel.failed", { error: "旧代次迟到事件" }, "1"),
    ]);
    expect(tunnel().state).toBe("off");
  });

  it("手机配对成功后配对码作废，devicesRevision 递增供面板重拉设备列表", async () => {
    const backend = new MockDesktopBackend("single-project");
    const { actions } = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      for (const [deviceName, revision] of [
        ["我的手机", 1],
        ["第二台", 2],
      ] as const) {
        await actions.issuePairingCode();
        const code = desktopStore.getState().remotePairing.code;
        // 手机端经 Sidecar 的 remote.pair 认领配对码，Sidecar 随即广播 remote.paired。
        await backend.request({
          kind: "request",
          id: `pair-${revision}`,
          method: "remote.pair",
          params: { code, device_name: deviceName },
        });
        expect(desktopStore.getState().remotePairing).toMatchObject({
          code: null,
          issuedAtEpochMs: null,
          devicesRevision: revision,
        });
      }
    } finally {
      unsubscribe();
    }
  });
});
