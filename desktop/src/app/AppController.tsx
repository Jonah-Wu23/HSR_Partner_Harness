import { useEffect, useRef } from "react";
import { useShallow } from "zustand/react/shallow";

import type { HarnessActions } from "../contracts/actions";
import type { DesktopBackend } from "../services/backend";
import { createEventBatcher } from "../services/eventBatcher";
import { presentAppShell } from "../presenters/presenters";
import {
  desktopStore,
  selectDesktopRenderState,
  useDesktopStore,
} from "../stores/desktopStore";
import { AppShell } from "../ui/AppShell";

interface AppControllerProps {
  backend: DesktopBackend;
  actions: HarnessActions;
  loadBootstrap: () => Promise<void>;
}

export function AppController({ backend, actions, loadBootstrap }: AppControllerProps) {
  const recoveringRef = useRef(false);
  const storeState = useDesktopStore(useShallow(selectDesktopRenderState));

  useEffect(() => {
    const batcher = createEventBatcher((events) => {
      desktopStore.getState().applyEvents(events);
      if (desktopStore.getState().needsBootstrap && !recoveringRef.current) {
        recoveringRef.current = true;
        void loadBootstrap().finally(() => {
          recoveringRef.current = false;
        });
      }
    });
    const unsubscribe = backend.subscribe(batcher.push);
    const stopPushToTalkOnBlur = () => {
      void actions.stopPushToTalk();
    };
    window.addEventListener("blur", stopPushToTalkOnBlur);
    void loadBootstrap();
    return () => {
      unsubscribe();
      batcher.dispose();
      window.removeEventListener("blur", stopPushToTalkOnBlur);
    };
  }, [actions, backend, loadBootstrap]);

  const viewModel = presentAppShell(storeState);

  return <AppShell vm={viewModel} actions={actions} />;
}
