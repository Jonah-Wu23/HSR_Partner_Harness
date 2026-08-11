import { useEffect } from "react";

import type { HarnessActions } from "../contracts/actions";
import type { DesktopBackend } from "../services/backend";
import { createEventBatcher } from "../services/eventBatcher";
import { presentAppShell } from "../presenters/presenters";
import { desktopStore, useDesktopStore } from "../stores/desktopStore";
import { AppShell } from "../ui/AppShell";

interface AppControllerProps {
  backend: DesktopBackend;
  actions: HarnessActions;
  loadBootstrap: () => Promise<void>;
}

export function AppController({ backend, actions, loadBootstrap }: AppControllerProps) {
  const storeState = useDesktopStore((state) => state);

  useEffect(() => {
    const batcher = createEventBatcher((events) => desktopStore.getState().applyEvents(events));
    const unsubscribe = backend.subscribe(batcher.push);
    void loadBootstrap();
    return () => {
      unsubscribe();
      batcher.dispose();
    };
  }, [backend, loadBootstrap]);

  const viewModel = presentAppShell(storeState);

  return <AppShell vm={viewModel} actions={actions} />;
}
