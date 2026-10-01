import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { AppShell } from "../AppShell";
import type { MockScenarioName } from "../../mocks/scenarios";
import { MOCK_SCENARIO_NAMES } from "../../mocks/scenarios";
import { presentAppShell } from "../../presenters/presenters";
import { createActionController } from "../../services/actions";
import { MockDesktopBackend } from "../../services/mockDesktopBackend";
import { desktopStore } from "../../stores/desktopStore";

/**
 * 视觉预览入口（仅 dev server 手工打开 /preview.html 使用，不进生产包）：
 *   /preview.html?scenario=collaboration-running&mode=collaboration&theme=dark
 * scenario 取 mocks/scenarios 的 MOCK_SCENARIO_NAMES，缺省为 single-project；
 * mode/theme 为可选覆写。参数值不合法时抛错。
 */
const params = new URLSearchParams(window.location.search);

function enumParam<T extends string>(name: string, allowed: readonly T[]): T | null {
  const value = params.get(name);
  if (value === null) return null;
  if (!(allowed as readonly string[]).includes(value)) {
    throw new Error(`preview 参数 ${name}=${value} 不合法，可选值：${allowed.join(", ")}`);
  }
  return value as T;
}

const scenario: MockScenarioName = enumParam("scenario", MOCK_SCENARIO_NAMES) ?? "single-project";
const modeOverride = enumParam("mode", ["chat", "collaboration"] as const);
const themeOverride = enumParam("theme", ["dark", "light"] as const);

const backend = new MockDesktopBackend(scenario);
const controller = createActionController(backend);

function PreviewApp() {
  const [, setTick] = useState(0);

  useEffect(() => desktopStore.subscribe(() => setTick((tick) => tick + 1)), []);

  useEffect(() => {
    void (async () => {
      await controller.loadBootstrap();
      if (modeOverride) controller.actions.switchMode(modeOverride);
      if (themeOverride) controller.actions.switchTheme(themeOverride);
    })();
  }, []);

  return (
    <AppShell
      vm={presentAppShell(desktopStore.getState())}
      actions={controller.actions}
      backend={backend}
    />
  );
}

createRoot(document.getElementById("root")!).render(<PreviewApp />);
