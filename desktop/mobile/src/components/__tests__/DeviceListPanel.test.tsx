import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DeviceListPanel } from "../DeviceListPanel";
import type { RemoteDevice } from "@shared/contracts/protocol";

describe("DeviceListPanel 组件", () => {
  afterEach(() => {
    cleanup();
  });

  it("loading 态展示读取中提示且刷新按钮禁用", () => {
    render(
      <DeviceListPanel
        devices={null}
        currentDeviceName="我的手机"
        loading={true}
        error={null}
        revokingDeviceName={null}
        revokeError={null}
        onRefresh={vi.fn()}
        onRevoke={vi.fn()}
      />,
    );
    expect(screen.getByTestId("device-list-unknown")).toHaveTextContent("正在读取设备列表…");
    const btn = screen.getByTestId("btn-refresh-devices");
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("读取中…");
  });

  it("读取失败时展示原始错误（不吞异常、不合成成功）", () => {
    render(
      <DeviceListPanel
        devices={null}
        currentDeviceName="我的手机"
        loading={false}
        error="[unauthorized] 设备凭据已失效"
        revokingDeviceName={null}
        revokeError={null}
        onRefresh={vi.fn()}
        onRevoke={vi.fn()}
      />,
    );
    expect(screen.getByTestId("device-list-error")).toHaveTextContent(
      "[unauthorized] 设备凭据已失效",
    );
  });

  it("devices === [] 时显示空列表提示", () => {
    render(
      <DeviceListPanel
        devices={[]}
        currentDeviceName="我的手机"
        loading={false}
        error={null}
        revokingDeviceName={null}
        revokeError={null}
        onRefresh={vi.fn()}
        onRevoke={vi.fn()}
      />,
    );
    expect(screen.getByTestId("device-list-empty")).toHaveTextContent(
      "还没有已配对的设备。",
    );
  });

  it("正常渲染设备行：区分当前设备与已撤销设备，点击撤销触发 onRevoke", () => {
    const onRevoke = vi.fn();
    const onRefresh = vi.fn();
    const devices: RemoteDevice[] = [
      {
        device_name: "本机手机",
        issued_at: "2026-09-01T10:00:00Z",
        last_used_at: "2026-09-09T18:00:00Z",
        revoked: false,
      },
      {
        device_name: "旧平板",
        issued_at: "2026-08-01T10:00:00Z",
        last_used_at: "2026-08-15T12:00:00Z",
        revoked: true,
      },
    ];

    render(
      <DeviceListPanel
        devices={devices}
        currentDeviceName="本机手机"
        loading={false}
        error={null}
        revokingDeviceName={null}
        revokeError={null}
        onRefresh={onRefresh}
        onRevoke={onRevoke}
      />,
    );

    // 当前设备徽标
    expect(screen.getByTestId("device-current-本机手机")).toBeInTheDocument();
    expect(screen.queryByTestId("device-revoked-本机手机")).toBeNull();

    // 旧平板已撤销
    expect(screen.getByTestId("device-revoked-旧平板")).toBeInTheDocument();
    const revokeBtnOld = screen.getByTestId("btn-revoke-旧平板");
    expect(revokeBtnOld).toBeDisabled();
    expect(revokeBtnOld).toHaveTextContent("已撤销");

    // 点击撤销未撤销设备
    const revokeBtnCurrent = screen.getByTestId("btn-revoke-本机手机");
    expect(revokeBtnCurrent).not.toBeDisabled();
    fireEvent.click(revokeBtnCurrent);
    expect(onRevoke).toHaveBeenCalledWith("本机手机");

    // 点击刷新
    fireEvent.click(screen.getByTestId("btn-refresh-devices"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("撤销进行中与撤销失败状态如实呈现", () => {
    const devices: RemoteDevice[] = [
      {
        device_name: "进行中设备",
        issued_at: "2026-09-01T10:00:00Z",
        last_used_at: "2026-09-09T18:00:00Z",
        revoked: false,
      },
    ];

    render(
      <DeviceListPanel
        devices={devices}
        currentDeviceName="另一设备"
        loading={false}
        error={null}
        revokingDeviceName="进行中设备"
        revokeError="撤销失败：网络连接超时"
        onRefresh={vi.fn()}
        onRevoke={vi.fn()}
      />,
    );

    const btn = screen.getByTestId("btn-revoke-进行中设备");
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("撤销中…");

    expect(screen.getByTestId("device-revoke-error")).toHaveTextContent(
      "撤销失败：网络连接超时",
    );
  });
});
