import { useEffect, useRef } from "react";

import type { HarnessActions } from "../../contracts/actions";
import { desktopStore } from "../../stores/desktopStore";

/** V0.3.7 U5：主动 power.get_status 查询并写入 store 电源切片。
    成功 → setPowerStatus（清旧错误）；失败 → setPowerError 保留原始错误，不伪造成功。
    事件路径（power.status_changed）由 AppController 统一进 applyEvents，不在此重复订阅。
    actions 可能缺省（如旧测试装配），此时不发起查询，只消费 store 既有状态。 */
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
