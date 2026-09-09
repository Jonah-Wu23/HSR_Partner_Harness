import { useCallback, useEffect, useRef, useState } from "react";
import type {
  RemoteDevice,
  RemoteListDevicesResult,
  RemoteRevokeResult,
} from "@shared/contracts/protocol";
import { mobileWsClient } from "../../lib/mobileStore";

/**
 * V0.3.9 V06：远程设备数据适配层（组件内适配，store 归逻辑轨）。
 *
 * 协议依据：`remote.list_devices`（无参数，返回 { devices }）与
 * `remote.revoke`（参数 { device_name }，按设备名撤销其全部 token）已存在于
 * desktop/src/contracts/protocol.ts 与 Sidecar 命令表。
 *
 * 待真实接线：mobileStore 目前没有 remote.* 的 action/状态，因此本层直接调用冻结命令，
 * 结果与错误都只放在组件局部状态里。逻辑轨补齐 store 后（见交付报告跨轨需求），
 * 本文件是唯一需要改动的接线点：把 request 换成 store action，props 形状不变。
 *
 * 失败处理：所有错误保留 error.code 与原始 message 后如实抛出到 UI，不吞异常、
 * 不把失败写成空列表。
 */

function describeError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (error && typeof error === "object" && "code" in error) {
    const code = String((error as { code?: unknown }).code ?? "");
    if (code) return `[${code}] ${message}`;
  }
  return message;
}

export interface RemoteDevicesController {
  /** null = 尚未取得列表；空数组 = 服务端确认没有设备。 */
  devices: RemoteDevice[] | null;
  loading: boolean;
  /** 读取失败原文（含 error.code）。 */
  error: string | null;
  revokingDeviceName: string | null;
  revokeError: string | null;
  refresh: () => void;
  revoke: (deviceName: string) => void;
}

export function useRemoteDevices(autoLoad: boolean): RemoteDevicesController {
  const [devices, setDevices] = useState<RemoteDevice[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revokingDeviceName, setRevokingDeviceName] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback((): void => {
    setLoading(true);
    setError(null);
    void mobileWsClient
      .request<RemoteListDevicesResult>("remote.list_devices", {})
      .then((result) => {
        if (!mountedRef.current) return;
        const list = result?.devices;
        if (!Array.isArray(list)) {
          // 结构不符时不伪造空列表：如实报告协议异常。
          setError("remote.list_devices 返回结构异常：缺少 devices 数组");
          return;
        }
        setDevices(list);
      })
      .catch((err: unknown) => {
        if (!mountedRef.current) return;
        setError(describeError(err));
      })
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
  }, []);

  const revoke = useCallback(
    (deviceName: string): void => {
      setRevokingDeviceName(deviceName);
      setRevokeError(null);
      void mobileWsClient
        .request<RemoteRevokeResult>("remote.revoke", { device_name: deviceName })
        .then(() => {
          if (!mountedRef.current) return;
          refresh();
        })
        .catch((err: unknown) => {
          if (!mountedRef.current) return;
          setRevokeError(describeError(err));
        })
        .finally(() => {
          if (mountedRef.current) setRevokingDeviceName(null);
        });
    },
    [refresh],
  );

  useEffect(() => {
    if (autoLoad) refresh();
  }, [autoLoad, refresh]);

  return { devices, loading, error, revokingDeviceName, revokeError, refresh, revoke };
}
