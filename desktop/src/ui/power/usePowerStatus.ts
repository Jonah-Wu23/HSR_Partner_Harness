import { useEffect, useRef } from "react";

import type { HarnessActions } from "../../contracts/actions";
import { desktopStore } from "../../stores/desktopStore";

/** 主动查询 power.get_status 并写入 store 电源切片。
    成功 → setPowerStatus（清旧错误）；失败 → setPowerError 保留原始错误。
    power.status_changed 事件由 AppController 统一送进 applyEvents，这里不重复订阅。
    actions 缺省时不发起查询，只消费 store 既有状态。 */
export function usePowerStatusQuery(actions: HarnessActions | undefined): void {
  const actionsRef = useRef(actions);
  actionsRef.current = actions;

  useEffect(() => {
    const current = actionsRef.current;
    if (!current) return;
    let cancelled = false;
    desktopStore.getState().setPowerQueryInFlight(true);
    current
      .powerGetStatus()
      .then((payload) => {
        if (cancelled) return;
        desktopStore.getState().setPowerStatus(payload);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        desktopStore
          .getState()
          .setPowerError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (cancelled) return;
        desktopStore.getState().setPowerQueryInFlight(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
}
