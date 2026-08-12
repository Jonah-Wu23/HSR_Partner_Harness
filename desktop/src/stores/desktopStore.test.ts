import { beforeEach, describe, expect, it } from "vitest";

import type { DesktopEvent, ToolRun } from "../contracts/protocol";
import { createMockScenario } from "../mocks/scenarios";
import { presentAppShell } from "../presenters/presenters";
import { desktopStore } from "./desktopStore";

describe("desktopStore event projection", () => {
  beforeEach(() => {
    desktopStore.getState().hydrate(createMockScenario("single-project").snapshot);
  });

  it("keeps streaming messages and tools attached to their origin chat", () => {
    const events: DesktopEvent[] = [
      {
        kind: "event",
        event: "message.delta",
        sequence: 1,
        payload: {
          message_id: "stream-other",
          conversation_id: "other-conversation",
          source: "assistant",
          kind: "assistant.natural_language",
          delta: "来自另一聊天",
        },
      },
      {
        kind: "event",
        event: "tool_run.upserted",
        sequence: 2,
        payload: {
          tool_run: {
            tool_call_id: "tool-1",
            conversation_id: "other-conversation",
            task_id: "task-1",
            engine_turn_id: "turn-1",
            sequence: 1,
            status: "running",
            title: "读取文件",
            summary: "进行中",
            details: "",
          } satisfies ToolRun,
        },
      },
    ];
    desktopStore.getState().applyEvents(events);

    const state = desktopStore.getState();
    expect(state.messageIdsByConversation["other-conversation"]).toEqual(["stream-other"]);
    expect(state.toolIdsByConversation["other-conversation"]).toEqual(["tool-1"]);
    expect(state.messageIdsByConversation["conv-1"]).toEqual(["message-1", "message-2"]);
  });

  it("connection.status 断线切换状态但保留已加载内容", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "connection.status",
        sequence: 1,
        payload: { status: "disconnected" },
      },
      {
        kind: "event",
        event: "error.reported",
        sequence: 2,
        payload: {
          code: "backend_disconnected",
          message: "Python Sidecar 已断开，正在重连…",
          severity: "recoverable",
          source: "sidecar",
        },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.status).toBe("disconnected");
    expect(state.needsBootstrap).toBe(false);
    expect(state.error).toBe("Python Sidecar 已断开，正在重连…");
    // 已加载内容保留，不整屏接管
    expect(state.conversationsById["conv-1"]).toBeDefined();
    expect(state.messagesById["message-1"]).toBeDefined();
  });

  it("connection.status 恢复后进入 booting 并请求重新 bootstrap", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "connection.status",
        sequence: 1,
        payload: { status: "disconnected" },
      },
      {
        kind: "event",
        event: "connection.status",
        sequence: 2,
        payload: { status: "connected" },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.status).toBe("booting");
    expect(state.needsBootstrap).toBe(true);
  });

  it("locks approval actions until the resolved event arrives", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "approval.requested",
        sequence: 1,
        payload: {
          approval_id: "approval-1",
          conversation_id: "conv-1",
          operation: {
            tool_kind: "shell",
            command: "pytest -q",
            paths: [],
            patch_file_count: null,
            summary: "运行测试",
          },
          reason: "需要审批",
        },
      },
    ]);
    desktopStore.getState().setApprovalResolving("approval-1", true);
    expect(presentAppShell(desktopStore.getState()).approval.pending[0].resolving).toBe(true);

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "approval.resolved",
        sequence: 2,
        payload: { approval_id: "approval-1" },
      },
    ]);
    expect(presentAppShell(desktopStore.getState()).approval.pending).toEqual([]);
    expect(desktopStore.getState().approvalResolvingById).toEqual({});
  });
});
