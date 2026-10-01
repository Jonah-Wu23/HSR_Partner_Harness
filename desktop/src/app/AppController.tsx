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
  /** conversation.open 装载，独立聊天窗口启动时使用。 */
  conversationOpen: (conversationId: string) => Promise<void>;
  /** 独立聊天窗口启动 URL 携带的会话 id；主窗口为 null。 */
  initialConversationId: string | null;
}

export function AppController({
  backend,
  actions,
  loadBootstrap,
  conversationOpen,
  initialConversationId,
}: AppControllerProps) {
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
    // 窗口失焦时结束进行中的按键说话，没有按键说话时不发请求。
    const stopPushToTalkOnBlur = () => {
      if (desktopStore.getState().voice.ptt) void actions.stopPushToTalk();
    };
    window.addEventListener("blur", stopPushToTalkOnBlur);
    const booting = loadBootstrap();
    if (initialConversationId) {
      // 独立聊天窗口：bootstrap 拿到账号目录后，按 URL 参数只读装载目标聊天并打开其标签；
      // 失败由请求层提示。
      void booting.then(() => conversationOpen(initialConversationId));
    }
    return () => {
      unsubscribe();
      batcher.dispose();
      window.removeEventListener("blur", stopPushToTalkOnBlur);
    };
  }, [actions, backend, loadBootstrap, conversationOpen, initialConversationId]);

  const viewModel = presentAppShell(storeState);

  return <AppShell vm={viewModel} actions={actions} backend={backend} />;
}
