import { beforeEach, describe, expect, it } from "vitest";

import type { DesktopEvent, DesktopSnapshot, ToolRun } from "../contracts/protocol";
import { createMockScenario } from "../mocks/scenarios";
import { presentAppShell } from "../presenters/presenters";
import { desktopStore } from "./desktopStore";

describe("desktopStore event projection", () => {
  beforeEach(() => {
    // M5.4 后 hydrate 会保留本地 Toast/config 缓存，且会重放水合前暂存事件；
    // 单测之间显式清空这些跨用例状态，避免前一个用例污染后续断言。
    desktopStore.setState({
      toasts: [],
      configSnapshot: null,
      lastSequence: -1,
      needsBootstrap: false,
      eventBuffer: [],
      streamId: null,
    });
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
    expect(state.toolIdsByConversation["other-conversation"]).toEqual([
      "other-conversation\u0000tool-1",
    ]);
    expect(state.messageIdsByConversation["conv-1"]).toEqual(["message-1", "message-2"]);
  });

  it("M4.4: 切回 chat 模式时 composerTarget 强制回到 character", () => {
    desktopStore.getState().setMode("collaboration");
    desktopStore.getState().setComposerTarget("assistant");
    expect(desktopStore.getState().composerTarget).toBe("assistant");

    desktopStore.getState().setMode("chat");
    expect(desktopStore.getState().mode).toBe("chat");
    expect(desktopStore.getState().composerTarget).toBe("character");
  });

  it("M4.1: 两个会话复用同一 tool_call_id 时互不覆盖", () => {
    const base = createMockScenario("single-project").snapshot;
    desktopStore.getState().hydrate({ ...base, sequence: 0 });
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "tool_run.upserted",
        sequence: 1,
        payload: {
          tool_run: {
            tool_call_id: "tool-dup",
            conversation_id: "conv-1",
            task_id: "task-1",
            engine_turn_id: "turn-1",
            sequence: 1,
            status: "running",
            title: "A 会话工具",
            summary: "",
            details: "",
          } satisfies ToolRun,
        },
      },
      {
        kind: "event",
        event: "tool_run.upserted",
        sequence: 2,
        payload: {
          tool_run: {
            tool_call_id: "tool-dup",
            conversation_id: "conv-2",
            task_id: "task-2",
            engine_turn_id: "turn-2",
            sequence: 1,
            status: "denied",
            title: "B 会话工具",
            summary: "沙箱拦截",
            details: "沙箱拦截",
          } satisfies ToolRun,
        },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.toolRunsById["conv-1\u0000tool-dup"]?.conversation_id).toBe("conv-1");
    expect(state.toolRunsById["conv-2\u0000tool-dup"]?.conversation_id).toBe("conv-2");
    expect(state.toolRunsById["tool-dup"]).toBeUndefined();
  });

  it("把角色思考与正文合并到同一条流式消息", () => {
    const messageId = "speech:conv-1:user-1";
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "message.delta",
        sequence: 1,
        payload: {
          message_id: messageId,
          conversation_id: "conv-1",
          source: "character",
          kind: "character.speech",
          channel: "reasoning",
          delta: "先看看",
          started: true,
          reasoning_streaming: true,
        },
      },
      {
        kind: "event",
        event: "message.delta",
        sequence: 2,
        payload: {
          message_id: messageId,
          conversation_id: "conv-1",
          source: "character",
          kind: "character.speech",
          delta: "你好。",
        },
      },
      {
        kind: "event",
        event: "message.created",
        sequence: 3,
        payload: {
          message: {
            message_id: messageId,
            conversation_id: "conv-1",
            pair_id: "pair-1",
            engine_turn_id: null,
            source: "character",
            kind: "character.speech",
            text: "你好。",
            payload: { reasoning: "先看看" },
            tts_eligible: true,
            created_at: "2026-08-11T00:00:00Z",
          },
        },
      },
    ]);

    const state = desktopStore.getState();
    expect(state.messageIdsByConversation["conv-1"]?.filter((id) => id === messageId)).toHaveLength(1);
    expect(state.messagesById[messageId]?.text).toBe("你好。");
    expect(state.messagesById[messageId]?.payload.reasoning).toBe("先看看");
    expect(state.messagesById[messageId]?.streaming).toBeUndefined();
  });

  it("把助手思考与正文合并到同一条流式消息", () => {
    const messageId = "assistant:conv-1:task-1";
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "message.delta",
        sequence: 1,
        payload: {
          message_id: messageId,
          conversation_id: "conv-1",
          source: "assistant",
          kind: "assistant.reasoning",
          channel: "summary",
          delta: "先检查项目。",
          reasoning_streaming: true,
        },
      },
      {
        kind: "event",
        event: "message.delta",
        sequence: 2,
        payload: {
          message_id: messageId,
          conversation_id: "conv-1",
          source: "assistant",
          kind: "assistant.natural_language",
          delta: "项目已检查。",
          reasoning_streaming: false,
        },
      },
    ]);

    const state = desktopStore.getState();
    expect(state.messageIdsByConversation["conv-1"]?.filter((id) => id === messageId)).toHaveLength(1);
    expect(state.messagesById[messageId]?.text).toBe("项目已检查。");
    expect(state.messagesById[messageId]?.payload.reasoning).toBe("先检查项目。");
    expect(state.messagesById[messageId]?.payload.reasoning_streaming).toBe(false);
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

  it("project.changed 只带项目字段时合并现有记录，不丢 conversations（白屏回归）", () => {
    const projectId = "project-1";
    const before = desktopStore.getState();
    const beforeProject = before.projectsById[projectId];
    expect(beforeProject?.conversations.length).toBeGreaterThan(0);
    const beforeConversationIds =
      beforeProject?.conversations.map((c) => c.conversation_id) ?? [];

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "project.changed",
        sequence: 1,
        payload: {
          // 后端设置类命令的定向响应形状：无 conversations 字段
          project: {
            project_id: projectId,
            name: "改名后的项目",
            root_path: before.projectsById[projectId].root_path,
            approval_mode: "review",
            reasoning_effort: "max",
            archived: false,
            created_at: null,
            last_opened_at: null,
            path_available: true,
          } as unknown as DesktopEvent["payload"],
        },
      },
    ]);

    const state = desktopStore.getState();
    const project = state.projectsById[projectId];
    expect(project.approval_mode).toBe("review");
    expect(project.reasoning_effort).toBe("max");
    // conversations 保留——presentAppShell 不会对 undefined 调用 map
    expect(project.conversations.map((c) => c.conversation_id)).toEqual(beforeConversationIds);
    const viewModel = presentAppShell(state).navigation?.projects.find(
      (item) => item.project_id === projectId,
    );
    expect(viewModel?.conversations).toBeDefined();
  });

  it("conversation.changed 同步更新项目内会话条目（标题自动生成可见）", () => {
    const projectId = "project-1";
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "conversation.changed",
        sequence: 1,
        payload: {
          conversation: {
            conversation_id: "conv-1",
            project_id: projectId,
            pair_id: "pair-1",
            title: "正在整理项目介绍",
            last_mode: "chat",
            archived: false,
            created_at: "2026-08-13T00:00:00Z",
            updated_at: "2026-08-13T00:00:00Z",
          },
        },
      },
    ]);
    const state = desktopStore.getState();
    // 侧栏渲染源 projectsById[].conversations 必须同步
    expect(state.projectsById[projectId].conversations[0].title).toBe("正在整理项目介绍");
    expect(presentAppShell(state).navigation?.projects[0].conversations[0].title).toBe(
      "正在整理项目介绍",
    );
  });

  it("turn.status_changed failed 清掉该会话 streaming 占位（三点不卡死）", () => {
    const messageId = "speech:conv-1:user-1";
    const turn = (
      sequence: number,
      status: string,
    ): DesktopEvent => ({
      kind: "event",
      event: sequence === 2 ? "turn.started" : "turn.status_changed",
      sequence,
      payload: {
        turn: {
          turn_id: "turn-1",
          account_id: "default-local",
          project_id: "project-1",
          conversation_id: "conv-1",
          target: "character",
          source_message_id: "user-1",
          status,
          created_at: "2026-08-13T00:00:00Z",
          updated_at: "2026-08-13T00:00:00Z",
        },
      },
    });
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "message.delta",
        sequence: 1,
        payload: {
          message_id: messageId,
          conversation_id: "conv-1",
          source: "character",
          kind: "character.speech",
          delta: "",
          started: true,
        },
      },
      turn(2, "running"),
    ]);
    expect(desktopStore.getState().messagesById[messageId]?.streaming).toBe(true);

    desktopStore.getState().applyEvents([turn(3, "failed")]);
    expect(desktopStore.getState().messagesById[messageId]?.streaming).toBe(false);
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

  it("V0.3.0: hydrateSnapshotState 正确水合 pairs 目录并在 snapshot 没有 pairs 时用 pair 兜底", () => {
    const scenario = createMockScenario("multi-pair");
    desktopStore.getState().hydrate(scenario.snapshot);
    const state = desktopStore.getState();
    expect(state.pairs).toHaveLength(3);
    expect(state.pairs.map((p) => p.pair_id)).toEqual([
      "phainon_ancient_machine",
      "firefly_sam",
      "march7_fourth_mirror",
    ]);

    // 没有 pairs 字段时，以 pair 构成单项目录兜底
    const { pairs: _pairs, ...withoutPairs } = scenario.snapshot;
    desktopStore.getState().hydrate(withoutPairs as unknown as DesktopSnapshot);
    expect(desktopStore.getState().pairs).toHaveLength(1);
    expect(desktopStore.getState().pairs[0].pair_id).toBe(scenario.snapshot.pair.pair_id);
  });

  it("M2.1: 新代次缓存业务事件，快照水合后只重放快照序号之后的事件", () => {
    const base = createMockScenario("single-project").snapshot;
    desktopStore.getState().hydrate({ ...base, stream_id: "old-stream", sequence: 2 });
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "connection.status",
        sequence: 99,
        stream_id: "new-stream",
        payload: { status: "connected", stream_id: "new-stream" },
      },
      {
        kind: "event",
        event: "message.created",
        sequence: 3,
        stream_id: "new-stream",
        payload: {
          message: {
            message_id: "stream-msg-3",
            conversation_id: "conv-1",
            pair_id: "pair-1",
            engine_turn_id: null,
            source: "assistant",
            kind: "assistant.natural_language",
            text: "新代次消息 3",
            payload: {},
            tts_eligible: true,
            created_at: "2026-08-14T00:00:00Z",
          },
        },
      },
      {
        kind: "event",
        event: "message.created",
        sequence: 4,
        stream_id: "new-stream",
        payload: {
          message: {
            message_id: "stream-msg-4",
            conversation_id: "conv-1",
            pair_id: "pair-1",
            engine_turn_id: null,
            source: "assistant",
            kind: "assistant.natural_language",
            text: "新代次消息 4",
            payload: {},
            tts_eligible: true,
            created_at: "2026-08-14T00:00:00Z",
          },
        },
      },
    ]);
    let state = desktopStore.getState();
    expect(state.streamId).toBe("new-stream");
    expect(state.needsBootstrap).toBe(true);
    expect(state.messagesById["stream-msg-3"]).toBeUndefined();

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "state.snapshot",
        sequence: 2,
        stream_id: "new-stream",
        payload: { ...base, stream_id: "new-stream", sequence: 2 },
      },
    ]);
    state = desktopStore.getState();
    expect(state.status).toBe("ready");
    expect(state.needsBootstrap).toBe(false);
    expect(state.messagesById["stream-msg-3"]?.text).toBe("新代次消息 3");
    expect(state.messagesById["stream-msg-4"]?.text).toBe("新代次消息 4");
  });

  it("M2.1: 旧代次快照不能覆盖新代次状态", () => {
    const base = createMockScenario("single-project").snapshot;
    desktopStore.getState().hydrate({ ...base, stream_id: "new-stream", sequence: 2 });
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "state.snapshot",
        sequence: 5,
        stream_id: "old-stream",
        payload: { ...base, stream_id: "old-stream", sequence: 5 },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.streamId).toBe("new-stream");
    expect(state.status).toBe("ready");
    expect(state.currentConversationId).toBe("conv-1");
  });

  it("M2.1: 同代次重复序号直接丢弃", () => {
    const base = createMockScenario("single-project").snapshot;
    desktopStore.getState().hydrate({ ...base, stream_id: "s1", sequence: 2 });
    const event = (sequence: number): DesktopEvent => ({
      kind: "event",
      event: "message.created",
      sequence,
      stream_id: "s1",
      payload: {
        message: {
          message_id: "dup-msg",
          conversation_id: "conv-1",
          pair_id: "pair-1",
          engine_turn_id: null,
          source: "assistant",
          kind: "assistant.natural_language",
          text: `重复 ${sequence}`,
          payload: {},
          tts_eligible: true,
          created_at: "2026-08-14T00:00:00Z",
        },
      },
    });
    desktopStore.getState().applyEvents([event(3), event(3)]);
    expect(desktopStore.getState().messagesById["dup-msg"]?.text).toBe("重复 3");
    expect(desktopStore.getState().lastSequence).toBe(3);
  });

  it("M2.1: 序号缺口触发 bootstrap 并暂存后续事件，快照核对后重放", () => {
    const base = createMockScenario("single-project").snapshot;
    desktopStore.getState().hydrate({ ...base, stream_id: "s1", sequence: 2 });
    const messageEvent = (sequence: number, messageId: string): DesktopEvent => ({
      kind: "event",
      event: "message.created",
      sequence,
      stream_id: "s1",
      payload: {
        message: {
          message_id: messageId,
          conversation_id: "conv-1",
          pair_id: "pair-1",
          engine_turn_id: null,
          source: "assistant",
          kind: "assistant.natural_language",
          text: `消息 ${sequence}`,
          payload: {},
          tts_eligible: true,
          created_at: "2026-08-14T00:00:00Z",
        },
      },
    });
    desktopStore.getState().applyEvents([messageEvent(4, "gap-msg-4")]);
    expect(desktopStore.getState().needsBootstrap).toBe(true);
    expect(desktopStore.getState().messagesById["gap-msg-4"]).toBeUndefined();

    desktopStore.getState().applyEvents([messageEvent(5, "gap-msg-5")]);
    expect(desktopStore.getState().eventBuffer).toHaveLength(2);

    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "state.snapshot",
        sequence: 3,
        stream_id: "s1",
        payload: { ...base, stream_id: "s1", sequence: 3 },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.needsBootstrap).toBe(false);
    expect(state.messagesById["gap-msg-4"]?.text).toBe("消息 4");
    expect(state.messagesById["gap-msg-5"]?.text).toBe("消息 5");
  });

  it("M5.4: message.status_changed 携带完整 Message 时先于 message.created 也能 upsert", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "message.status_changed",
        sequence: 1,
        payload: {
          message: {
            message_id: "early-status",
            conversation_id: "conv-1",
            pair_id: "pair-1",
            engine_turn_id: null,
            source: "user",
            kind: "user.text",
            text: "状态先到",
            payload: {},
            tts_eligible: false,
            created_at: "2026-08-15T00:00:00Z",
            status: "received",
          },
        },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.messagesById["early-status"]?.text).toBe("状态先到");
    expect(state.messagesById["early-status"]?.status).toBe("received");
    expect(state.messageIdsByConversation["conv-1"]).toContain("early-status");
  });

  it("M5.4: message.status_changed 缺少必要字段时触发 bootstrap 而不是静默丢弃", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "message.status_changed",
        sequence: 1,
        payload: { message: { message_id: "incomplete" } },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.needsBootstrap).toBe(true);
    expect(state.messagesById["incomplete"]).toBeUndefined();
  });

  it("M5.4: backend.ready 进入新 stream bootstrap 流程", () => {
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "backend.ready",
        sequence: 1,
        payload: { pid: 1234 },
      },
    ]);
    const state = desktopStore.getState();
    expect(state.status).toBe("booting");
    expect(state.needsBootstrap).toBe(true);
  });

  it("M5.4: state.snapshot 水合保留仍有效的 Toast 与 config 缓存", () => {
    desktopStore.getState().pushToast({
      id: "keep:toast",
      kind: "error",
      text: "保留我",
      hasDetails: true,
    });
    desktopStore.getState().setConfigSnapshot({ engine: "deepseek" });
    desktopStore.getState().hydrate({
      ...createMockScenario("single-project").snapshot,
      sequence: 5,
    });
    const state = desktopStore.getState();
    expect(state.toasts).toHaveLength(1);
    expect(state.toasts[0]?.text).toBe("保留我");
    expect(state.configSnapshot).toEqual({ engine: "deepseek" });
  });

  it("M5.4: A 会话任务不会让 B 会话显示为自己的 busy", () => {
    const base = createMockScenario("single-project").snapshot;
    const project = base.projects[0];
    const otherConversation = {
      ...project.conversations[0],
      conversation_id: "conv-b",
      title: "B 会话",
    };
    desktopStore.getState().hydrate({
      ...base,
      projects: [{ ...project, conversations: [otherConversation] }],
      current_conversation_id: "conv-b",
      current_conversation: otherConversation,
      sequence: 3,
    });
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "task.busy_changed",
        sequence: 4,
        payload: {
          busy: true,
          active_task: {
            project_id: "project-1",
            conversation_id: "conv-1",
            task_id: "task-a",
            engine_turn_id: null,
          },
        },
      },
    ]);
    expect(desktopStore.getState().busy).toBe(false);
    expect(desktopStore.getState().activeTask?.conversation_id).toBe("conv-1");
  });
});
