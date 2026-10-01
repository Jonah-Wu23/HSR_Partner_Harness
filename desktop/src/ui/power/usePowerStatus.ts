import { useEffect } from "react";

import type { HarnessActions } from "../../contracts/actions";
import { desktopStore } from "../../stores/desktopStore";

/** 挂载时查询 power.get_status 并写入 store 电源切片。
    成功 → setPowerStatus（清旧错误）；失败 → setPowerError 保留原始错误。
    结果写入全局 store，组件卸载后仍然写入。
    power.status_changed 事件由 AppController 统一送进 applyEvents。 */
export function usePowerStatusQuery(actions: HarnessActions): void {
  useEffect(() => {
    const store = desktopStore.getState();
    store.setPowerQueryInFlight(true);
    actions
      .powerGetStatus()
      .then(
        (payload) => desktopStore.getState().setPowerStatus(payload),
        (error: unknown) =>
          desktopStore
            .getState()
            .setPowerError(error instanceof Error ? error.message : String(error)),
      )
      .finally(() => desktopStore.getState().setPowerQueryInFlight(false));
  }, [actions]);
}
