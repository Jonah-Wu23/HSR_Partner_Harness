import { useEffect, useRef } from "react";

import type { HarnessActions } from "../contracts/actions";
import type { DesktopBackend } from "../services/backend";
import { createEventBatcher } from "../services/eventBatcher";
import { presentAppShell } from "../presenters/presenters";
import { desktopStore, useDesktopStore } from "../stores/desktopStore";

interface AppControllerProps {
  backend: DesktopBackend;
  actions: HarnessActions;
  loadBootstrap: () => Promise<void>;
}

const EMPTY_MESSAGE_IDS: string[] = [];

export function AppController({ backend, actions, loadBootstrap }: AppControllerProps) {
  const recoveringRef = useRef(false);
  const status = useDesktopStore((state) => state.status);
  const theme = useDesktopStore((state) => state.theme);
  const currentProjectId = useDesktopStore((state) => state.currentProjectId);
  const currentConversationId = useDesktopStore((state) => state.currentConversationId);
  const busy = useDesktopStore((state) => state.busy);
  const messageIds = useDesktopStore(
    (state) => state.messageIdsByConversation[state.currentConversationId] ?? EMPTY_MESSAGE_IDS,
  );
  const activePair = useDesktopStore((state) => state.pair);
  const error = useDesktopStore((state) => state.error);

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

  const viewModel = presentAppShell(desktopStore.getState());
  const projectName = viewModel.navigation?.projects.find(
    (project) => project.project_id === currentProjectId,
  )?.name;

  return (
    <main data-testid="app-shell" data-theme={theme} data-status={status}>
      <header>
        <h1>HSR Partner Harness</h1>
        <p data-testid="pair-name">{activePair?.character.name ?? "正在连接"} × {activePair?.assistant.name ?? ""}</p>
      </header>
      <section aria-label="迁移骨架状态">
        <p data-testid="backend-status">后端状态：{status}</p>
        <p data-testid="project-name">项目：{projectName ?? "暂无项目"}</p>
        <p data-testid="conversation-id">聊天：{currentConversationId || "暂无聊天"}</p>
        <p data-testid="message-count">消息：{messageIds.length}</p>
        <p data-testid="task-status">任务：{busy ? "运行中" : "空闲"}</p>
        {error ? <p role="alert">{error}</p> : null}
      </section>
      <section aria-label="逻辑骨架动作">
        <button type="button" onClick={() => actions.switchMode("chat")}>聊天模式</button>
        <button type="button" onClick={() => actions.switchMode("collaboration")}>协作模式</button>
        <button type="button" onClick={() => actions.switchTheme(theme === "dark" ? "light" : "dark")}>
          切换主题
        </button>
      </section>
    </main>
  );
}
