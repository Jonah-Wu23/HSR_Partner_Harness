import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppController } from "./app/AppController";
import { createActionController } from "./services/actions";
import type { DesktopBackend } from "./services/backend";
import { MockDesktopBackend } from "./services/mockDesktopBackend";
import { TauriDesktopBackend } from "./services/tauriDesktopBackend";

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

const backend: DesktopBackend = isTauriRuntime()
  ? new TauriDesktopBackend()
  : new MockDesktopBackend("single-project");
const controller = createActionController(backend);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppController
      backend={backend}
      actions={controller.actions}
      loadBootstrap={controller.loadBootstrap}
    />
  </StrictMode>,
);
