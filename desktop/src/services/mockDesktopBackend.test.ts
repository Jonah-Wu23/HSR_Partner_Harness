import { beforeEach, describe, expect, it } from "vitest";

import { createActionController } from "./actions";
import { MockDesktopBackend } from "./mockDesktopBackend";
import { desktopStore } from "../stores/desktopStore";

describe("MockDesktopBackend project and conversation flow", () => {
  beforeEach(() => {
    desktopStore.getState().setStatus("booting");
    desktopStore.getState().setComposerDraft("");
  });

  it("keeps project and chat selection in the same snapshot contract", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await controller.actions.createConversation(undefined, "新的协作聊天");
    const stateAfterCreate = desktopStore.getState();
    const createdConversationId = stateAfterCreate.currentConversationId;
    expect(stateAfterCreate.conversationsById[createdConversationId]?.title).toBe("新的协作聊天");

    await controller.actions.selectConversation("conv-1");
    expect(desktopStore.getState().currentConversationId).toBe("conv-1");
    expect(desktopStore.getState().projectsById["project-1"].conversations).toHaveLength(2);
  });

  it("routes mock streaming messages to the selected conversation", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      await controller.actions.submitMessage("继续看看", "character");
      const state = desktopStore.getState();
      const messageIds = state.messageIdsByConversation["conv-1"] ?? [];
      expect(messageIds).toHaveLength(4);
      expect(state.messagesById[messageIds.at(-1) ?? ""]?.source).toBe("character");
      expect(state.messagesById[messageIds.at(-1) ?? ""]?.streaming).toBe(false);
    } finally {
      unsubscribe();
    }
  });

  it("uses the selected folder name for new projects and auto-names the first chat", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      await controller.actions.createProject("C:/Projects/observatory");
      const stateAfterProject = desktopStore.getState();
      expect(stateAfterProject.projectsById[stateAfterProject.currentProjectId]?.name).toBe(
        "observatory",
      );

      await controller.actions.createConversation(undefined);
      const conversationId = desktopStore.getState().currentConversationId;
      expect(desktopStore.getState().conversationsById[conversationId]?.title).toBe("新聊天");
      await controller.actions.submitMessage("整理实验记录", "character");
      expect(desktopStore.getState().conversationsById[conversationId]?.title).toBe("关于整理实验记录");
    } finally {
      unsubscribe();
    }
  });

  it("archives a project even when it is the only project", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await controller.actions.archiveProject("project-1");

    const state = desktopStore.getState();
    expect(state.currentProjectId).toBe("");
    expect(state.currentConversationId).toBe("");
    expect(state.projectsById).toEqual({});
  });
});
