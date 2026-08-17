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

  it("createProject 取消文件夹时返回 false，带路径创建时返回 true", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    await expect(controller.actions.createProject()).resolves.toBe(false);
    await expect(controller.actions.createProject("C:/Projects/observatory")).resolves.toBe(true);
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

  it("reconnect 模拟断线-恢复并驱动连接状态机", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      expect(desktopStore.getState().status).toBe("ready");

      await controller.actions.reconnect();
      // 断线-恢复事件驱动 store：connected 进入 booting 并标记需要重新 bootstrap
      expect(desktopStore.getState().status).toBe("booting");
      expect(desktopStore.getState().needsBootstrap).toBe(true);

      // 与 AppController 的恢复流程一致：重新 bootstrap 后回到 ready
      await controller.loadBootstrap();
      expect(desktopStore.getState().status).toBe("ready");
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

  it("opens another chat through conversation.open without global selection", async () => {
    const backend = new MockDesktopBackend("multi-pair");
    const controller = createActionController(backend);
    await controller.loadBootstrap();

    expect(desktopStore.getState().currentConversationId).toBe("conv-firefly");
    await controller.actions.openConversationTab("conv-phainon");

    const state = desktopStore.getState();
    // conversation.open 只打开并聚焦本窗口标签，不改 Sidecar 全局当前聊天。
    expect(state.currentConversationId).toBe("conv-firefly");
    expect(state.activeConversationId).toBe("conv-phainon");
    expect(state.openConversationIds).toContain("conv-firefly");
    expect(state.openConversationIds).toContain("conv-phainon");
    expect(backend.recordedRequests.at(-1)?.method).toBe("conversation.open");
    expect(backend.recordedRequests.at(-1)?.params).toMatchObject({
      conversation_id: "conv-phainon",
    });
    expect(backend.recordedRequests.some((item) => item.method === "conversation.select")).toBe(
      false,
    );

    // 已打开的标签再次聚焦也要取权威快照，不能只切本地 ID。
    await controller.actions.openConversationTab("conv-firefly");
    expect(backend.recordedRequests.at(-1)?.method).toBe("conversation.open");
    expect(backend.recordedRequests.at(-1)?.params).toMatchObject({
      conversation_id: "conv-firefly",
    });
  });

  it("cancels only the matching conversation task in the mock protocol", async () => {
    const backend = new MockDesktopBackend("collaboration-running");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      await controller.actions.cancelTask();

      const request = backend.recordedRequests.at(-1);
      expect(request?.method).toBe("task.cancel");
      expect(request?.params).toEqual({
        conversation_id: "conv-1",
        task_id: "mock-task-1",
      });
      expect(desktopStore.getState().activeTask).toBeNull();
    } finally {
      unsubscribe();
    }
  });
});
