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
 * scenario 取 mocks/scenarios 的 16 个场景名；mode/theme 为可选覆写。
 */
const params = new URLSearchParams(window.location.search);
const requested = params.get("scenario") ?? "single-project";
const scenario: MockScenarioName = (MOCK_SCENARIO_NAMES as string[]).includes(requested)
  ? (requested as MockScenarioName)
  : "single-project";
const modeOverride = params.get("mode");
const themeOverride = params.get("theme");

const backend = new MockDesktopBackend(scenario);
const controller = createActionController(backend);

function PreviewApp() {
  const [, setTick] = useState(0);

  useEffect(() => desktopStore.subscribe(() => setTick((tick) => tick + 1)), []);

  useEffect(() => {
    void (async () => {
      await controller.loadBootstrap();
      if (modeOverride === "chat" || modeOverride === "collaboration") {
        controller.actions.switchMode(modeOverride);
      }
      if (themeOverride === "dark" || themeOverride === "light") {
        controller.actions.switchTheme(themeOverride);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <AppShell vm={presentAppShell(desktopStore.getState())} actions={controller.actions} />;
}

createRoot(document.getElementById("root")!).render(<PreviewApp />);
