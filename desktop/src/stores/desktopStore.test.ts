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

  it("error.reported recoverable 入 Toast 队列（同 code+message 去重，最多 5 条）", () => {
    const reported = (sequence: number, code: string, message: string) => ({
      kind: "event" as const,
      event: "error.reported" as const,
      sequence,
      payload: { code, message, severity: "recoverable", source: "sidecar" },
    });
    desktopStore.getState().applyEvents([
      reported(1, "backend_disconnected", "Python Sidecar 已断开，正在重连…"),
      reported(2, "backend_disconnected", "Python Sidecar 已断开，正在重连…"),
      reported(3, "voice.tts", "语音合成失败：服务无响应"),
      reported(4, "dialogue.deepseek", "请求超时"),
    ]);
    let state = desktopStore.getState();
    // 同 code+message 去重；fatal 之外的错误保留 error 字段（既有语义）
    expect(state.toasts).toHaveLength(3);
    expect(state.toasts[0].kind).toBe("warning");
    expect(state.error).toBe("请求超时");

    // 超过 5 条只保留最新 5 条（最早的 Sidecar 断开被挤出）
    desktopStore.getState().applyEvents([
      reported(5, "a", "错误五"),
      reported(6, "b", "错误六"),
      reported(7, "c", "错误七"),
    ]);
    state = desktopStore.getState();
    expect(state.toasts).toHaveLength(5);
    expect(state.toasts.map((toast) => toast.text)).toEqual([
      "语音合成失败：服务无响应",
      "请求超时",
      "错误五",
      "错误六",
      "错误七",
    ]);

    // dismissToast 移除指定 Toast
    desktopStore.getState().dismissToast("c:错误七");
    expect(desktopStore.getState().toasts.map((toast) => toast.text)).toEqual([
      "语音合成失败：服务无响应",
      "请求超时",
      "错误五",
      "错误六",
    ]);
  });

  it("error.reported info 进 Toast，fatal 维持整屏接管", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "error.reported",
        sequence: 1,
        payload: { code: "voice.asr", message: "麦克风不可用", severity: "info" },
      },
    ]);
    expect(desktopStore.getState().toasts).toHaveLength(1);
    expect(desktopStore.getState().toasts[0].kind).toBe("info");

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "error.reported",
        sequence: 2,
        payload: { code: "sidecar", message: "后端崩溃", severity: "fatal" },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.status).toBe("error");
    expect(state.toasts).toHaveLength(1); // fatal 不进 Toast
  });

  it("error.reported 缺失 severity 按 fatal 处理", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "error.reported",
        sequence: 1,
        payload: { message: "未知错误" },
      },
    ]);
    expect(desktopStore.getState().status).toBe("error");
    expect(desktopStore.getState().toasts).toHaveLength(0);
  });

  it("account.changed 水合当前账号与账号列表", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "account.changed",
        sequence: 1,
        payload: {
          account: {
            account_id: "alice-1",
            username: "alice",
            display_name: "爱丽丝",
            avatar: "",
            last_login_at: null,
            onboarding_complete: false,
            theme: "dark",
          },
          accounts: [
            {
              account_id: "default-local",
              username: "default",
              display_name: "默认账号",
              avatar: "",
              last_login_at: null,
              onboarding_complete: false,
              theme: "dark",
              is_last_login: false,
            },
            {
              account_id: "alice-1",
              username: "alice",
              display_name: "爱丽丝",
              avatar: "",
              last_login_at: null,
              onboarding_complete: false,
              theme: "dark",
              is_last_login: true,
            },
          ],
        },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.currentAccountId).toBe("alice-1");
    expect(state.currentAccount?.username).toBe("alice");
    expect(state.accounts).toHaveLength(2);
    expect(state.accounts.find((item) => item.is_last_login)?.account_id).toBe("alice-1");
  });

  it("state.snapshot 保持事件序号，后续引导完成事件继续生效", () => {
    const pending = createMockScenario("onboarding-pending").snapshot;
    desktopStore.getState().hydrate({ ...pending, sequence: 0 });
    const pendingAccount = pending.current_account!;
    const completedAccount = { ...pendingAccount, onboarding_complete: true };

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "account.changed",
        sequence: 1,
        payload: { account: pendingAccount, accounts: pending.accounts },
      },
      {
        kind: "event",
        event: "state.snapshot",
        sequence: 2,
        payload: { ...pending, sequence: 2 },
      },
      {
        kind: "event",
        event: "account.changed",
        sequence: 3,
        payload: {
          account: completedAccount,
          accounts: pending.accounts.map((item) =>
            item.account_id === completedAccount.account_id
              ? { ...item, onboarding_complete: true }
              : item,
          ),
        },
      },
    ]);

    expect(desktopStore.getState().currentAccount?.onboarding_complete).toBe(true);
    expect(desktopStore.getState().lastSequence).toBe(3);
    expect(desktopStore.getState().needsBootstrap).toBe(false);
  });

  it("没有序号的协议错误不会触发重新引导", () => {
    desktopStore.getState().hydrate({ ...createMockScenario("onboarding-pending").snapshot, sequence: 2 });
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "error.reported",
        sequence: undefined as unknown as number,
        payload: { message: "未知协议错误" },
      },
    ]);
    expect(desktopStore.getState().needsBootstrap).toBe(false);
    expect(desktopStore.getState().lastSequence).toBe(2);
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
